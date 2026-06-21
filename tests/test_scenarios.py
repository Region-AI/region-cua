"""集成场景测试：真实驱动桌面应用，验证实现质量。

默认跳过（需 Ollama + 真实桌面）。运行方式：

    poetry run pytest -m integration           # 运行全部集成测试
    poetry run pytest tests/test_scenarios.py::test_dry_run_produces_plan  # 仅 dry-run

场景覆盖（README 要求）：
  - WPS 文字写文档
  - WPS 演示做 PPT
  - WPS 表格做电子表格
  - 浏览器搜索热点话题
  - 计算器（基础冒烟）

注意：这些测试会真实操控桌面（移动鼠标、打开应用），请在无人值守时谨慎运行。
"""

from __future__ import annotations

import pytest

from region_cua.main import run_task

# (id, 任务描述)
SCENARIOS = [
    ("wps_doc", "打开 WPS 文字，新建一个文档，输入标题'季度工作总结'和一段正文，保存到桌面"),
    ("wps_ppt", "打开 WPS 演示，新建演示文稿，添加一张标题幻灯片，标题写'产品发布'，保存"),
    ("wps_sheet", "打开 WPS 表格，新建工作簿，在 A1 输入'姓名'、B1 输入'成绩'，再填两行示例数据并保存"),
    ("browser_search", "打开浏览器，搜索'今日热点新闻'并查看搜索结果"),
    ("calculator", "打开计算器，计算 1024 乘以 768"),
]


@pytest.mark.integration
def test_dry_run_produces_plan(require_ollama):
    """dry-run 仅调用规划模型，不触碰桌面，验证 planner 端到端可用。"""
    plan, records, task_dir = run_task("打开计算器，计算 1024 乘以 768", dry_run=True)
    assert task_dir is None
    assert len(plan.steps) >= 1
    # 规划出的动作应全部合法
    from region_cua.agent.models import VALID_ACTIONS
    for s in plan.steps:
        assert s.action in VALID_ACTIONS


@pytest.mark.integration
@pytest.mark.desktop
@pytest.mark.parametrize("sid,task", SCENARIOS, ids=[s[0] for s in SCENARIOS])
def test_scenario_runs_and_produces_doc(require_ollama, sid, task):
    """每个场景真实执行并产出操作说明文档。失败时 ask_user 直接 abort 避免卡住。"""
    plan, records, task_dir = run_task(task, no_video=True, ask_user=lambda m: "abort")
    assert task_dir is not None, "任务应创建输出目录"
    assert (task_dir / "任务说明.md").exists(), "应生成操作说明文档"
    assert (task_dir / "scripts" / "replay.py").exists(), "应生成可复用脚本"
    assert len(records) > 0, "应至少执行一步"
