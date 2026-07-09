"""结构化轨迹：把任务执行过程导出为 JSONL，便于回放、分析和训练。

每行一个 JSON 对象，对应一个步骤的完整记录：
  {"step": 1, "timestamp": "...", "action": "click", "target": "320,480",
   "coords": [320, 480], "screenshot_before": "...", "screenshot_after": "...",
   "vision_analysis": "...", "vision_check": "...", "success": true,
   "error": "", "duration_ms": 1234}

与 operation.log（人类可读文本）互补，trajectory.jsonl 面向机器回放。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from ..agent.models import StepRecord, TaskPlan


def export_trajectory(
    plan: TaskPlan,
    records: list[StepRecord],
    task_dir: Path,
    task_started_at: Optional[datetime] = None,
    task_ended_at: Optional[datetime] = None,
) -> Path:
    """导出结构化轨迹到 task_dir/trajectory.jsonl，返回文件路径。

    records 中的 timestamps 用 HHMMSS 字符串，这里补全为完整 ISO 时间。
    """
    task_dir = Path(task_dir)
    traj_path = task_dir / "trajectory.jsonl"
    lines: list[str] = []

    # 元数据头（第一行，type=meta）
    meta: dict[str, Any] = {
        "type": "meta",
        "task": plan.task,
        "total_steps": len(records),
        "started_at": task_started_at.isoformat() if task_started_at else None,
        "ended_at": task_ended_at.isoformat() if task_ended_at else None,
    }
    lines.append(json.dumps(meta, ensure_ascii=False))

    # 每步一条记录
    for r in records:
        coords = _extract_coords(r.target)
        entry: dict[str, Any] = {
            "type": "step",
            "step": r.order,
            "timestamp": r.timestamp,
            "action": r.action,
            "target": r.target,
            "value": r.value,
            "coords": coords,
            "description": r.description,
            "screenshot_before": _relpath(r.screenshot_before, task_dir),
            "screenshot_after": _relpath(r.screenshot_after, task_dir),
            "vision_analysis": r.vision_analysis,
            "vision_check": r.vision_check,
            "success": r.success,
            "error": r.error,
        }
        lines.append(json.dumps(entry, ensure_ascii=False))

    # 汇总尾（最后一行，type=summary）
    ok = sum(1 for r in records if r.success)
    summary: dict[str, Any] = {
        "type": "summary",
        "total_steps": len(records),
        "success_steps": ok,
        "failed_steps": len(records) - ok,
        "result": "success" if ok == len(records) and len(records) > 0 else "partial" if ok > 0 else "failed",
    }
    lines.append(json.dumps(summary, ensure_ascii=False))

    traj_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return traj_path


def load_trajectory(path: str | Path) -> list[dict[str, Any]]:
    """读取 JSONL 轨迹文件，返回 dict 列表。"""
    p = Path(path)
    result = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            result.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return result


def _extract_coords(target: str) -> Optional[list[int]]:
    """从 target 字段提取 [x, y] 坐标，无法解析返回 None。"""
    if not target:
        return None
    import re

    m = re.match(r"\s*(\d+)\s*[,，]\s*(\d+)\s*$", target)
    if m:
        return [int(m.group(1)), int(m.group(2))]
    return None


def _relpath(path: Optional[str], base: Path) -> Optional[str]:
    if not path:
        return None
    try:
        return str(Path(path).relative_to(base)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")
