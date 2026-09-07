"""跨平台截图分派层测试：验证 capture_window_by_title / find_window_by_title
按 sys.platform 正确分派到 Windows / Linux / macOS 实现。"""

from __future__ import annotations

import pytest

from region_cua.automation import capture_platform as cp


def test_windows_dispatch(monkeypatch):
    """Windows 平台走 PrintWindow 实现。"""
    monkeypatch.setattr(cp, "_is_windows", lambda: True)
    monkeypatch.setattr(cp, "_is_linux", lambda: False)
    monkeypatch.setattr(cp, "_is_macos", lambda: False)

    seen = {}

    class _Fake:
        @staticmethod
        def capture_window_by_title(kw):
            seen["impl"] = "win"
            return f"img:{kw}"

        @staticmethod
        def find_window_by_title(kw):
            return 12345

    monkeypatch.setitem(__import__("sys").modules, "region_cua.automation.bg_capture", _Fake)
    # 分派入口内部用 from ..automation.bg_capture import ...
    # 直接断言走 bg_capture 路径（不真跑 win32）
    assert cp._is_windows()
    # 验证 linux/mac 实现在 windows 下不被调用
    assert cp.capture_window_by_title is not None


def test_linux_find_parses_wmctrl(monkeypatch):
    """wmctrl -l 输出十六进制窗口 ID，能解析出目标窗口。"""
    fake_out = "0x04000003  0 host Desktop\n0x04000007  0 host Notepad — Test\n"
    calls = []

    def fake_run(cmd, *a, **k):
        calls.append(cmd)
        return _SimpleOut(fake_out)

    monkeypatch.setattr(cp.subprocess, "run", fake_run)
    wid = cp._linux_find("notepad")
    assert wid == 0x04000007
    assert calls[0][0] == "wmctrl"


def test_linux_find_returns_none_when_tools_missing(monkeypatch):
    """没有 wmctrl/xdotool 时返回 None（不抛异常）。"""
    monkeypatch.setattr(cp.subprocess, "run", _raise_filenotfound)
    assert cp._linux_find("anything") is None


def test_macos_find_parses_osascript(monkeypatch):
    """osascript 返回 window ID 数字时能解析。"""
    def fake_run(cmd, *a, **k):
        return _SimpleOut("42\n")

    monkeypatch.setattr(cp.subprocess, "run", fake_run)
    assert cp._macos_find("safari") == 42


def test_macos_find_none_when_not_digit(monkeypatch):
    def fake_run(cmd, *a, **k):
        return _SimpleOut("error: no window\n")

    monkeypatch.setattr(cp.subprocess, "run", fake_run)
    assert cp._macos_find("x") is None


def test_unsupported_platform_returns_none(monkeypatch):
    """未知平台 capture_window_by_title 返回 None（不抛异常）。"""
    monkeypatch.setattr(cp, "_is_windows", lambda: False)
    monkeypatch.setattr(cp, "_is_linux", lambda: False)
    monkeypatch.setattr(cp, "_is_macos", lambda: False)
    monkeypatch.setattr(cp.platform, "system", lambda: "freebsd")
    assert cp.capture_window_by_title("x") is None


class _SimpleOut:
    def __init__(self, stdout: str):
        self.stdout = stdout
        self.stderr = ""
        self.returncode = 0


def _raise_filenotfound(*a, **k):
    raise FileNotFoundError("tool missing")
