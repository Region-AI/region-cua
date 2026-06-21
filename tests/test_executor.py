"""TaskExecutor 单元测试：动作分发、坐标兜底、参数容错、视觉失败隔离、索引安全。"""

from __future__ import annotations

import pytest

from region_cua.agent.executor import TaskExecutor
from region_cua.agent.models import Step, TaskPlan
from region_cua.agent.monitor import Monitor


def _executor(client, tmp_path, monitor=None, verify=True):
    return TaskExecutor(
        client, "vision-model", tmp_path,
        monitor or Monitor(max_failures=99),
        record_video=False, verify=verify,
    )


# ------------------------------------------------------------- action dispatch
def test_open_app(stub_desktop, tmp_path, fake_client_cls):
    ex = _executor(fake_client_cls(), tmp_path)
    ex._do_action(Step(action="open_app", target="calc"))
    assert stub_desktop["open_app"] == ["calc"]


def test_click_with_coords(stub_desktop, tmp_path, fake_client_cls):
    ex = _executor(fake_client_cls(), tmp_path)
    ex._do_action(Step(action="click", target="100,200", value="left"))
    assert stub_desktop["click"] == [(100, 200, "left", 1)]


def test_click_double_and_right(stub_desktop, tmp_path, fake_client_cls):
    ex = _executor(fake_client_cls(), tmp_path)
    ex._do_action(Step(action="click", target="10,20", value="double"))
    ex._do_action(Step(action="click", target="30,40", value="right"))
    assert stub_desktop["click"][0] == (10, 20, "left", 2)
    assert stub_desktop["click"][1] == (30, 40, "right", 1)


def test_click_no_coords_falls_back_to_center(stub_desktop, tmp_path, fake_client_cls):
    """无坐标且未启用视觉定位时，点击屏幕中心而非 (0,0)。"""
    ex = _executor(fake_client_cls(), tmp_path)
    ex._do_action(Step(action="click", target="搜索框", requires_vision=False))
    assert stub_desktop["click"] == [(960, 540, "left", 1)]


def test_type_text(stub_desktop, tmp_path, fake_client_cls):
    ex = _executor(fake_client_cls(), tmp_path)
    ex._do_action(Step(action="type", target="你好世界"))
    assert stub_desktop["type"] == ["你好世界"]


def test_scroll_invalid_target_defaults(stub_desktop, tmp_path, fake_client_cls):
    ex = _executor(fake_client_cls(), tmp_path)
    ex._do_action(Step(action="scroll", target="向下"))
    assert stub_desktop["scroll"] == [-3]


def test_hotkey_invalid_no_crash(stub_desktop, tmp_path, fake_client_cls):
    ex = _executor(fake_client_cls(), tmp_path)
    # 不应抛异常
    ex._do_action(Step(action="hotkey", target="保存"))
    ex._do_action(Step(action="hotkey", target="ctrl+s"))


def test_wait_invalid_target(stub_desktop, tmp_path, fake_client_cls):
    ex = _executor(fake_client_cls(), tmp_path)
    ex._do_action(Step(action="wait", target="一会"))
    assert stub_desktop["wait"] == ["一会"]


# ------------------------------------------------------------- full loop
def test_execute_full_loop_with_vision(stub_desktop, tmp_path, fake_client_cls):
    client = fake_client_cls(responses={
        "找到": '{"found": true, "x": 300, "y": 400, "description": "按钮"}',
        "判断": '{"success": true, "reason": "操作成功"}',
    })
    plan = TaskPlan(task="t", steps=[
        Step(order=1, action="open_app", target="calc", requires_vision=False),
        Step(order=2, action="click", target="按钮", requires_vision=True),
    ])
    records = _executor(client, tmp_path).execute(plan)
    assert len(records) == 2
    assert all(r.success for r in records)
    # click 使用了视觉定位坐标
    assert (300, 400, "left", 1) in stub_desktop["click"]
    assert records[0].screenshot_before and records[0].screenshot_after


def test_vision_failure_isolation(stub_desktop, tmp_path, fake_client_cls):
    """视觉模型故障不应中断任务：定位失败→兜底中心点击，验证失败→记录但继续。"""
    client = fake_client_cls(raise_on=True)
    plan = TaskPlan(task="t", steps=[Step(order=1, action="click", target="按钮", requires_vision=True)])
    records = _executor(client, tmp_path, verify=True).execute(plan)
    assert len(records) == 1
    assert records[0].success is True
    assert "失败" in records[0].vision_analysis
    assert "失败" in records[0].vision_check
    assert (960, 540, "left", 1) in stub_desktop["click"]


def test_monitor_abort_on_consecutive_failures(stub_desktop, tmp_path, fake_client_cls, monkeypatch):
    import region_cua.automation.appfinder as af

    monkeypatch.setattr(af, "open_app", lambda n: (_ for _ in ()).throw(RuntimeError("打不开")))
    monitor = Monitor(max_failures=1, ask_user=lambda m: "abort")
    plan = TaskPlan(task="t", steps=[
        Step(order=1, action="open_app", target="x"),
        Step(order=2, action="open_app", target="y"),
    ])
    records = _executor(fake_client_cls(), tmp_path, monitor=monitor).execute(plan)
    assert len(records) == 1  # 第一步失败即 abort，未执行第二步
    assert records[0].success is False


def test_index_safety_noncontiguous_order(stub_desktop, tmp_path, fake_client_cls):
    """step.order 非连续/越界不应导致 IndexError。"""
    plan = TaskPlan(task="t", steps=[
        Step(order=99, action="open_app", target="a"),
        Step(order=5, action="open_app", target="b"),
    ])
    records = _executor(fake_client_cls(), tmp_path).execute(plan)
    assert len(records) == 2
    assert [r.order for r in records] == [1, 2]


def test_done_stops_early(stub_desktop, tmp_path, fake_client_cls):
    plan = TaskPlan(task="t", steps=[
        Step(order=1, action="open_app", target="a"),
        Step(order=2, action="done"),
        Step(order=3, action="open_app", target="b"),
    ])
    records = _executor(fake_client_cls(), tmp_path).execute(plan)
    assert len(records) == 2


def test_logger_persists_on_success(stub_desktop, tmp_path, fake_client_cls):
    """成功路径下 operation.log 应包含每步开始/结束/总结。"""
    client = fake_client_cls(default='{"success":true,"reason":"ok"}')
    plan = TaskPlan(task="t", steps=[
        Step(order=1, action="open_app", target="calc", requires_vision=False),
    ])
    _executor(client, tmp_path).execute(plan)
    log_path = tmp_path / "operation.log"
    assert log_path.exists()
    txt = log_path.read_text(encoding="utf-8")
    assert "RegionCUA 任务日志" in txt
    assert "▶ 步骤 1" in txt
    assert "◀ 步骤 1 ✓" in txt
    assert "执行结束" in txt


def test_logger_persists_on_step_failure(stub_desktop, tmp_path, fake_client_cls, monkeypatch):
    """单步失败也要在日志里记录 ✗，并仍写出总结。"""
    import region_cua.automation.appfinder as af

    monkeypatch.setattr(af, "open_app", lambda n: (_ for _ in ()).throw(RuntimeError("打不开")))
    plan = TaskPlan(task="t", steps=[Step(order=1, action="open_app", target="x")])
    monitor = Monitor(max_failures=99)  # 不触发 abort
    _executor(fake_client_cls(), tmp_path, monitor=monitor).execute(plan)
    txt = (tmp_path / "operation.log").read_text(encoding="utf-8")
    assert "✗ 失败" in txt
    assert "打不开" in txt
    assert "执行结束" in txt


def test_no_log_disables_logfile(stub_desktop, tmp_path, fake_client_cls):
    """record_log=False 时不应生成 operation.log。"""
    plan = TaskPlan(task="t", steps=[Step(order=1, action="open_app", target="a")])
    monitor = Monitor(max_failures=99)
    ex = TaskExecutor(
        fake_client_cls(), "v", tmp_path, monitor,
        record_video=False, record_log=False, verify=False,
    )
    ex.execute(plan)
    assert not (tmp_path / "operation.log").exists()
