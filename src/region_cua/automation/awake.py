"""跨平台「保持唤醒」：任务期间阻止系统/显示器进入锁屏或睡眠。

锁屏后所有桌面 agent 都拿不到屏幕内容（Windows secure desktop / Linux 锁屏
覆盖层 / Wayland portal 拒绝）—— 业内标准做法是阻止锁屏，而不是去绕过它。

用法（with 块自动恢复，异常安全）：

    with keep_awake():
        ...  # 任务期间不会自动锁屏

平台支持：
- Windows: SetThreadExecutionState（系统级，与 PowerToys Awake / 咖啡因同原理）
- Linux:   systemd-inhibit 子进程（包住整个任务），无 systemd 时降级为 no-op
- macOS:   caffeinate 子进程（包住整个任务）
- 其他:    no-op，不影响主流程
"""

from __future__ import annotations

import contextlib
import platform
import subprocess
from typing import Iterator


# ----------------------------------------------------------------- Windows
def _windows_keep_awake() -> "_AwakeHandle":
    """通过 SetThreadExecutionState 通知系统当前线程正在工作。"""
    import ctypes

    ES_CONTINUOUS = 0x80000000
    ES_DISPLAY_REQUIRED = 0x00000002
    ES_SYSTEM_REQUIRED = 0x00000001
    flags = ES_CONTINUOUS | ES_DISPLAY_REQUIRED | ES_SYSTEM_REQUIRED
    prev = ctypes.windll.kernel32.SetThreadExecutionState(flags)  # type: ignore[attr-defined]

    def _restore() -> None:
        try:
            ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)  # type: ignore[attr-defined]
        except Exception:
            pass

    return _AwakeHandle(_restore, "windows:SetThreadExecutionState", prev_state=prev)


# ------------------------------------------------------------------- Linux
def _linux_keep_awake() -> "_AwakeHandle":
    """systemd-inhibit 占住一个 sleep+idle inhibitor，直到子进程被 kill。"""
    try:
        proc = subprocess.Popen(
            [
                "systemd-inhibit",
                "--what=idle:sleep:handle-lid-switch",
                "--why=region-cua-task",
                "--mode=block",
                "sleep", "infinity",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        return _AwakeHandle(lambda: None, "linux:no-systemd-inhibit")

    def _restore() -> None:
        try:
            proc.terminate()
            proc.wait(timeout=2)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    return _AwakeHandle(_restore, "linux:systemd-inhibit")


# ------------------------------------------------------------------- macOS
def _macos_keep_awake() -> "_AwakeHandle":
    try:
        proc = subprocess.Popen(
            ["caffeinate", "-disu"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        return _AwakeHandle(lambda: None, "macos:no-caffeinate")

    def _restore() -> None:
        try:
            proc.terminate()
            proc.wait(timeout=2)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    return _AwakeHandle(_restore, "macos:caffeinate")


# ------------------------------------------------------------------- handle
class _AwakeHandle:
    """保持唤醒的句柄。close() 幂等。"""

    def __init__(self, restore_fn, backend: str, prev_state: int = 0):
        self._restore = restore_fn
        self.backend = backend
        self.prev_state = prev_state
        self._closed = False

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._restore()
        except Exception:
            pass


# ------------------------------------------------------------- public API
def acquire_keep_awake() -> _AwakeHandle:
    """获取一个保持唤醒句柄，调用方需在结束时调 .close()。"""
    system = platform.system()
    if system == "Windows":
        return _windows_keep_awake()
    if system == "Linux":
        return _linux_keep_awake()
    if system == "Darwin":
        return _macos_keep_awake()
    return _AwakeHandle(lambda: None, f"unsupported:{system}")


@contextlib.contextmanager
def keep_awake(enabled: bool = True) -> "Iterator[_AwakeHandle | None]":
    """with 块：任务期间阻止锁屏/睡眠，块结束自动恢复。

    enabled=False 时退化为空 with，便于通过 CLI 开关一键关闭。
    """
    if not enabled:
        yield None
        return
    handle = acquire_keep_awake()
    try:
        yield handle
    finally:
        handle.close()
