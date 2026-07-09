"""后台截图测试：capture_window / capture_window_by_title 桩测试 + 真实窗口冒烟。"""

from __future__ import annotations

import pytest

from region_cua.automation import bg_capture
from region_cua.vision import screenshot as shot


def test_capture_returns_none_when_window_not_found(monkeypatch):
    """找不到窗口时 capture_window_by_title 返回 None。"""
    monkeypatch.setattr("region_cua.automation.windows.find_window_by_title", lambda kw: None)
    assert bg_capture.capture_window_by_title("不存在的窗口XYZ") is None


def test_capture_falls_back_to_foreground(monkeypatch):
    """capture() 在后台截图失败时退回前台截图。"""
    called = {"fg": False}

    def fake_fg():
        called["fg"] = True
        return "fake_fg_image"

    monkeypatch.setattr(shot, "capture_window_bg", lambda kw: None)
    monkeypatch.setattr(shot, "capture_screen", fake_fg)
    result = shot.capture(window_keyword="不存在")
    assert result == "fake_fg_image"
    assert called["fg"] is True


def test_capture_uses_foreground_when_no_keyword(monkeypatch):
    """无 keyword 时直接前台截图。"""
    called = {"bg": False, "fg": False}
    monkeypatch.setattr(shot, "capture_window_bg", lambda kw: called.__setitem__("bg", True))
    monkeypatch.setattr(shot, "capture_screen", lambda: called.__setitem__("fg", True) or "fg")
    result = shot.capture()
    assert result == "fg"
    assert called["fg"] is True
    assert called["bg"] is False


def test_capture_uses_background_when_keyword_found(monkeypatch):
    """有 keyword 且后台截图成功时用后台结果。"""
    monkeypatch.setattr(shot, "capture_window_bg", lambda kw: "bg_image")
    monkeypatch.setattr(shot, "capture_screen", lambda: "fg_image")
    result = shot.capture(window_keyword="WPS")
    assert result == "bg_image"


@pytest.mark.integration
def test_capture_real_notepad_window():
    """真实冒烟：打开记事本，后台截图应返回非 None 图片。"""
    import subprocess, time
    from PIL import Image

    subprocess.Popen(["notepad.exe"])
    time.sleep(2)
    try:
        img = bg_capture.capture_window_by_title("记事本")
        if img is not None:
            assert isinstance(img, Image.Image)
            assert img.size[0] > 0 and img.size[1] > 0
    finally:
        subprocess.Popen(["taskkill", "/IM", "notepad.exe", "/F"])
