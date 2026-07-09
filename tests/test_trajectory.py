"""结构化轨迹测试：JSONL 格式、坐标提取、load_trajectory。"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from region_cua.agent.models import StepRecord, TaskPlan
from region_cua.recorder.trajectory import export_trajectory, load_trajectory, _extract_coords


def _records(tmp_path: Path) -> list[StepRecord]:
    ss = tmp_path / "screenshots"
    return [
        StepRecord(order=1, action="open_app", description="打开WPS", target="WPS",
                   screenshot_before=str(ss / "s1b.png"), screenshot_after=str(ss / "s1a.png"),
                   success=True, vision_analysis='{"found":true}'),
        StepRecord(order=2, action="click", description="点击按钮", target="320,480",
                   value="left", success=False, error="找不到元素"),
        StepRecord(order=3, action="type", description="输入文字", target="你好世界",
                   success=True),
    ]


def test_export_creates_jsonl(tmp_path):
    plan = TaskPlan(task="测试任务")
    records = _records(tmp_path)
    traj = export_trajectory(plan, records, tmp_path,
                             datetime(2026, 6, 20, 12, 0), datetime(2026, 6, 20, 12, 1))
    assert traj.exists()
    lines = traj.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 5  # meta + 3 steps + summary

    # 第一行是 meta
    meta = json.loads(lines[0])
    assert meta["type"] == "meta"
    assert meta["task"] == "测试任务"
    assert meta["total_steps"] == 3

    # 中间是 steps
    for i, line in enumerate(lines[1:4], 1):
        entry = json.loads(line)
        assert entry["type"] == "step"
        assert entry["step"] == i

    # 最后一行是 summary
    summary = json.loads(lines[-1])
    assert summary["type"] == "summary"
    assert summary["success_steps"] == 2
    assert summary["failed_steps"] == 1


def test_coords_extracted_from_target(tmp_path):
    plan = TaskPlan(task="t")
    records = [StepRecord(order=1, action="click", target="320,480")]
    traj = export_trajectory(plan, records, tmp_path)
    data = load_trajectory(traj)
    step = [d for d in data if d["type"] == "step"][0]
    assert step["coords"] == [320, 480]


def test_coords_none_when_not_numeric(tmp_path):
    plan = TaskPlan(task="t")
    records = [StepRecord(order=1, action="type", target="你好世界")]
    traj = export_trajectory(plan, records, tmp_path)
    data = load_trajectory(traj)
    step = [d for d in data if d["type"] == "step"][0]
    assert step["coords"] is None


def test_screenshot_paths_relativized(tmp_path):
    plan = TaskPlan(task="t")
    records = [StepRecord(order=1, action="open_app", target="a",
                          screenshot_before=str(tmp_path / "screenshots" / "b.png"),
                          screenshot_after=str(tmp_path / "screenshots" / "a.png"))]
    traj = export_trajectory(plan, records, tmp_path)
    data = load_trajectory(traj)
    step = [d for d in data if d["type"] == "step"][0]
    assert step["screenshot_before"] == "screenshots/b.png"
    assert step["screenshot_after"] == "screenshots/a.png"


def test_load_trajectory_skips_bad_lines(tmp_path):
    p = tmp_path / "bad.jsonl"
    p.write_text('{"valid":1}\nnot json\n{"valid":2}\n', encoding="utf-8")
    data = load_trajectory(p)
    assert len(data) == 2


def test_extract_coords_chinese_comma():
    assert _extract_coords("320，480") == [320, 480]
    assert _extract_coords("320, 480") == [320, 480]
    assert _extract_coords("搜索框") is None
    assert _extract_coords("") is None
