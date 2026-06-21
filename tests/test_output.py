"""输出产物测试：Markdown 文档与可复用脚本生成。"""

from __future__ import annotations

from pathlib import Path

from region_cua.agent.models import StepRecord, TaskPlan
from region_cua.output.docs import generate_doc
from region_cua.output.scripts import generate_script


def _records(tmp_path: Path) -> list[StepRecord]:
    ss = tmp_path / "screenshots"
    return [
        StepRecord(order=1, action="open_app", description="打开计算器", target="calc",
                   screenshot_before=str(ss / "s1b.png"), screenshot_after=str(ss / "s1a.png"),
                   success=True),
        StepRecord(order=2, action="click", description="点击按钮", target="300,400",
                   success=False, error="找不到元素"),
        StepRecord(order=3, action="type", description="输入文本", target="1024", success=True),
        StepRecord(order=4, action="hotkey", description="保存", target="ctrl+s", success=True),
        StepRecord(order=5, action="done", description="完成", value="完成", success=True),
    ]


def test_generate_doc(tmp_path):
    plan = TaskPlan(task="打开计算器计算1024乘以768")
    records = _records(tmp_path)
    content = generate_doc(plan, records, tmp_path)
    doc = Path(tmp_path / "任务说明.md")
    assert doc.exists()
    assert "打开计算器计算1024乘以768" in content
    assert "✅ 成功" in content
    assert "❌ 失败" in content
    assert "找不到元素" in content
    assert "screenshots/s1b.png" in content  # 相对路径内嵌
    assert "screenshots/s1a.png" in content


def test_generate_script(tmp_path):
    plan = TaskPlan(task="打开计算器计算1024乘以768")
    records = _records(tmp_path)
    content = generate_script(plan, records, tmp_path)
    script = Path(tmp_path / "scripts" / "replay.py")
    assert script.exists()
    assert "import pyautogui" in content
    assert "pyautogui.FAILSAFE = False" in content
    assert "os.startfile('calc')" in content
    assert "pyautogui.click(300, 400" in content
    assert "text_1 = '1024'" in content
    assert "pyautogui.write(text_1" in content
    assert "pyautogui.hotkey('ctrl', 's')" in content
