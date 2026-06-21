"""屏幕截图：统一通过 pyautogui（Pillow）采集，便于测试 monkeypatch。"""

from __future__ import annotations

from pathlib import Path


def capture_screen():
    """返回当前屏幕的 PIL.Image.Image。"""
    import pyautogui  # 延迟导入：无桌面环境下导入模块本身不报错
    return pyautogui.screenshot()


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
