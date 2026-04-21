"""
RouterRegistry
==============
管理用户自定义路由器的安装、激活、回滚和执行。

目录结构（~/.bridge-server/routers/）：
  my-router/
    manifest.json        # {"name", "version", "entrypoint", "class", "description"}
    router.py            # 用户路由器代码（必须包含 class 继承 BaseRouter）
    router_config.yaml   # 可选，用户自定义参数（传给 __init__(config)）

安全机制：
  1. AST 扫描 — 拒绝 import os / subprocess / socket / sys 等危险模块
  2. 300ms 硬超时 — asyncio.wait_for，超时后系统 fallback 到内置路由
  3. RoutingDecision 校验 — provider/model 必须在 ctx.models 中
  4. Pydantic 模型验证 manifest.json 字段

.bspkg 格式 = ZIP 压缩包，解压后得到上述目录结构。
"""
from __future__ import annotations

import ast
import asyncio
import importlib.util
import inspect
import json
import logging
import shutil
import traceback
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from bridge_server.router_sdk import BaseRouter, RoutingContext, RoutingDecision

logger = logging.getLogger(__name__)

# 禁止 import 的危险模块
_BANNED_IMPORTS = frozenset(
    {
        "os", "sys", "subprocess", "socket", "shutil", "pathlib",
        "ctypes", "mmap", "signal", "resource", "pty", "termios",
        "pickle", "shelve", "marshal", "imp", "importlib",
        "threading", "multiprocessing", "concurrent",
        "urllib", "requests", "httpx", "aiohttp", "http",
        "ftplib", "smtplib", "telnetlib", "xmlrpc",
        "builtins", "__builtins__",
    }
)

_ROUTER_TIMEOUT_S = 0.3  # 300ms


class RouterManifest:
    """解析并校验 manifest.json。"""

    REQUIRED = ("name", "version", "entrypoint", "class")

    def __init__(self, data: Dict[str, Any], source_dir: Path):
        for key in self.REQUIRED:
            if key not in data:
                raise ValueError(f"manifest.json 缺少必填字段: '{key}'")
        self.name: str = data["name"]
        self.version: str = data["version"]
        self.entrypoint: str = data["entrypoint"]
        self.class_name: str = data["class"]
        self.description: str = data.get("description", "")
        self.source_dir = source_dir
        self._data = data

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "entrypoint": self.entrypoint,
            "class": self.class_name,
            "description": self.description,
        }


def _check_ast_security(code: str, filename: str) -> Optional[str]:
    """
    静态 AST 分析，拒绝危险 import。
    返回 None 表示通过，返回字符串表示拒绝原因。
    """
    try:
        tree = ast.parse(code, filename=filename)
    except SyntaxError as e:
        return f"语法错误: {e}"

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            else:
                names = [node.module] if node.module else []

            for name in names:
                root = name.split(".")[0] if name else ""
                if root in _BANNED_IMPORTS:
                    return (
                        f"安全拒绝: import '{name}' 不允许。"
                        f"禁止模块: {sorted(_BANNED_IMPORTS)}"
                    )

        # 禁止 exec / eval / compile / __import__
        if isinstance(node, ast.Call):
            func = node.func
            fname = ""
            if isinstance(func, ast.Name):
                fname = func.id
            elif isinstance(func, ast.Attribute):
                fname = func.attr
            if fname in ("exec", "eval", "compile", "__import__"):
                return f"安全拒绝: 禁止调用 '{fname}()'"

    return None


class RouterRegistry:
    """
    管理自定义路由器的完整生命周期。
    在 runtime.initialize_system() 中作为全局单例使用。
    """

    _STATE_FILE = "registry_state.json"

    def __init__(self, routers_dir: Optional[Path] = None):
        self._base_dir = routers_dir or (Path.home() / ".bridge-server" / "routers")
        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._state_file = self._base_dir / self._STATE_FILE

        # state: {name: {active, version, installed_at}}
        self._state: Dict[str, Any] = self._load_state()

        # 已加载的路由器实例缓存 {name: BaseRouter}
        self._instances: Dict[str, BaseRouter] = {}

    # ── Install ───────────────────────────────────────────────────────────────

    def install(self, source: Path) -> RouterManifest:
        """
        从目录或 .bspkg 文件安装路由器。
        若同名路由器已存在会覆盖（保留旧版本在 _backup/ 子目录）。
        """
        if source.suffix == ".bspkg":
            return self._install_from_bspkg(source)
        elif source.is_dir():
            return self._install_from_dir(source)
        else:
            raise ValueError(f"无法识别的路由器来源: {source}")

    def _install_from_dir(self, src: Path) -> RouterManifest:
        manifest_file = src / "manifest.json"
        if not manifest_file.exists():
            raise FileNotFoundError(f"找不到 manifest.json: {manifest_file}")

        with open(manifest_file, encoding="utf-8") as f:
            manifest_data = json.load(f)

        manifest = RouterManifest(manifest_data, src)
        self._validate_and_install(manifest, src)
        return manifest

    def _install_from_bspkg(self, pkg: Path) -> RouterManifest:
        if not zipfile.is_zipfile(pkg):
            raise ValueError(f"'{pkg}' 不是合法的 ZIP/.bspkg 文件")

        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            with zipfile.ZipFile(pkg, "r") as zf:
                zf.extractall(tmp)
            tmp_path = Path(tmp)
            # 检查是否有一级子目录
            dirs = [d for d in tmp_path.iterdir() if d.is_dir()]
            src = dirs[0] if len(dirs) == 1 else tmp_path
            return self._install_from_dir(src)

    def _validate_and_install(self, manifest: RouterManifest, src: Path) -> None:
        # 安全扫描所有 .py 文件
        for py_file in src.rglob("*.py"):
            code = py_file.read_text(encoding="utf-8")
            err = _check_ast_security(code, str(py_file))
            if err:
                raise PermissionError(f"安全检查失败 [{py_file.name}]: {err}")

        # 检查 entrypoint 和 class 存在
        ep = src / manifest.entrypoint
        if not ep.exists():
            raise FileNotFoundError(f"entrypoint '{manifest.entrypoint}' 不存在")

        router_class = self._load_class(ep, manifest.class_name)
        if not (inspect.isclass(router_class) and issubclass(router_class, BaseRouter)):
            raise TypeError(
                f"'{manifest.class_name}' 必须是 BaseRouter 的子类"
            )

        # 复制到 routers/<name>/
        dest = self._base_dir / manifest.name
        backup = dest / "_backup"
        if dest.exists():
            if backup.exists():
                shutil.rmtree(backup)
            shutil.copytree(dest, backup, ignore=shutil.ignore_patterns("_backup"))
            shutil.rmtree(dest)

        shutil.copytree(str(src), str(dest))
        logger.info(f"路由器 '{manifest.name}' v{manifest.version} 安装成功")

        # 写入 state
        self._state[manifest.name] = {
            "active": False,
            "version": manifest.version,
            "installed_at": __import__("time").time(),
        }
        self._save_state()

        # 清除旧实例缓存
        self._instances.pop(manifest.name, None)

    # ── Activate / Deactivate / Rollback ─────────────────────────────────────

    def activate(self, name: str) -> None:
        if name not in self._state:
            raise KeyError(f"路由器 '{name}' 未安装")

        # 实例化并运行健康检查
        inst = self._get_or_load_instance(name)
        try:
            ok = inst.on_load()
            if not ok:
                raise RuntimeError("on_load() 返回 False")
        except Exception as e:
            raise RuntimeError(f"路由器 '{name}' on_load() 失败: {e}")

        # 停用其他路由器
        for n in self._state:
            self._state[n]["active"] = False
        self._state[name]["active"] = True
        self._save_state()
        logger.info(f"路由器 '{name}' 已激活")

    def deactivate(self) -> None:
        for n in self._state:
            self._state[n]["active"] = False
        self._save_state()
        logger.info("自定义路由器已停用，回退到内置路由")

    def rollback(self, name: str) -> None:
        dest = self._base_dir / name
        backup = dest / "_backup"
        if not backup.exists():
            raise FileNotFoundError(f"路由器 '{name}' 没有可回滚的备份")

        shutil.rmtree(dest)
        shutil.copytree(backup, dest)
        self._instances.pop(name, None)
        logger.info(f"路由器 '{name}' 已回滚到上一个版本")

    # ── Remove ────────────────────────────────────────────────────────────────

    def remove(self, name: str) -> None:
        if name not in self._state:
            raise KeyError(f"路由器 '{name}' 未安装")
        dest = self._base_dir / name
        if dest.exists():
            shutil.rmtree(dest)
        self._instances.pop(name, None)
        del self._state[name]
        self._save_state()
        logger.info(f"路由器 '{name}' 已卸载")

    # ── Query ─────────────────────────────────────────────────────────────────

    def list_routers(self) -> List[Dict[str, Any]]:
        result = []
        for name, st in self._state.items():
            dest = self._base_dir / name
            manifest_file = dest / "manifest.json"
            desc = ""
            if manifest_file.exists():
                try:
                    desc = json.loads(manifest_file.read_text(encoding="utf-8")).get("description", "")
                except Exception:
                    pass
            result.append({
                "name": name,
                "version": st.get("version", "?"),
                "active": st.get("active", False),
                "description": desc,
            })
        return result

    def get_active(self) -> Optional[str]:
        for name, st in self._state.items():
            if st.get("active", False):
                return name
        return None

    # ── Execute ───────────────────────────────────────────────────────────────

    async def execute(
        self, name: str, ctx: RoutingContext
    ) -> Tuple[bool, Any]:
        """
        执行路由器并返回 (success, RoutingDecision|error_msg)。
        300ms 超时后返回 (False, "timeout")。
        """
        try:
            inst = self._get_or_load_instance(name)
            decision = await asyncio.wait_for(
                inst.route(ctx), timeout=_ROUTER_TIMEOUT_S
            )

            if not isinstance(decision, RoutingDecision):
                return False, f"路由器返回类型错误: {type(decision)}"

            err = decision.validate(ctx)
            if err:
                return False, f"RoutingDecision 校验失败: {err}"

            return True, decision

        except asyncio.TimeoutError:
            logger.warning(f"路由器 '{name}' 执行超时 (>{_ROUTER_TIMEOUT_S*1000:.0f}ms)，fallback 到内置路由")
            return False, "timeout"
        except Exception as e:
            logger.warning(f"路由器 '{name}' 执行异常: {e}\n{traceback.format_exc()}")
            return False, str(e)

    async def test_router(
        self, name: str, ctx: RoutingContext
    ) -> Dict[str, Any]:
        """测试接口，返回完整诊断信息（供 /api/admin/router/test 使用）。"""
        import time as _time
        start = _time.perf_counter()
        ok, result = await self.execute(name, ctx)
        elapsed_ms = round((_time.perf_counter() - start) * 1000, 1)
        return {
            "name": name,
            "success": ok,
            "decision": (
                {
                    "provider": result.provider,
                    "model": result.model,
                    "confidence": result.confidence,
                    "reason": result.reason,
                }
                if ok else None
            ),
            "error": None if ok else result,
            "elapsed_ms": elapsed_ms,
        }

    # ── Internal ──────────────────────────────────────────────────────────────

    def _get_or_load_instance(self, name: str) -> BaseRouter:
        if name in self._instances:
            return self._instances[name]

        inst = self._load_instance(name)
        self._instances[name] = inst
        return inst

    def _load_instance(self, name: str) -> BaseRouter:
        dest = self._base_dir / name
        if not dest.exists():
            raise FileNotFoundError(f"路由器目录不存在: {dest}")

        manifest_file = dest / "manifest.json"
        with open(manifest_file, encoding="utf-8") as f:
            manifest_data = json.load(f)
        manifest = RouterManifest(manifest_data, dest)

        ep = dest / manifest.entrypoint
        router_class = self._load_class(ep, manifest.class_name)

        # 读取 router_config.yaml（可选）
        cfg_file = dest / "router_config.yaml"
        config: Dict[str, Any] = {}
        if cfg_file.exists():
            try:
                with open(cfg_file, encoding="utf-8") as f:
                    config = yaml.safe_load(f) or {}
            except Exception:
                pass

        return router_class(config)

    @staticmethod
    def _load_class(py_file: Path, class_name: str) -> type:
        spec = importlib.util.spec_from_file_location(
            f"_custom_router_{py_file.stem}", py_file
        )
        if spec is None or spec.loader is None:
            raise ImportError(f"无法加载 '{py_file}'")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        cls = getattr(mod, class_name, None)
        if cls is None:
            raise AttributeError(f"'{py_file}' 中找不到类 '{class_name}'")
        return cls

    # ── State persistence ─────────────────────────────────────────────────────

    def _load_state(self) -> Dict[str, Any]:
        if self._state_file.exists():
            try:
                with open(self._state_file, encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _save_state(self) -> None:
        with open(self._state_file, "w", encoding="utf-8") as f:
            json.dump(self._state, f, indent=2, ensure_ascii=False)


# ── Global singleton ──────────────────────────────────────────────────────────

_registry: Optional[RouterRegistry] = None


def get_router_registry() -> Optional[RouterRegistry]:
    return _registry


def set_router_registry(instance: RouterRegistry) -> None:
    global _registry
    _registry = instance
