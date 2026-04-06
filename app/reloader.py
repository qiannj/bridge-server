"""
Bridge Server Configuration Hot Reloader

支持三种重载方式：
1. 文件监听自动重载
2. SIGHUP 信号触发
3. API 端点触发
"""

import os
import signal
import logging
import threading
import time
from pathlib import Path
from typing import Optional, Dict, Any, Callable, List
from dataclasses import dataclass
from datetime import datetime
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileModifiedEvent

logger = logging.getLogger(__name__)


@dataclass
class ReloadResult:
    """重载结果"""

    success: bool
    timestamp: datetime
    message: str
    changed_sections: List[str]
    error: Optional[str] = None


class ConfigWatcher(FileSystemEventHandler):
    """配置文件监听器"""

    def __init__(self, callback: Callable[[Path], None], debounce_seconds: float = 1.0):
        """
        初始化监听器

        Args:
            callback: 文件变化回调函数
            debounce_seconds: 防抖时间（秒）
        """
        self.callback = callback
        self.debounce_seconds = debounce_seconds
        self._timers: Dict[str, threading.Timer] = {}
        self._lock = threading.Lock()

    def on_modified(self, event):
        """文件修改事件"""
        if not isinstance(event, FileModifiedEvent):
            return

        file_path = Path(event.src_path)

        # 只监听 YAML 配置文件
        if file_path.suffix not in [".yaml", ".yml"]:
            return

        logger.info(f"检测到配置文件修改：{file_path}")

        # 防抖处理
        with self._lock:
            if file_path.name in self._timers:
                self._timers[file_path.name].cancel()

            timer = threading.Timer(
                self.debounce_seconds, self.callback, args=[file_path]
            )
            timer.start()
            self._timers[file_path.name] = timer


class HotReloader:
    """配置热重载器"""

    # 支持热重载的配置项
    HOT_RELOADABLE_SECTIONS = {
        "server.auth_tokens",
        "server.rate_limiting",
        "providers",
        "budget",
        "logging",
        "features",
    }

    # 不支持热重载的配置项（需要重启）
    REQUIRES_RESTART_SECTIONS = {"server.host", "server.port", "server.ssl", "database"}

    def __init__(
        self,
        config_path: str,
        reload_callback: Optional[Callable[[Dict[str, Any]], bool]] = None,
    ):
        """
        初始化热重载器

        Args:
            config_path: 配置文件路径
            reload_callback: 重载回调函数，接收新配置字典，返回是否成功
        """
        self.config_path = Path(config_path)
        self.reload_callback = reload_callback

        self._observer: Optional[Observer] = None
        self._watcher: Optional[ConfigWatcher] = None
        self._last_config: Optional[Dict[str, Any]] = None
        self._last_reload: Optional[datetime] = None
        self._reload_history: List[ReloadResult] = []
        self._lock = threading.Lock()

        # 注册 SIGHUP 信号处理
        self._register_signal_handler()

    def _register_signal_handler(self):
        """注册 SIGHUP 信号处理"""

        def sighup_handler(signum, frame):
            logger.info("收到 SIGHUP 信号，触发配置重载")
            self.reload()

        # 仅在 Unix 系统上注册
        if hasattr(signal, "SIGHUP"):
            signal.signal(signal.SIGHUP, sighup_handler)
            logger.info("已注册 SIGHUP 信号处理")

    def start_watching(self):
        """启动文件监听"""
        if self._observer is not None:
            logger.warning("文件监听已在运行")
            return

        if not self.config_path.exists():
            logger.error(f"配置文件不存在：{self.config_path}")
            return

        self._watcher = ConfigWatcher(callback=self._on_file_changed)
        self._observer = Observer()

        # 监听配置文件所在目录
        watch_dir = self.config_path.parent
        self._observer.schedule(self._watcher, str(watch_dir), recursive=False)

        self._observer.start()
        logger.info(f"开始监听配置文件：{self.config_path}")

    def stop_watching(self):
        """停止文件监听"""
        if self._observer is None:
            return

        self._observer.stop()
        self._observer.join()
        self._observer = None
        logger.info("已停止文件监听")

    def _on_file_changed(self, file_path: Path):
        """文件变化回调"""
        if file_path == self.config_path:
            logger.info("配置文件变化，自动触发重载")
            self.reload()

    def reload(self, force: bool = False) -> ReloadResult:
        """
        重载配置

        Args:
            force: 是否强制重载（跳过检查）

        Returns:
            ReloadResult: 重载结果
        """
        with self._lock:
            try:
                # 检查配置文件
                if not self.config_path.exists():
                    return ReloadResult(
                        success=False,
                        timestamp=datetime.now(),
                        message="配置文件不存在",
                        changed_sections=[],
                        error=f"File not found: {self.config_path}",
                    )

                # 加载新配置
                import yaml

                with open(self.config_path, "r", encoding="utf-8") as f:
                    new_config = yaml.safe_load(f)

                # 检查是否有变化
                if not force and new_config == self._last_config:
                    return ReloadResult(
                        success=True,
                        timestamp=datetime.now(),
                        message="配置无变化",
                        changed_sections=[],
                    )

                # 检查不支持热重载的配置项
                requires_restart = self._check_requires_restart(new_config)
                if requires_restart:
                    return ReloadResult(
                        success=False,
                        timestamp=datetime.now(),
                        message="配置修改需要重启服务",
                        changed_sections=requires_restart,
                        error=f"Sections require restart: {', '.join(requires_restart)}",
                    )

                # 执行重载
                if self.reload_callback:
                    success = self.reload_callback(new_config)
                else:
                    success = True

                if success:
                    self._last_config = new_config
                    self._last_reload = datetime.now()

                    # 记录重载历史
                    result = ReloadResult(
                        success=True,
                        timestamp=datetime.now(),
                        message="配置重载成功",
                        changed_sections=self._detect_changes(new_config),
                    )
                    self._reload_history.append(result)

                    # 保留最近 100 条记录
                    if len(self._reload_history) > 100:
                        self._reload_history = self._reload_history[-100:]

                    logger.info(f"配置重载成功：{result.changed_sections}")
                    return result
                else:
                    return ReloadResult(
                        success=False,
                        timestamp=datetime.now(),
                        message="重载回调失败",
                        changed_sections=[],
                    )

            except yaml.YAMLError as e:
                error_msg = f"YAML 解析错误：{e}"
                logger.error(error_msg)
                return ReloadResult(
                    success=False,
                    timestamp=datetime.now(),
                    message="配置文件格式错误",
                    changed_sections=[],
                    error=error_msg,
                )
            except Exception as e:
                error_msg = f"重载失败：{e}"
                logger.error(error_msg)
                return ReloadResult(
                    success=False,
                    timestamp=datetime.now(),
                    message="重载失败",
                    changed_sections=[],
                    error=error_msg,
                )

    def _check_requires_restart(self, new_config: Dict[str, Any]) -> List[str]:
        """检查是否有需要重启的配置项"""
        requires_restart = []

        if not self._last_config:
            return requires_restart

        for section in self.REQUIRES_RESTART_SECTIONS:
            keys = section.split(".")
            old_val = self._get_nested_value(self._last_config, keys)
            new_val = self._get_nested_value(new_config, keys)

            if old_val != new_val:
                requires_restart.append(section)

        return requires_restart

    def _detect_changes(self, new_config: Dict[str, Any]) -> List[str]:
        """检测变化的配置项"""
        if not self._last_config:
            return ["all"]

        changed = []
        for section in self.HOT_RELOADABLE_SECTIONS:
            keys = section.split(".")
            old_val = self._get_nested_value(self._last_config, keys)
            new_val = self._get_nested_value(new_config, keys)

            if old_val != new_val:
                changed.append(section)

        return changed

    def _get_nested_value(self, d: Dict, keys: List[str], default=None):
        """获取嵌套字典的值"""
        for key in keys:
            if isinstance(d, dict):
                d = d.get(key, default)
            else:
                return default
        return d

    def get_status(self) -> Dict[str, Any]:
        """获取重载器状态"""
        return {
            "watching": self._observer is not None,
            "config_path": str(self.config_path),
            "last_reload": self._last_reload.isoformat() if self._last_reload else None,
            "reload_count": len(self._reload_history),
            "hot_reloadable_sections": list(self.HOT_RELOADABLE_SECTIONS),
            "requires_restart_sections": list(self.REQUIRES_RESTART_SECTIONS),
        }

    def get_reload_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """获取重载历史"""
        history = self._reload_history[-limit:]
        return [
            {
                "success": r.success,
                "timestamp": r.timestamp.isoformat(),
                "message": r.message,
                "changed_sections": r.changed_sections,
                "error": r.error,
            }
            for r in history
        ]


# 全局单例
_default_reloader: Optional[HotReloader] = None


def get_reloader(config_path: Optional[str] = None) -> Optional[HotReloader]:
    """获取全局重载器实例"""
    global _default_reloader
    return _default_reloader


def init_reloader(
    config_path: str, reload_callback: Optional[Callable] = None
) -> HotReloader:
    """初始化全局重载器"""
    global _default_reloader
    _default_reloader = HotReloader(config_path, reload_callback)
    return _default_reloader


def reload_config() -> ReloadResult:
    """触发配置重载"""
    if _default_reloader is None:
        return ReloadResult(
            success=False,
            timestamp=datetime.now(),
            message="重载器未初始化",
            changed_sections=[],
        )
    return _default_reloader.reload()


if __name__ == "__main__":
    # 测试代码
    logging.basicConfig(level=logging.INFO)

    # 安全修复：使用 tempfile 模块替代硬编码/tmp 路径
    import tempfile
    import atexit

    # 创建临时目录和配置文件
    temp_dir = tempfile.mkdtemp(prefix="bridge-server-test-")
    test_config = Path(temp_dir) / "test-config.yaml"

    # 注册清理函数
    def cleanup():
        import shutil

        try:
            shutil.rmtree(temp_dir)
            logger.info(f"清理临时目录：{temp_dir}")
        except Exception as e:
            logger.error(f"清理临时目录失败：{e}")

    atexit.register(cleanup)

    test_config.write_text("""
server:
  host: 0.0.0.0
  port: 19377
  auth_tokens:
    - token1
""")

    def reload_callback(new_config):
        logger.info(f"新配置：{new_config}")
        return True

    # 初始化重载器
    reloader = init_reloader(str(test_config), reload_callback)
    reloader.start_watching()

    print(f"重载器状态：{reloader.get_status()}")
    print(f"按 Ctrl+C 退出")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        reloader.stop_watching()
        print("\n已退出")
