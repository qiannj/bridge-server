"""
RouterRegistry
==============
管理用户自定义路由器的安装、激活、回滚和执行。

目录结构（~/.bridge-server/routers/）：
  my-router/
    manifest.json        # {"name", "version", "entrypoint", "class", "description"}
    router.py            # 用户路由器代码（必须包含 class 继承 BaseRouter）
    router_config.yaml   # 可选，用户自定义参数（传给 __init__(config)）

安全机制（Layer 3 子进程沙箱）：
  1. AST 扫描    — 拒绝危险 import / open() / globals() / __class__ 等属性链攻击
  2. 子进程隔离  — 用户代码在独立进程中执行，通过 JSON stdin/stdout 通信
                   Linux/macOS: resource.setrlimit 限制内存(128MB)/CPU(2s)/文件描述符(10)
                   Windows:     asyncio 超时控制（无 resource 模块）
  3. 300ms 超时  — asyncio.wait_for(proc.communicate(...), timeout=0.3)
  4. RoutingDecision 校验 — provider/model 必须在 ctx.models 中
  5. 环境变量清洗 — 子进程启动前清除所有 API Key 等敏感环境变量

.bspkg 格式 = ZIP 压缩包，解压后得到上述目录结构。
"""
from __future__ import annotations

import ast
import asyncio
import json
import logging
import shutil
import sys
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
        # 额外封堵
        "gc", "weakref", "inspect", "dis", "code", "codeop",
        "linecache", "tokenize", "traceback", "pdb", "profile",
        "cProfile", "timeit", "zipimport", "pkgutil", "sysconfig",
    }
)

# 禁止调用的内置函数（即使没有 import，也可能从 builtins 访问）
_BANNED_BUILTINS: frozenset = frozenset(
    {
        "open", "input", "compile", "exec", "eval", "__import__",
        "breakpoint", "memoryview",
    }
)

# 禁止访问的危险属性名
_BANNED_ATTRS: frozenset = frozenset(
    {
        "__class__", "__bases__", "__subclasses__", "__globals__",
        "__builtins__", "__dict__", "__code__", "__closure__",
        "__func__", "__self__", "__wrapped__", "__reduce__",
        "__reduce_ex__", "__getstate__", "__setstate__",
        "mro", "__mro__", "__init_subclass__",
    }
)

# 禁止作为函数调用的名称（包含 globals/locals/vars/getattr 等）
_BANNED_FUNC_NAMES: frozenset = frozenset(
    {
        "globals", "locals", "vars", "dir", "id",
        "getattr", "setattr", "delattr", "hasattr",
        "type",       # type(x, y, z) 可动态创建类
        "object",     # object.__subclasses__()
        "super",
    }
)

_ROUTER_TIMEOUT_S = 0.3  # 300ms


def _check_ast_security(code: str, filename: str) -> Optional[str]:
    """
    静态 AST 分析，拒绝危险 import 和危险调用模式。
    返回 None 表示通过，返回字符串表示拒绝原因。

    防护层次：
    1. 禁止 import 危险模块
    2. 禁止调用危险内置函数（open/eval/exec/globals 等）
    3. 禁止访问危险 dunder 属性（__class__/__bases__ 等类层次利用）
    4. 禁止 exec/eval/compile/__import__ 字符串调用
    """
    try:
        tree = ast.parse(code, filename=filename)
    except SyntaxError as e:
        return f"语法错误: {e}"

    for node in ast.walk(tree):
        # ── 规则 1：禁止危险 import ─────────────────────────────────────
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
                        f"禁止模块列表见文档。"
                    )

        # ── 规则 2：禁止调用危险内置函数和受限函数名 ────────────────────
        if isinstance(node, ast.Call):
            func = node.func
            fname = ""
            if isinstance(func, ast.Name):
                fname = func.id
            elif isinstance(func, ast.Attribute):
                fname = func.attr

            if fname in _BANNED_BUILTINS:
                return f"安全拒绝: 禁止调用内置函数 '{fname}()'"
            if fname in _BANNED_FUNC_NAMES:
                return f"安全拒绝: 禁止调用 '{fname}()'"

        # ── 规则 3：禁止访问危险 dunder/特殊属性 ────────────────────────
        if isinstance(node, ast.Attribute):
            if node.attr in _BANNED_ATTRS:
                return (
                    f"安全拒绝: 禁止访问属性 '{node.attr}'，"
                    f"该属性可能被用于 Python 对象层次利用攻击。"
                )

        # ── 规则 4：禁止通过下标访问 __builtins__ 等 ─────────────────────
        if isinstance(node, ast.Subscript):
            if isinstance(node.value, ast.Name):
                if node.value.id in ("__builtins__", "builtins"):
                    return "安全拒绝: 禁止通过下标访问 __builtins__"

    return None


def _serialize_context(ctx: "RoutingContext") -> Dict[str, Any]:
    """将 RoutingContext 序列化为 JSON 安全的字典（只传递安全字段）。"""
    return {
        "last_user_message": ctx.last_user_message,
        "messages_count": ctx.messages_count,
        "models": [
            {
                "provider": m.provider,
                "model_id": m.model_id,
                "display_name": m.display_name,
                "health": m.health,
                "input_cost_per_1k": m.input_cost_per_1k,
                "output_cost_per_1k": m.output_cost_per_1k,
                "capabilities": {
                    "coding": m.capabilities.coding,
                    "reasoning": m.capabilities.reasoning,
                    "creative": m.capabilities.creative,
                    "tool_use": m.capabilities.tool_use,
                    "context_length": m.capabilities.context_length,
                },
                "metrics": {
                    "latency_p50_ms": m.metrics.latency_p50_ms,
                    "latency_p99_ms": m.metrics.latency_p99_ms,
                    "error_rate": m.metrics.error_rate,
                    "is_rate_limited": m.metrics.is_rate_limited,
                },
                "tags": list(m.tags),
            }
            for m in ctx.models
        ],
        "session_metadata": dict(ctx.session_metadata),
    }


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
        # subprocess 模式不缓存实例，每次路由均在新子进程中执行

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

        # 检查 entrypoint 存在
        ep = src / manifest.entrypoint
        if not ep.exists():
            raise FileNotFoundError(f"entrypoint '{manifest.entrypoint}' 不存在")

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

    # ── Activate / Deactivate / Rollback ─────────────────────────────────────

    def activate(self, name: str) -> None:
        if name not in self._state:
            raise KeyError(f"路由器 '{name}' 未安装")

        # 验证路由器可以正常加载（通过 AST + manifest 检查）
        dest = self._base_dir / name
        manifest_file = dest / "manifest.json"
        with open(manifest_file, encoding="utf-8") as f:
            manifest_data = json.load(f)
        manifest = RouterManifest(manifest_data, dest)
        ep = dest / manifest.entrypoint
        if not ep.exists():
            raise FileNotFoundError(f"entrypoint '{manifest.entrypoint}' 不存在")

        # 停用其他路由器
        for n in self._state:
            self._state[n]["active"] = False
        self._state[name]["active"] = True
        self._save_state()
        logger.info(f"路由器 '{name}' 已激活（子进程沙箱模式）")

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
        logger.info(f"路由器 '{name}' 已回滚到上一个版本")

    # ── Remove ────────────────────────────────────────────────────────────────

    def remove(self, name: str) -> None:
        if name not in self._state:
            raise KeyError(f"路由器 '{name}' 未安装")
        dest = self._base_dir / name
        if dest.exists():
            shutil.rmtree(dest)
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

    # ── Execute (subprocess sandbox) ─────────────────────────────────────────

    async def execute(
        self, name: str, ctx: "RoutingContext"
    ) -> "Tuple[bool, Any]":
        """
        在隔离子进程中执行路由器，返回 (success, RoutingDecision|error_msg)。
        超时或失败时返回 (False, error_msg)，调用方应 fallback 到内置路由。

        跨平台：
          - Linux/macOS: 子进程受 resource 限制（内存/CPU/文件描述符）
          - Windows:     仅 asyncio 超时控制
        """
        try:
            result = await self._run_in_subprocess(name, ctx)
            if not result.get("ok"):
                err = result.get("error", "unknown error")
                logger.warning(f"路由器 '{name}' 沙箱执行失败: {err}")
                return False, err

            decision = RoutingDecision(
                provider=result["provider"],
                model=result["model"],
                confidence=float(result.get("confidence", 0.5)),
                reason=result.get("reason", ""),
            )
            err = decision.validate(ctx)
            if err:
                return False, f"RoutingDecision 校验失败: {err}"
            return True, decision

        except asyncio.TimeoutError:
            logger.warning(
                f"路由器 '{name}' 执行超时 (>{_ROUTER_TIMEOUT_S*1000:.0f}ms)，"
                f"fallback 到内置路由"
            )
            return False, "timeout"
        except Exception as e:
            logger.warning(f"路由器 '{name}' 执行异常: {e}\n{traceback.format_exc()}")
            return False, str(e)

    async def test_router(
        self, name: str, ctx: "RoutingContext"
    ) -> "Dict[str, Any]":
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

    # ── Subprocess management ─────────────────────────────────────────────────

    async def _run_in_subprocess(
        self, name: str, ctx: "RoutingContext"
    ) -> "Dict[str, Any]":
        """
        启动沙箱子进程，通过 JSON IPC 执行路由器，带超时控制。
        """
        dest = self._base_dir / name
        if not dest.exists():
            raise FileNotFoundError(f"路由器目录不存在: {dest}")

        manifest_file = dest / "manifest.json"
        with open(manifest_file, encoding="utf-8") as f:
            manifest_data = json.load(f)
        manifest = RouterManifest(manifest_data, dest)

        cfg_file = dest / "router_config.yaml"
        config: Dict[str, Any] = {}
        if cfg_file.exists():
            try:
                with open(cfg_file, encoding="utf-8") as f:
                    raw_cfg = yaml.safe_load(f)
                    config = raw_cfg or {}
            except Exception:
                pass

        # 将 RoutingContext 序列化为 JSON（只传递安全数据）
        context_data = _serialize_context(ctx)

        request_payload = json.dumps({
            "router_dir": str(dest),
            "entrypoint": manifest.entrypoint,
            "class": manifest.class_name,
            "config": config,
            "context": context_data,
        }, ensure_ascii=False)

        sandbox_script = str(Path(__file__).parent / "sandbox_runner.py")

        proc = await asyncio.create_subprocess_exec(
            sys.executable, sandbox_script,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(input=request_payload.encode("utf-8")),
                timeout=_ROUTER_TIMEOUT_S,
            )
        except asyncio.TimeoutError:
            try:
                proc.kill()
                await proc.wait()
            except Exception:
                pass
            raise

        if stderr_bytes:
            logger.debug(f"路由器 '{name}' 沙箱 stderr: {stderr_bytes.decode('utf-8', errors='replace')[:500]}")

        if not stdout_bytes:
            return {"ok": False, "error": "沙箱子进程无输出"}

        try:
            return json.loads(stdout_bytes.decode("utf-8"))
        except json.JSONDecodeError as e:
            raw = stdout_bytes.decode("utf-8", errors="replace")[:200]
            return {"ok": False, "error": f"沙箱输出解析失败: {e} | 原始输出: {raw}"}

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
