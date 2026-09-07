"""跨平台后台截图：PrintWindow 的 Linux / macOS 替代。

统一入口 :func:`capture_window_by_title` 按 ``sys.platform`` 分派到平台实现：

- Windows : Win32 ``PrintWindow``（现有 ``bg_capture``，读窗口离屏缓冲，被遮挡也可截）
- Linux   : X11 ``xwd``（截指定窗口 ID，即使被遮挡）；Wayland 无全局离屏抓取，
            降级返回 None（截图方自动退回 pyautogui 全屏）
- macOS   : 系统 ``screencapture -l <windowID>``（CoreGraphics 按窗口 ID 抓取，
            被遮挡窗口也能截；首次需屏幕录制权限）

各平台"按标题找窗口"也在此平台化：
- Windows : Win32 EnumWindows（现有 ``windows.find_window_by_title``）
- Linux   : ``wmctrl -l``（X11 标准工具）或 ``xdotool search --name``
- macOS   : AppleScript ``System Events`` 枚举窗口标题

设计原则：所有平台实现都是"子进程调系统自带工具"（零额外 Python 依赖），
失败一律返回 None，由上层 `vision.screenshot.capture()` 自动退回全屏截图。
"""

from __future__ import annotations

import logging
import platform
import subprocess
import sys
from typing import Optional

_log = logging.getLogger(__name__)


def _is_linux() -> bool:
    return sys.platform.startswith("linux")


def _is_macos() -> bool:
    return sys.platform == "darwin"


def _is_windows() -> bool:
    return sys.platform == "win32"


# --------------------------------------------------------------------------- #
# 统一入口
# --------------------------------------------------------------------------- #
def capture_window_by_title(keyword: str):
    """按窗口标题关键词截取窗口，返回 PIL.Image.Image。找不到/不支持返回 None。"""
    if _is_windows():
        from .bg_capture import capture_window_by_title as _win_impl

        return _win_impl(keyword)
    if _is_linux():
        return _linux_capture(keyword)
    if _is_macos():
        return _macos_capture(keyword)
    _log.warning("capture_window_by_title: 不支持平台 %s", platform.system())
    return None


def find_window_by_title(keyword: str) -> Optional[int]:
    """按标题关键词返回窗口标识（Windows=HWND；Linux=窗口ID；macOS=windowID）。"""
    if _is_windows():
        from .windows import find_window_by_title as _win_find

        return _win_find(keyword)
    if _is_linux():
        return _linux_find(keyword)
    if _is_macos():
        return _macos_find(keyword)
    return None


# --------------------------------------------------------------------------- #
# Linux (X11)
# --------------------------------------------------------------------------- #
def _linux_find(keyword: str) -> Optional[int]:
    """X11 下用 wmctrl 列窗口，返回标题包含 keyword 的第一个窗口 ID。

    - wmctrl 是 X11 标准工具（`sudo apt install wmctrl`），依赖 xprop/xwininfo。
    - Wayland 原生会话下 wmctrl 不可用 → 返回 None（后台截图降级全屏）。
    """
    kw = keyword.lower()
    for tool, args in (
        ("wmctrl", ["-l"]),
        ("xdotool", ["search", "--name", keyword]),
    ):
        try:
            out = subprocess.run(
                [tool, *args], capture_output=True, text=True, timeout=5,
                encoding="utf-8", errors="replace",
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
        if tool == "wmctrl":
            for line in (out.stdout or "").splitlines():
                parts = line.split(None, 3)
                if len(parts) >= 4 and kw in parts[3].lower():
                    try:
                        return int(parts[0], 16)  # wmctrl 窗口 ID 是十六进制
                    except ValueError:
                        continue
        else:
            # xdotool search 输出十进制窗口 ID，每行一个
            for line in (out.stdout or "").splitlines():
                line = line.strip()
                if line.isdigit():
                    return int(line)
    return None


def _linux_capture(keyword: str):
    """X11 下用 xwd 截指定窗口。

    ``xwd -id <wid> -silent`` 输出 XWD 格式，用 Pillow 解析后返回。
    截取被遮挡窗口时 X11 会返回窗口内容（只要窗口已映射）。
    """
    from PIL import Image

    wid = _linux_find(keyword)
    if wid is None:
        _log.info("Linux 后台截图: 未找到窗口 keyword=%r", keyword)
        return None
    try:
        out = subprocess.run(
            ["xwd", "-id", str(wid), "-silent"],
            capture_output=True, timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        _log.warning("Linux 后台截图 xwd 失败: %s", exc)
        return None
    if out.returncode != 0 or not out.stdout:
        _log.warning("Linux 后台截图 xwd 无输出: %s", (out.stderr or b"").decode("utf-8", "replace")[:200])
        return None
    try:
        import io

        return Image.open(io.BytesIO(out.stdout)).convert("RGB")
    except Exception as exc:
        _log.warning("Linux 后台截图解析 XWD 失败: %s", exc)
        return None


# --------------------------------------------------------------------------- #
# macOS
# --------------------------------------------------------------------------- #
def _macos_find(keyword: str) -> Optional[int]:
    """macOS 用 AppleScript 枚举窗口标题，返回 window ID。

    需要辅助功能/自动化权限（首次弹窗授权）。
    """
    script = f"""
    tell application "System Events"
        repeat with p in (every process whose background only is false)
            repeat with w in (every window of p)
                if (name of w) contains "{keyword}" then
                    return id of w
                end if
            end repeat
        end repeat
    end tell
    """
    try:
        out = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=10, encoding="utf-8",
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    txt = (out.stdout or "").strip()
    return int(txt) if txt.isdigit() else None


def _macos_capture(keyword: str):
    """macOS 用系统 screencapture -l <windowID> 截指定窗口。

    被遮挡窗口也能截（CoreGraphics 读窗口内容）；首次需屏幕录制权限。
    """
    from PIL import Image

    wid = _macos_find(keyword)
    if wid is None:
        _log.info("macOS 后台截图: 未找到窗口 keyword=%r", keyword)
        return None
    import tempfile
    import os

    tmp = os.path.join(tempfile.gettempdir(), f"regioncua_win_{wid}.png")
    try:
        out = subprocess.run(
            ["screencapture", "-l", str(wid), "-x", tmp],
            capture_output=True, timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        _log.warning("macOS 后台截图 screencapture 失败: %s", exc)
        return None
    if out.returncode != 0 or not os.path.exists(tmp):
        _log.warning("macOS 后台截图失败（可能缺屏幕录制权限）: %s", (out.stderr or b"").decode("utf-8", "replace")[:200])
        return None
    try:
        img = Image.open(tmp).convert("RGB")
        return img
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
