"""跨平台 keep_awake 测试：上下文管理器、平台分发、enabled 开关。"""

from __future__ import annotations

from region_cua.automation import awake


def test_keep_awake_disabled_yields_none():
    """enabled=False 时不调用任何系统 API，yield None。"""
    with awake.keep_awake(enabled=False) as h:
        assert h is None


def test_keep_awake_enabled_returns_handle(monkeypatch):
    """enabled=True 时获取句柄，with 退出后调用 restore。"""
    restore_called = {"n": 0}

    def fake_restore():
        restore_called["n"] += 1

    monkeypatch.setattr(
        awake, "acquire_keep_awake",
        lambda: awake._AwakeHandle(fake_restore, "test"),
    )
    with awake.keep_awake(enabled=True) as h:
        assert h is not None
        assert h.backend == "test"
    assert restore_called["n"] == 1


def test_handle_close_is_idempotent():
    """close() 多次调用只触发一次 restore。"""
    n = {"v": 0}
    h = awake._AwakeHandle(lambda: n.__setitem__("v", n["v"] + 1), "test")
    h.close()
    h.close()
    h.close()
    assert n["v"] == 1


def test_handle_swallows_restore_exception():
    """restore 抛异常不应传播到 close 调用方。"""
    def boom():
        raise RuntimeError("fail")
    h = awake._AwakeHandle(boom, "test")
    h.close()  # 不应抛异常


def test_keep_awake_restores_even_on_exception(monkeypatch):
    """with 块内抛异常时，restore 仍应被调用（finally 语义）。"""
    restored = {"v": False}
    monkeypatch.setattr(
        awake, "acquire_keep_awake",
        lambda: awake._AwakeHandle(lambda: restored.__setitem__("v", True), "test"),
    )
    try:
        with awake.keep_awake(enabled=True):
            raise ValueError("任务出错")
    except ValueError:
        pass
    assert restored["v"] is True


def test_acquire_returns_handle_on_current_platform():
    """在当前平台 acquire 应返回一个有效 handle，close() 安全。"""
    h = awake.acquire_keep_awake()
    assert h.backend  # 非空
    h.close()


def test_unsupported_platform_no_op(monkeypatch):
    """未知 platform 退化为 no-op handle。"""
    monkeypatch.setattr(awake.platform, "system", lambda: "Plan9")
    h = awake.acquire_keep_awake()
    assert h.backend == "unsupported:Plan9"
    h.close()  # 不应抛异常


def test_linux_no_systemd_inhibit(monkeypatch):
    """Linux 上 systemd-inhibit 不存在时降级为 no-op，不报错。"""
    def boom(*a, **k):
        raise FileNotFoundError("no systemd-inhibit")
    monkeypatch.setattr(awake.subprocess, "Popen", boom)
    h = awake._linux_keep_awake()
    assert "no-systemd-inhibit" in h.backend
    h.close()
