"""Monitor 单元测试：连续失败阈值、人工介入、异常界面检测。"""

from __future__ import annotations

from region_cua.agent.monitor import Monitor


def test_success_resets_counter():
    m = Monitor(max_failures=3)
    assert m.on_step(1, False) == "continue"
    assert m.on_step(2, False) == "continue"
    assert m.on_step(3, True) == "continue"
    # 成功后重置，再两次失败不应触发
    assert m.on_step(4, False) == "continue"
    assert m.on_step(5, False) == "continue"


def test_threshold_triggers_ask():
    asked = []
    m = Monitor(max_failures=2, ask_user=lambda p: asked.append(p) or "abort")
    assert m.on_step(1, False) == "continue"
    assert m.on_step(2, False) == "abort"
    assert len(asked) == 1


def test_ask_continue_resets():
    m = Monitor(max_failures=2, ask_user=lambda p: "continue")
    assert m.on_step(1, False) == "continue"
    assert m.on_step(2, False) == "continue"  # 询问后重置
    assert m.on_step(3, False) == "continue"
    assert m.on_step(4, False) == "continue"  # 再次询问


def test_detect_anomaly_login():
    assert Monitor.detect_anomaly("请输入账号和密码登录") is not None
    assert Monitor.detect_anomaly("scan QR code 验证码") is not None
    assert Monitor.detect_anomaly("这是一个普通的桌面界面") is None


def test_default_ask_eof_returns_abort(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda *a: (_ for _ in ()).throw(EOFError()))
    m = Monitor(max_failures=1)
    assert m.on_step(1, False) == "abort"
