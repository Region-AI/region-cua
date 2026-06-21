"""生成可复用的 Python 脚本：把执行步骤回放为参数化的 pyautogui 脚本。"""

from __future__ import annotations

from pathlib import Path

from ..agent.models import StepRecord, TaskPlan


def _py_str(s: str) -> str:
    return repr(str(s))


def generate_script(plan: TaskPlan, records: list[StepRecord], task_dir: Path) -> str:
    """生成回放脚本并写入 task_dir/scripts/，返回脚本内容。"""
    task_dir = Path(task_dir)
    (task_dir / "scripts").mkdir(parents=True, exist_ok=True)

    # 收集 type 动作的文本为变量，便于参数化复用
    type_vars: list[str] = []
    var_map: dict[int, str] = {}
    for r in records:
        if r.action == "type" and r.target:
            vname = f"text_{len(type_vars) + 1}"
            type_vars.append(r.target)
            var_map[r.order] = vname

    lines: list[str] = []
    lines.append('"""自动生成的桌面自动化脚本。')
    lines.append(f"任务：{plan.task}")
    lines.append('由 RegionCUA 生成，可直接 python 运行回放。')
    lines.append('"""')
    lines.append("import pyautogui")
    lines.append("import time")
    lines.append("")
    lines.append("pyautogui.FAILSAFE = False  # 关闭角落紧急停止")
    lines.append("")
    # 参数化变量
    for i, val in enumerate(type_vars, 1):
        lines.append(f"text_{i} = {_py_str(val)}")
    if type_vars:
        lines.append("")
    lines.append("def main():")
    if not records:
        lines.append("    pass")
    for r in records:
        desc = r.description or r.action
        lines.append(f"    # 步骤 {r.order}: {desc}")
        body = _step_body(r, var_map)
        for b in body:
            lines.append(f"    {b}")
        lines.append(f"    time.sleep(0.8)")
    lines.append("")
    lines.append('if __name__ == "__main__":')
    lines.append("    main()")
    lines.append("")

    content = "\n".join(lines)
    (task_dir / "scripts" / "replay.py").write_text(content, encoding="utf-8")
    return content


def _step_body(r: StepRecord, var_map: dict[int, str]) -> list[str]:
    a = r.action
    if a == "open_app":
        return [f"import os; os.startfile({_py_str(r.target)})"]
    if a == "click":
        import re

        m = re.match(r"\s*(\d+)\s*[,，]\s*(\d+)\s*$", r.target or "")
        if m:
            x, y = m.group(1), m.group(2)
            clicks = "2" if "double" in (r.value or "").lower() else "1"
            btn = '"right"' if "right" in (r.value or "").lower() else '"left"'
            return [f"pyautogui.click({x}, {y}, clicks={clicks}, button={btn}, duration=0.2)"]
        return ["pass  # 坐标未确定，需手动补充"]
    if a == "type":
        var = var_map.get(r.order)
        if var:
            return [f"pyautogui.write({var}, interval=0.02)"]
        return [f"pyautogui.write({_py_str(r.target)}, interval=0.02)"]
    if a == "hotkey":
        keys = ", ".join(_py_str(k.strip()) for k in (r.target or "").replace(" ", "").split("+") if k.strip())
        return [f"pyautogui.hotkey({keys})"] if keys else ["pass"]
    if a == "scroll":
        import re

        m = re.match(r"-?\d+", r.target or "")
        n = m.group(0) if m else "-3"
        return [f"pyautogui.scroll({n})"]
    if a == "wait":
        import re

        m = re.match(r"[\d.]+", r.target or "")
        t = m.group(0) if m else "2.0"
        return [f"time.sleep({t})"]
    if a == "screenshot":
        return ["pyautogui.screenshot()"]
    if a == "done":
        return ["pass  # 任务完成"]
    return ["pass"]
