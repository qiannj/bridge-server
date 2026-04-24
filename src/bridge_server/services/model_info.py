"""
ModelInfoAggregator
===================
后台定时聚合所有可用模型的完整信息快照，供自定义路由器的 RoutingContext 使用。

数据来源（按优先级叠加）：
  1. config.yaml         → provider 基本配置、model input/output cost
  2. runtime provider_manager → provider health 状态
  3. usage.db (5分钟滚动) → 延迟 p50/p99、错误率
  4. benchmarks.json     → 模型能力评分（来自 cli/model-benchmark.py）

刷新间隔：30 秒（后台 asyncio 任务）。
路由器读取的是只读快照，不阻塞请求路径。
"""
from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from bridge_server.router_sdk import (
    ModelCapabilities,
    ModelInfo,
    ModelMetrics,
)

logger = logging.getLogger(__name__)

_REFRESH_INTERVAL_S = 30  # seconds between background refreshes


class ModelInfoAggregator:
    """
    聚合模型元信息，提供只读快照给路由器使用。
    在 runtime.initialize_system() 中调用 start() 启动后台刷新。
    """

    def __init__(self, config_dir: Optional[Path] = None):
        self._config_dir = config_dir or Path.home() / ".bridge-server"
        self._snapshot: List[ModelInfo] = []
        self._lock = asyncio.Lock()
        self._refresh_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """启动聚合器（立即刷新一次 + 开启后台定时刷新）。"""
        await self._refresh()
        self._refresh_task = asyncio.create_task(self._background_loop())
        logger.info(f"ModelInfoAggregator 启动，当前快照 {len(self._snapshot)} 个模型")

    async def stop(self) -> None:
        if self._refresh_task:
            self._refresh_task.cancel()
            try:
                await self._refresh_task
            except asyncio.CancelledError:
                pass

    def get_snapshot(self) -> List[ModelInfo]:
        """返回最新快照（只读副本，线程安全）。"""
        return list(self._snapshot)

    # ── Background loop ───────────────────────────────────────────────────────

    async def _background_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(_REFRESH_INTERVAL_S)
                await self._refresh()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"ModelInfo 后台刷新失败: {e}")

    async def _refresh(self) -> None:
        async with self._lock:
            try:
                config = self._load_config()
                health_map = self._load_health()
                metrics_map = self._load_metrics()
                bench_map = self._load_benchmarks()

                models: List[ModelInfo] = []
                for prov in config.get("providers", []):
                    pname = prov.get("name", "")
                    health_status = health_map.get(pname, "unknown")

                    for m in prov.get("models", []):
                        if isinstance(m, dict):
                            mid = m.get("id", "")
                            dname = m.get("name", mid)
                            ic = float(m.get("input_cost", 0.0) or 0.0)
                            oc = float(m.get("output_cost", 0.0) or 0.0)
                            tags = list(m.get("tags", []) or [])
                        else:
                            mid = str(m)
                            dname = mid
                            ic = oc = 0.0
                            tags = []

                        if not mid:
                            continue

                        key = f"{pname}/{mid}"
                        caps_raw = bench_map.get(key, {})
                        met_raw = metrics_map.get(key, {})

                        models.append(ModelInfo(
                            provider=pname,
                            model_id=mid,
                            display_name=dname,
                            health=health_status,
                            input_cost_per_1k=ic,
                            output_cost_per_1k=oc,
                            capabilities=ModelCapabilities(
                                coding=float(caps_raw.get("coding", 0.0)),
                                reasoning=float(caps_raw.get("reasoning", 0.0)),
                                creative=float(caps_raw.get("creative", 0.0)),
                                tool_use=float(caps_raw.get("tool_use", 0.0)),
                                context_length=int(caps_raw.get("context_length", 4096)),
                            ),
                            metrics=ModelMetrics(
                                latency_p50_ms=float(met_raw.get("p50", 0.0)),
                                latency_p99_ms=float(met_raw.get("p99", 0.0)),
                                error_rate=float(met_raw.get("error_rate", 0.0)),
                                is_rate_limited=bool(met_raw.get("rate_limited", False)),
                            ),
                            tags=tags,
                        ))

                self._snapshot = models
                logger.debug(f"ModelInfo 快照刷新完成: {len(models)} 个模型")

            except Exception as e:
                logger.error(f"ModelInfo 刷新出错: {e}", exc_info=True)

    # ── Data loaders ──────────────────────────────────────────────────────────

    def _load_config(self) -> Dict[str, Any]:
        cfg_file = self._config_dir / "config.yaml"
        if not cfg_file.exists():
            return {}
        with open(cfg_file, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def _load_health(self) -> Dict[str, str]:
        """
        从 runtime 模块读取 provider 健康状态。
        返回 {provider_name: "healthy"|"degraded"|"down"|"unknown"}
        """
        try:
            import sys
            rt = sys.modules.get("bridge_server.runtime")
            if rt is None:
                return {}
            pm = getattr(rt, "provider_manager", None)
            if pm is None:
                return {}

            # ProviderManager 在 health_check 后会维护 _health 或 _providers 列表
            # 尝试多种属性名
            if hasattr(pm, "_health"):
                return {k: str(v) for k, v in pm._health.items()}

            # Fallback: iterate providers and check status
            health: Dict[str, str] = {}
            providers = getattr(pm, "_providers", [])
            for p in providers:
                pid = getattr(p, "provider_id", None) or getattr(p, "id", None)
                status = getattr(p, "status", None)
                if pid:
                    health[pid] = str(status) if status else "unknown"
            return health
        except Exception as e:
            logger.debug(f"读取 provider health 失败: {e}")
            return {}

    def _load_metrics(self) -> Dict[str, Dict[str, Any]]:
        """
        从 usage.db 加载最近 5 分钟的滚动指标。
        Returns {provider/model: {p50, p99, error_rate}}
        """
        db_path = self._config_dir / "usage.db"
        if not db_path.exists():
            return {}
        since = time.time() - 300  # 5 minutes
        try:
            conn = sqlite3.connect(str(db_path))
            rows = conn.execute(
                """
                SELECT
                    provider,
                    model,
                    AVG(duration_ms)                        AS p50,
                    MAX(duration_ms)                        AS p99,
                    1.0 - AVG(CAST(success AS REAL))        AS error_rate
                FROM usage_records
                WHERE timestamp >= ?
                GROUP BY provider, model
                """,
                (since,),
            ).fetchall()
            conn.close()

            result: Dict[str, Dict[str, Any]] = {}
            for row in rows:
                key = f"{row[0]}/{row[1]}"
                result[key] = {
                    "p50": round(row[2] or 0.0, 1),
                    "p99": round(row[3] or 0.0, 1),
                    "error_rate": round(row[4] or 0.0, 4),
                    "rate_limited": False,
                }
            return result
        except Exception as e:
            logger.warning(f"加载 usage metrics 失败: {e}")
            return {}

    def _load_benchmarks(self) -> Dict[str, Dict[str, Any]]:
        """
        从 ~/.bridge-server/benchmarks.json 加载能力评分。
        格式: {"provider/model": {"coding": 0.9, "reasoning": 0.85, ...}}
        由 cli/model-benchmark.py 写入。
        """
        bench_file = self._config_dir / "benchmarks.json"
        if not bench_file.exists():
            return {}
        try:
            with open(bench_file, encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"加载 benchmarks.json 失败: {e}")
            return {}


# ── Global singleton ──────────────────────────────────────────────────────────

_aggregator: Optional[ModelInfoAggregator] = None


def get_model_info_aggregator() -> Optional[ModelInfoAggregator]:
    """返回全局聚合器实例（在 runtime.initialize_system() 中创建并 start()）。"""
    return _aggregator


def set_model_info_aggregator(instance: ModelInfoAggregator) -> None:
    global _aggregator
    _aggregator = instance
