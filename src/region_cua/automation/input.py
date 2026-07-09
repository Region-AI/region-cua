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
    """输入文本。

    策略：
    - 含非 ASCII（如中文）→ 剪贴板粘贴
    - 纯 ASCII 但含 @ . , 等易被 IME 拦截的字符 → 剪贴板粘贴
    - 纯字母数字 → 切英文输入法 + write() 逐字符
    """
    if not text:
        return
    try:
        text.encode("ascii")
    except UnicodeEncodeError:
        _paste(text)
        return
    # 纯 ASCII：检查是否含 IME 易拦截字符
    ime_sensitive = set("@.,;:!?/\\()[]{}\"'`~")
    if any(c in ime_sensitive for c in text):
        _paste(text)
        return
    # 纯字母数字：切英文输入法 + 逐字符输入
    _ensure_english_ime()
    _pa().write(text, interval=interval)


# 输入法状态管理
_ime_restored_to = None  # 记录切换前的输入法，用于恢复


def _ensure_english_ime() -> None:
    """确保当前是英文输入模式。

    Windows 中文输入法（微软拼音/搜狗等）会拦截按键。
    用 Shift 键切换中英文模式（大多数中文 IME 的默认快捷键）。
    如果检测到当前是中文模式，按 Shift 切到英文，输入完后再切回。
    """
    global _ime_restored_to
    try:
        import ctypes
        user32 = ctypes.windll.user32
        # GetKeyboardLayout 获取当前线程的键盘布局
        # 0x0404 = 中文(繁体), 0x0804 = 中文(简体)
        layout = user32.GetKeyboardLayout(0)
        lang_id = layout & 0xFFFF
        if lang_id in (0x0404, 0x0804):
            # 中文输入法 → 按 Shift 切换到英文模式
            # 先记录状态（无法精确获取中/英模式，假设切换后是英文）
            _ime_restored_to = "zh"
            _pa().keyDown("shift")
            _pa().keyUp("shift")
            time.sleep(0.2)
    except Exception:
        pass  # 非 Windows 或无 IME，忽略


def _restore_ime() -> None:
    """输入完成后恢复输入法状态。"""
    global _ime_restored_to
    if _ime_restored_to == "zh":
        try:
            _pa().keyDown("shift")
            _pa().keyUp("shift")
            time.sleep(0.1)
        except Exception:
            pass
    _ime_restored_to = None


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
