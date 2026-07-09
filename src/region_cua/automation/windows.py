"""窗口管理：把指定窗口拉到前台。

pygetwindow.activate() 在 Windows 上有已知 bug（Error code 0 但抛异常），
这里用 ctypes 直接调 Windows API，通过 Alt 键释放前台锁，可靠地激活窗口。
"""

from __future__ import annotations

import ctypes
import time
from typing import Optional


def _user32():
    return ctypes.windll.user32  # type: ignore[attr-defined]


def find_window_by_title(keyword: str) -> Optional[int]:
    """遍历所有顶层窗口，返回标题包含 keyword 的第一个窗口句柄。"""
    user32 = _user32()
    results: list[int] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)
    def _enum_proc(hwnd: int, _lparam: int) -> bool:
        length = user32.GetWindowTextLengthW(hwnd)
        if length > 0:
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            if keyword.lower() in buf.value.lower():
                results.append(hwnd)
        return True

    # 保持回调引用，防止被 GC（ctypes 回调对象生命周期必须覆盖 EnumWindows 调用）
    user32.EnumWindows(_enum_proc, 0)
    return results[0] if results else None


def activate_window(keyword: str) -> bool:
    """把标题包含 keyword 的窗口拉到前台，返回是否成功。"""
    hwnd = find_window_by_title(keyword)
    if not hwnd:
        return False
    user32 = _user32()
    # SW_RESTORE = 9：如果窗口最小化则恢复
    user32.ShowWindow(hwnd, 9)
    # 发 Alt 键释放 Windows 前台窗口锁，否则 SetForegroundWindow 会被拒绝
    user32.keybd_event(0x12, 0, 0, 0)        # Alt down
    user32.keybd_event(0x12, 0, 0x0002, 0)   # Alt up
    return bool(user32.SetForegroundWindow(hwnd))


def activate_after_open(app_name: str, wait: float = 2.0) -> None:
    """启动应用后尝试把它的窗口拉到前台。

    从应用名提取关键词（去掉 .exe、取第一个有意义的词），
    循环尝试几次匹配窗口（应用启动需要时间）。
    """
    keyword = app_name.replace(".exe", "").replace(".lnk", "").strip()
    # 取较短的关键词更容易匹配窗口标题
    parts = keyword.split()
    if len(parts) > 1:
        keyword = parts[0]  # "WPS Office" → "WPS"

    for _ in range(max(1, int(wait * 2))):
        if activate_window(keyword):
            return
        time.sleep(0.5)
