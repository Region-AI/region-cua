"""生成带截图的 Markdown 操作说明文档。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from ..agent.models import StepRecord, TaskPlan
from ..recorder.screenshots import relpath


def generate_doc(plan: TaskPlan, records: list[StepRecord], task_dir: Path) -> str:
    """生成 Markdown 文档并写入 task_dir，返回文档内容。"""
    task_dir = Path(task_dir)
    total = len(records)
    success = sum(1 for r in records if r.success)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines: list[str] = []
    lines.append(f"# 任务：{plan.task or '未命名任务'}")
    lines.append("")
    lines.append("## 执行摘要")
    lines.append("")
    lines.append(f"- 生成时间：{now}")
    lines.append(f"- 步骤总数：{total}")
    lines.append(f"- 成功步骤：{success}")
    lines.append(f"- 失败步骤：{total - success}")
    lines.append(f"- 任务目录：`{task_dir}`")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 操作步骤")
    lines.append("")

    for r in records:
        lines.append(f"### 步骤 {r.order}：{r.description or r.action}")
        lines.append("")
        lines.append(f"- 操作：`{r.action}`")
        if r.target:
            lines.append(f"- 目标：`{r.target}`")
        lines.append(f"- 状态：{'✅ 成功' if r.success else '❌ 失败'}")
        if r.error:
            lines.append(f"- 错误：{r.error}")
        lines.append("")

        if r.screenshot_before:
            rel = relpath(r.screenshot_before, task_dir)
            lines.append(f"**操作前：**")
            lines.append("")
            lines.append(f"![before-{r.order}]({rel})")
            lines.append("")
        if r.vision_analysis:
            lines.append(f"> 视觉分析：{r.vision_analysis}")
            lines.append("")
        if r.screenshot_after:
            rel = relpath(r.screenshot_after, task_dir)
            lines.append(f"**操作后：**")
            lines.append("")
            lines.append(f"![after-{r.order}]({rel})")
            lines.append("")
        if r.vision_check:
            lines.append(f"> 操作验证：{r.vision_check}")
            lines.append("")
        lines.append("---")
        lines.append("")

    content = "\n".join(lines)
    doc_path = task_dir / "任务说明.md"
    doc_path.write_text(content, encoding="utf-8")
    return content
