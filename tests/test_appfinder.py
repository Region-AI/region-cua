"""应用查找测试：路径判定与开始菜单快捷方式搜索。"""

from __future__ import annotations

from region_cua.automation import appfinder


def test_looks_like_path_or_url():
    assert appfinder._looks_like_path_or_url("https://www.baidu.com")
    assert appfinder._looks_like_path_or_url("http://x.com")
    assert appfinder._looks_like_path_or_url("notepad.exe")
    assert appfinder._looks_like_path_or_url(r"C:\Windows\notepad.exe")
    assert not appfinder._looks_like_path_or_url("calc")
    assert not appfinder._looks_like_path_or_url("WPS 文字")


def test_find_shortcuts(monkeypatch, tmp_path):
    start = tmp_path / "StartMenu"
    start.mkdir()
    (start / "计算器.lnk").touch()
    (start / "WPS文字.lnk").touch()
    (start / "WPS表格.lnk").touch()
    monkeypatch.setattr(appfinder, "_START_MENU_DIRS", [start])

    found = appfinder.find_shortcuts("计算器")
    assert len(found) == 1
    assert "计算器.lnk" in found[0]

    found = appfinder.find_shortcuts("WPS")
    assert len(found) == 2

    assert appfinder.find_shortcuts("不存在的应用XYZ") == []


def test_open_app_falls_back_to_shell(monkeypatch, tmp_path):
    """无快捷方式时回退到 cmd start，不抛异常。"""
    monkeypatch.setattr(appfinder, "_START_MENU_DIRS", [tmp_path / "empty"])
    monkeypatch.setattr(appfinder.shutil, "which", lambda name: None)
    called = {}
    monkeypatch.setattr(appfinder.subprocess, "Popen", lambda *a, **k: called.setdefault("ok", True))
    method = appfinder.open_app("some-unknown-app")
    assert called.get("ok") is True
    assert method.startswith("shell:")
