"""数据模型：任务计划、步骤、执行记录。

action 取值（与 planner 提示词保持一致）：
  open_app   启动应用      target=应用名/路径
  click      点击          target="x,y" 或元素描述（vision 解析为坐标）  value=left/right/double
  type       输入文本      target=要输入的文本（支持中文）
  hotkey     组合键        target="ctrl+s"
  scroll     滚动          target=整数（正向上、负向下）
  wait       等待          target=秒数
  screenshot 截图          （仅记录）
  done       任务完成      value=总结
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

# 合法的 action 集合
VALID_ACTIONS = {
    "open_app", "click", "type", "hotkey", "scroll", "wait", "screenshot", "done",
}


class Step(BaseModel):
    order: int = 0
    action: str = ""
    target: str = ""
    value: str = ""
    description: str = ""
    requires_vision: bool = True

    def normalized_action(self) -> str:
        return (self.action or "").strip().lower()


class TaskPlan(BaseModel):
    task: str = ""
    steps: list[Step] = Field(default_factory=list)


class StepRecord(BaseModel):
    order: int
    action: str = ""
    description: str = ""
    target: str = ""
    value: str = ""
    screenshot_before: Optional[str] = None
    screenshot_after: Optional[str] = None
    vision_analysis: str = ""
    vision_check: str = ""
    success: bool = True
    error: str = ""
    timestamp: str = ""

    @property
    def status_icon(self) -> str:
        return "成功" if self.success else "失败"
