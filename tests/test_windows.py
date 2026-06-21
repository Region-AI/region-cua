"""窗口管理测试：find_window_by_title / activate_window 的桩测试。

真实窗口操作无法在 CI 中测试，这里只验证函数签名和路径逻辑。
"""

from __future__ import annotations

from unittest.mock import patch, MagicMock

from region_cua.automation import windows


def test_find_window_no_match(monkeypatch):
    """EnumWindows 返回空时应返回 None。"""
    fake_user32 = MagicMock()
    fake_user32.GetWindowTextLengthW.return_value = 0
    fake_user32.EnumWindows.side_effect = lambda cb, lp: None
    monkeypatch.setattr(windows, "_user32", lambda: fake_user32)
    assert windows.find_window_by_title("不存在") is None


def test_activate_window_returns_false_when_not_found(monkeypatch):
    monkeypatch.setattr(windows, "find_window_by_title", lambda kw: None)
    assert windows.activate_window("不存在") is False


def test_activate_after_open_uses_keyword_extraction(monkeypatch):
    """activate_after_open 应从 'WPS Office' 提取 'WPS' 作为搜索关键词。"""
    called = {"keyword": None}
    monkeypatch.setattr(windows.time, "sleep", lambda *a: None)

    def fake_activate(keyword):
        called["keyword"] = keyword
        return True

    monkeypatch.setattr(windows, "activate_window", fake_activate)
    windows.activate_after_open("WPS Office", wait=0.1)
    assert called["keyword"] == "WPS"


def test_activate_after_open_strips_exe(monkeypatch):
    called = {"keyword": None}
    monkeypatch.setattr(windows.time, "sleep", lambda *a: None)
    monkeypatch.setattr(windows, "activate_window", lambda kw: called.__setitem__("keyword", kw) or True)
    windows.activate_after_open("notepad.exe", wait=0.1)
    assert called["keyword"] == "notepad"
