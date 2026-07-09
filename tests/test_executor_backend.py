"""executor backend 切换测试：foreground vs background 行为差异。"""

from __future__ import annotations

import pytest

from region_cua.agent.executor import TaskExecutor
from region_cua.agent.models import Step, TaskPlan
from region_cua.agent.monitor import Monitor


def _executor(client, tmp_path, monitor=None, verify=True, **kw):
    return TaskExecutor(
        client, "vision-model", tmp_path,
        monitor or Monitor(max_failures=99),
        record_video=False, verify=verify, **kw
    )


def test_foreground_backend_activates_window(stub_desktop, tmp_path, fake_client_cls, monkeypatch):
    """前台模式 open_app 应调用 activate_after_open。"""
    activate_called = {"v": False}
    import region_cua.automation.windows as wins
    monkeypatch.setattr(wins, "activate_after_open", lambda name, wait=2.0: activate_called.__setitem__("v", True))

    plan = TaskPlan(task="t", steps=[Step(order=1, action="open_app", target="WPS")])
    _executor(fake_client_cls(), tmp_path, backend="foreground").execute(plan)
    assert activate_called["v"] is True


def test_background_backend_skips_activation(stub_desktop, tmp_path, fake_client_cls, monkeypatch):
    """后台模式 open_app 不应调用 activate_after_open，而是设置 window_keyword。"""
    activate_called = {"v": False}
    import region_cua.automation.windows as wins
    monkeypatch.setattr(wins, "activate_after_open", lambda name, wait=2.0: activate_called.__setitem__("v", True))

    plan = TaskPlan(task="t", steps=[Step(order=1, action="open_app", target="WPS Office")])
    ex = _executor(fake_client_cls(), tmp_path, backend="background")
    ex.execute(plan)
    assert activate_called["v"] is False  # 后台不激活
    assert ex.window_keyword == "WPS"  # 关键词已设置


def test_background_capture_uses_keyword(stub_desktop, tmp_path, fake_client_cls, monkeypatch):
    """后台模式截图应传入 window_keyword。"""
    capture_calls = {"kw": None}
    import region_cua.vision.screenshot as shot_mod
    original_capture = shot_mod.capture
    def spy_capture(window_keyword=None):
        capture_calls["kw"] = window_keyword
        return "fake_img"
    monkeypatch.setattr(shot_mod, "capture", spy_capture)
    monkeypatch.setattr(shot_mod, "save_screenshot", lambda img, path: str(path))

    plan = TaskPlan(task="t", steps=[Step(order=1, action="open_app", target="WPS", requires_vision=False)])
    ex = _executor(fake_client_cls(), tmp_path, backend="background")
    ex.execute(plan)
    # 后台模式下截图传入了 window_keyword
    assert capture_calls["kw"] is not None


def test_foreground_capture_no_keyword(stub_desktop, tmp_path, fake_client_cls, monkeypatch):
    """前台模式截图不传 window_keyword。"""
    capture_calls = {"kw": "INITIAL"}
    import region_cua.vision.screenshot as shot_mod
    def spy_capture(window_keyword=None):
        capture_calls["kw"] = window_keyword
        return "fake_img"
    monkeypatch.setattr(shot_mod, "capture", spy_capture)
    monkeypatch.setattr(shot_mod, "save_screenshot", lambda img, path: str(path))

    plan = TaskPlan(task="t", steps=[Step(order=1, action="open_app", target="WPS", requires_vision=False)])
    ex = _executor(fake_client_cls(), tmp_path, backend="foreground")
    ex.execute(plan)
    assert capture_calls["kw"] is None


def test_default_backend_is_foreground(tmp_path, fake_client_cls):
    """默认 backend 是 foreground。"""
    ex = _executor(fake_client_cls(), tmp_path)
    assert ex.backend == "foreground"
    assert ex.window_keyword is None
