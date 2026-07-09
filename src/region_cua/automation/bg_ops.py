"""后台操作后端：用 Windows UI Automation 实现不抢焦点的点击和输入。

对比前台 pyautogui：
- 前台：鼠标移动到坐标 → 物理点击 → 抢占光标，被遮挡/锁屏失效
- 后台 UIA：通过控件树找到目标元素 → 直接 Invoke/SetValue → 不移动鼠标

策略：
1. 优先用 UIA 控件树按名称/坐标找元素，调 Invoke/Click
2. 找不到控件时，用 Win32 PostMessage 发鼠标消息到窗口（仍不需前台）
3. 输入文本用 UIA ValuePattern 或 SendInput 到特定窗口
"""

from __future__ import annotations

import ctypes
import time
from typing import Optional


def _uia():
    """延迟导入 uiautomation，避免无桌面环境导入失败。"""
    import uiautomation as ua
    return ua


def click_element_by_name(name: str, root=None, depth: int = 10) -> bool:
    """在控件树中按名称查找元素并点击（Invoke），不移动鼠标。

    Args:
        name: 控件名称（按钮文字、菜单项文字等）
        root: 搜索根节点（默认桌面根）
        depth: 搜索深度
    Returns:
        是否找到并点击成功
    """
    ua = _uia()
    if root is None:
        root = ua.GetRootControl()
    # 按名称查找，NameMatchMode.Contains
    elem = root.FindFirst(
        ua.CreateTreeCondition(
            ua.GetProperty(ua.NameProperty),
            name,
            PropertyConditionFlags=ua.PropertyConditionFlags.MatchContains,
        ),
        depth=depth,
    )
    if elem is None:
        return False
    try:
        # 优先 InvokePattern（按钮、菜单项）
        if elem.GetInvokePattern():
            elem.GetInvokePattern().Invoke()
            return True
    except Exception:
        pass
    try:
        # 退路：LegacyIAccessiblePattern
        if elem.GetLegacyIAccessiblePattern():
            elem.GetLegacyIAccessiblePattern().DoDefaultAction()
            return True
    except Exception:
        pass
    # 最后退路：获取坐标并用 Win32 PostMessage 点击
    rect = elem.BoundingRectangle
    if rect:
        cx = (rect.left + rect.right) // 2
        cy = (rect.top + rect.bottom) // 2
        return post_click(cx, cy)
    return False


def click_at_coords_bg(hwnd: int, x: int, y: int, button: str = "left", clicks: int = 1) -> bool:
    """对特定窗口发送鼠标点击消息（后台，不移动实际鼠标）。

    坐标是相对于窗口客户区的。
    """
    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    lparam = (y << 16) | (x & 0xFFFF)

    msgs = []
    if button == "right":
        msgs = [(0x0204, 0), (0x0205, lparam)]  # WM_RBUTTONDOWN/UP
    elif button == "middle":
        msgs = [(0x0207, 0), (0x0208, lparam)]  # WM_MBUTTONDOWN/UP
    else:
        msgs = [(0x0201, 0), (0x0202, lparam)]  # WM_LBUTTONDOWN/UP

    for _ in range(clicks):
        for msg, lp in msgs:
            user32.PostMessageW(hwnd, msg, 0, lp)
            time.sleep(0.05)
    return True


def post_click(screen_x: int, screen_y: int, button: str = "left") -> bool:
    """通过窗口句柄发送后台点击（需要先找到该坐标对应的窗口）。"""
    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    hwnd = user32.WindowFromPoint(wintypes_point(screen_x, screen_y))
    if not hwnd:
        return False
    # 转换为窗口客户区坐标
    pt = wintypes.POINT(screen_x, screen_y)
    user32.ScreenToClient(hwnd, ctypes.byref(pt))
    return click_at_coords_bg(hwnd, pt.x, pt.y, button=button)


def type_text_bg(hwnd: int, text: str) -> bool:
    """对特定窗口后台输入文本（通过发送 WM_CHAR 消息）。

    适合简单 ASCII 文本，中文等复杂输入建议用前台剪贴板方式。
    """
    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    # 找到窗口内当前焦点控件
    thread_id = user32.GetWindowThreadProcessId(hwnd, None)
    user32.AttachThreadInput(user32.GetCurrentThreadId(), thread_id, True)
    focus = user32.GetFocus()
    user32.AttachThreadInput(user32.GetCurrentThreadId(), thread_id, False)

    target = focus if focus else hwnd
    for ch in text:
        user32.PostMessageW(target, 0x0102, ord(ch), 0)  # WM_CHAR
        time.sleep(0.01)
    return True


def set_value_by_uia(name: str, value: str, root=None) -> bool:
    """用 UIA ValuePattern 直接设置文本框内容（后台，不需要焦点）。"""
    ua = _uia()
    if root is None:
        root = ua.GetRootControl()
    elem = root.FindFirst(
        ua.CreateTreeCondition(ua.GetProperty(ua.NameProperty), name),
        depth=10,
    )
    if elem is None:
        return False
    try:
        vp = elem.GetValuePattern()
        if vp:
            vp.SetValue(value)
            return True
    except Exception:
        pass
    return False


class wintypes_point(ctypes.Structure):
    """POINT 结构体，用于 WindowFromPoint。"""
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


# 补充 wintypes.POINT 别名（某些版本 ctypes.wintypes 没有 POINT）
if not hasattr(ctypes.wintypes, "POINT"):
    ctypes.wintypes.POINT = wintypes_point
