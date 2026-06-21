"""操作日志器测试：写入、刷新、上下文管理器、no-op、异常容错。"""

from __future__ import annotations

from pathlib import Path

from region_cua.agent.models import Step, StepRecord
from region_cua.recorder.oplog import OperationLogger


def test_disabled_when_no_path(tmp_path):
    log = OperationLogger(None, enabled=True)
    assert log.enabled is False
    log.info("no-op should not crash")
    log.close()


def test_disabled_explicit(tmp_path):
    log = OperationLogger(tmp_path / "op.log", enabled=False)
    assert log.enabled is False
    log.info("nothing written")
    log.close()
    assert not (tmp_path / "op.log").exists()


def test_basic_writes_and_flushes(tmp_path):
    p = tmp_path / "op.log"
    log = OperationLogger(p, enabled=True)
    log.header("打开计算器", "qwen3.6:latest", "qwen3.6:latest")
    # flush 后应立即可读
    content = p.read_text(encoding="utf-8")
    assert "RegionCUA 任务日志" in content
    assert "qwen3.6:latest" in content
    log.close()


def test_step_lifecycle_logs(tmp_path):
    p = tmp_path / "op.log"
    log = OperationLogger(p, enabled=True)

    steps = [
        Step(order=1, action="open_app", target="calc", description="启动计算器"),
        Step(order=2, action="click", target="数字1", description="点击 1"),
    ]
    log.header("test", "p", "v")
    log.plan(steps)
    log.step_start(1, steps[0])
    log.info("调用 appfinder.open_app(calc)")
    log.step_end(StepRecord(order=1, action="open_app", description="启动计算器",
                            target="calc", success=True,
                            screenshot_after="/tmp/s.png",
                            vision_check='{"success":true}'))
    log.step_start(2, steps[1])
    log.step_end(StepRecord(order=2, action="click", target="数字1",
                            success=False, error="找不到元素"))
    log.summary(2, 1, video_path=Path("/tmp/v.mp4"))
    log.close()

    txt = p.read_text(encoding="utf-8")
    assert "▶ 步骤 1" in txt
    assert "◀ 步骤 1 ✓ 成功" in txt
    assert "▶ 步骤 2" in txt
    assert "◀ 步骤 2 ✗ 失败" in txt
    assert "找不到元素" in txt
    assert "录屏" in txt or "v.mp4" in txt
    assert "执行结束" in txt


def test_fatal_logs_traceback(tmp_path):
    p = tmp_path / "op.log"
    log = OperationLogger(p, enabled=True)
    try:
        raise RuntimeError("xx")
    except RuntimeError as exc:
        log.fatal(exc)
    log.close()
    txt = p.read_text(encoding="utf-8")
    assert "致命异常" in txt
    assert "RuntimeError" in txt
    assert "Traceback" in txt


def test_context_manager_logs_exception_and_closes(tmp_path):
    p = tmp_path / "op.log"
    try:
        with OperationLogger(p, enabled=True) as log:
            log.header("t", "p", "v")
            raise ValueError("故意抛")
    except ValueError:
        pass
    txt = p.read_text(encoding="utf-8")
    assert "致命异常" in txt
    assert "ValueError" in txt


def test_oneline_truncates_long():
    s = "a" * 500
    assert len(OperationLogger._oneline(s)) <= 200


def test_open_failure_silent_noop(tmp_path, monkeypatch):
    """打开文件失败时 logger 应自动降级为 no-op，不抛异常。"""
    bad = tmp_path / "nonexistent_dir" / "op.log"

    def boom(*a, **k):
        raise PermissionError("denied")

    monkeypatch.setattr("builtins.open", boom)
    log = OperationLogger(bad, enabled=True)
    assert log.enabled is False
    log.info("nothing happens")
    log.close()
