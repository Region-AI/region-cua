"""TaskPlanner 单元测试：JSON 提取、null 清洗、回退、未知 action 归一。"""

from __future__ import annotations

from region_cua.agent.planner import TaskPlanner, _clean, _extract_json


# ---------------------------------------------------------------- _extract_json
def test_extract_json_plain():
    assert _extract_json('{"a": 1, "b": 2}') == {"a": 1, "b": 2}


def test_extract_json_fenced():
    assert _extract_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_extract_json_with_prose():
    assert _extract_json('好的，结果如下：\n{"a": 1}\n以上。') == {"a": 1}


def test_extract_json_nested():
    assert _extract_json('{"a": {"b": [1,2]}}') == {"a": {"b": [1, 2]}}


def test_extract_json_empty():
    assert _extract_json("") is None
    assert _extract_json("没有json") is None


# --------------------------------------------------------------------- _clean
def test_clean_none_to_empty():
    assert _clean(None) == ""
    assert _clean({"a": None, "b": 1}) == {"a": "", "b": 1}
    assert _clean([None, 1, {"x": None}]) == ["", 1, {"x": ""}]


# -------------------------------------------------------------- planner.parse
def test_parse_valid_with_nulls(fake_client_cls):
    raw = (
        '{"task":"测试","steps":['
        '{"order":1,"action":"open_app","target":"calc","value":null,"description":null,"requires_vision":null},'
        '{"order":2,"action":"click","target":"按钮","value":"left"},'
        '{"order":3,"action":"未知动作","target":"x"}'
        ']}'
    )
    client = fake_client_cls(default=raw)
    plan = TaskPlanner(client, "m").plan("测试")
    assert plan.task == "测试"
    assert len(plan.steps) == 3
    s1 = plan.steps[0]
    assert s1.action == "open_app"
    assert s1.value == ""          # null → ""
    assert s1.description == ""
    assert s1.requires_vision is False  # open_app 默认 False
    s2 = plan.steps[1]
    assert s2.requires_vision is True   # click 默认 True
    s3 = plan.steps[2]
    assert s3.action == "screenshot"    # 未知 action 归一为 screenshot


def test_parse_fallback_on_bad_json(fake_client_cls):
    client = fake_client_cls(default="这不是JSON")
    plan = TaskPlanner(client, "m").plan("随便做点什么")
    assert len(plan.steps) == 1
    assert plan.steps[0].action == "open_app"
    assert plan.task == "随便做点什么"


def test_parse_fallback_on_empty_steps(fake_client_cls):
    client = fake_client_cls(default='{"task":"t","steps":[]}')
    plan = TaskPlanner(client, "m").plan("t")
    assert len(plan.steps) == 1
    assert plan.steps[0].action == "open_app"


def test_plan_client_failure_falls_back(fake_client_cls):
    client = fake_client_cls(raise_on=True)
    plan = TaskPlanner(client, "m").plan("任务")
    assert len(plan.steps) == 1
    assert plan.steps[0].action == "open_app"


def test_plan_orders_are_sequential(fake_client_cls):
    raw = '{"task":"t","steps":[{"action":"open_app","target":"a"},{"action":"wait","target":"2"}]}'
    client = fake_client_cls(default=raw)
    plan = TaskPlanner(client, "m").plan("t")
    assert [s.order for s in plan.steps] == [1, 2]
