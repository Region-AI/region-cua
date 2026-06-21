"""鼠标 / 键盘操作封装。

设计要点：
- 所有 pyautogui 调用集中在本模块，executor 只调用这里的函数，便于单测 monkeypatch。
- pyautogui.FAILSAFE 关闭，避免鼠标移到屏幕角落触发紧急停止（也不点击 (0,0)）。
- 中文等非 ASCII 文本走剪贴板 + Ctrl+V，因为 pyautogui.write 只支持当前键盘布局可输入字符。
"""

from __future__ import annotations

import time

_pa_module = None


def _pa():
    """延迟获取 pyautogui 单例，并保证 FAILSAFE 关闭。"""
    global _pa_module
    if _pa_module is None:
        import pyautogui
        pyautogui.FAILSAFE = False  # 关闭角落紧急停止
        _pa_module = pyautogui
    return _pa_module


def move_to(x: int, y: int) -> None:
    _pa().moveTo(x, y, duration=0.25)


def click_at(x: int, y: int, button: str = "left", clicks: int = 1) -> None:
    """点击指定坐标。button: left/right/middle；clicks=2 为双击。"""
    pa = _pa()
    # 避免点击 (0,0) 触发 failsafe（即使已关闭也规避极端坐标）
    x = max(1, x)
    y = max(1, y)
    pa.click(x, y, clicks=clicks, button=button, duration=0.2)


def type_text(text: str, interval: float = 0.02) -> None:
    """输入文本。含非 ASCII（如中文）时改用剪贴板粘贴。"""
    if not text:
        return
    try:
        text.encode("ascii")
        _pa().write(text, interval=interval)
        return
    except UnicodeEncodeError:
        pass
    # 非中文也安全：走剪贴板
    _paste(text)


def _paste(text: str) -> None:
    try:
        import pyperclip

        pyperclip.copy(text)
    except Exception:
        # 退路：Windows clip.exe
        import subprocess

        subprocess.run(["clip"], input=text.encode("utf-16le"), check=False)
    _pa().hotkey("ctrl", "v")
    time.sleep(0.3)


def press_hotkey(*keys: str) -> None:
    """组合键，如 press_hotkey('ctrl','s')。接受 'ctrl+s' 字符串。"""
    flat: list[str] = []
    for k in keys:
        flat.extend(part.strip() for part in str(k).replace(" ", "").split("+") if part)
    if not flat:
        return
    _pa().hotkey(*flat)


def press_key(key: str) -> None:
    _pa().press(key)


def scroll(amount: int) -> None:
    """amount 正数向上滚、负数向下滚。"""
    _pa().scroll(int(amount))


def wait(seconds: float) -> None:
    try:
        time.sleep(float(seconds))
    except (TypeError, ValueError):
        time.sleep(2.0)
