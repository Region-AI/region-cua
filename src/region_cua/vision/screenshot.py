"""屏幕截图：支持前台（pyautogui）和后台（PrintWindow）两种模式。

- 前台模式（默认）：pyautogui.screenshot() 截整个屏幕的可见画面
- 后台模式：PrintWindow API 截特定窗口，即使被遮挡/锁屏也能拿到内容

后台模式需要传入 window_keyword（窗口标题关键词）来定位目标窗口。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional


def capture_screen():
    """前台截图：返回当前屏幕的 PIL.Image.Image。

    带重试机制：screen grab failed 是 Windows 上的间歇性错误，
    通常重试 1-2 次就能成功。
    """
    import pyautogui
    import time as _time
    last_err = None
    for _ in range(3):
        try:
            return pyautogui.screenshot()
        except Exception as e:
            last_err = e
            _time.sleep(0.5)
    raise last_err


def capture_window_bg(keyword: str):
    """后台截图：截取标题包含 keyword 的窗口，即使被遮挡。

    返回 PIL.Image.Image，找不到窗口返回 None。
    """
    try:
        from ..automation.bg_capture import capture_window_by_title
        return capture_window_by_title(keyword)
    except Exception:
        return None


def capture(window_keyword: Optional[str] = None):
    """统一截图入口。

    - window_keyword=None：前台截全屏
    - window_keyword="WPS"：后台截 WPS 窗口（被遮挡也能截到）
    """
    if window_keyword:
        img = capture_window_bg(window_keyword)
        if img is not None:
            return img
        # 后台截图失败，退回前台
    return capture_screen()


def screen_size() -> tuple[int, int]:
    """返回 (宽, 高)。"""
    import pyautogui
    return pyautogui.size()


def save_screenshot(img, path: str | Path) -> str:
    """把 PIL 图片保存为 PNG，返回字符串路径。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(p), format="PNG")
    return str(p)
