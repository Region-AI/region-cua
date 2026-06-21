"""TaskPlanner：把自然语言任务分解为结构化步骤序列。

调用 Ollama 规划模型输出 JSON，再做严格清洗：
- 去除 markdown 代码围栏、提取首个 JSON 对象
- 把 null / 缺失字段补成安全默认值（避免 pydantic 校验报错）
- 解析失败时回退为单步「探索式执行」，保证不中断
"""

from __future__ import annotations

import json
import re
from typing import Any

from ..vision.ollama_client import OllamaClient
from .models import Step, TaskPlan, VALID_ACTIONS

PLANNER_SYSTEM = """你是一个 Windows 桌面自动化任务规划器。
给定用户的自然语言任务，把它分解为一系列可在桌面执行的原子步骤，输出严格的 JSON。

可选 action 及参数：
- open_app: 启动应用。target=应用名或可执行名（如 "calc"、"WPS 文字"、"notepad"）
- click: 点击。target 给元素描述（如 "搜索框"），执行时会用视觉模型定位坐标；若已知坐标可写 "x,y"
- type: 输入文本。target=要输入的文字（支持中文）
- hotkey: 组合键。target="ctrl+s" 这种形式
- scroll: 滚动。target=整数，正向上负向下
- wait: 等待。target=秒数（应用启动/加载用）
- screenshot: 截图记录当前界面
- done: 任务完成，value 写一句话总结

每步包含字段：order(从1开始), action, target, value, description(简短中文说明), requires_vision(bool，click 默认 true，open_app/type 可 false)。

只输出 JSON 对象，不要解释文字，不要 markdown 代码块。示例：
{"task":"打开计算器计算1024乘以768","steps":[{"order":1,"action":"open_app","target":"calc","value":"","description":"打开计算器","requires_vision":false},{"order":2,"action":"click","target":"数字1","value":"left","description":"点击1","requires_vision":true}]}
"""


def _extract_json(text: str) -> dict[str, Any] | None:
    """从模型输出中提取首个 JSON 对象，兼容代码围栏与前后说明。"""
    if not text:
        return None
    # 去掉 ```json ... ``` 围栏
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    candidate = fenced.group(1) if fenced else text
    # 找第一个 { 到匹配的 }
    start = candidate.find("{")
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(candidate)):
        if candidate[i] == "{":
            depth += 1
        elif candidate[i] == "}":
            depth -= 1
            if depth == 0:
                snippet = candidate[start : i + 1]
                try:
                    return json.loads(snippet)
                except json.JSONDecodeError:
                    return None
    return None


def _clean(value: Any) -> Any:
    """递归把 None 转成空字符串，保留其他类型。"""
    if value is None:
        return ""
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    return value


class TaskPlanner:
    def __init__(self, client: OllamaClient, model: str):
        self.client = client
        self.model = model

    def plan(self, task: str) -> TaskPlan:
        messages = [
            {"role": "system", "content": PLANNER_SYSTEM},
            {"role": "user", "content": f"任务：{task}"},
        ]
        try:
            raw = self.client.chat(self.model, messages)
        except Exception as exc:  # 规划失败也要能继续
            return self._fallback(task, f"planner 调用失败: {exc}")
        return self._parse(raw, task)

    # ------------------------------------------------------------------ parse
    def _parse(self, raw: str, task: str) -> TaskPlan:
        data = _extract_json(raw)
        if not data:
            return self._fallback(task, "无法解析 JSON，使用探索式单步")
        data = _clean(data)
        raw_steps = data.get("steps") or []
        steps: list[Step] = []
        for i, s in enumerate(raw_steps):
            if not isinstance(s, dict):
                continue
            s = _clean(s)
            action = str(s.get("action", "")).strip().lower()
            if action not in VALID_ACTIONS:
                # 未知 action：归一为 screenshot，避免执行器报错
                action = "screenshot"
            steps.append(
                Step(
                    order=int(s.get("order", i + 1) or i + 1),
                    action=action,
                    target=str(s.get("target", "")),
                    value=str(s.get("value", "")),
                    description=str(s.get("description", "")),
                    requires_vision=bool(s.get("requires_vision", action == "click")),
                )
            )
        if not steps:
            return self._fallback(task, "步骤为空，使用探索式单步")
        return TaskPlan(task=str(data.get("task", task)) or task, steps=steps)

    @staticmethod
    def _fallback(task: str, reason: str) -> TaskPlan:
        """规划失败兜底：单步 open_app + 探索。"""
        step = Step(
            order=1,
            action="open_app",
            target=task,
            description=f"探索式执行（{reason}）",
            requires_vision=True,
        )
        return TaskPlan(task=task, steps=[step])
