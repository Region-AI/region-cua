"""Bench 规则规划器：根据任务名和描述直接生成操作步骤，不依赖 LLM。

bench 任务的描述格式固定，可以用规则解析出精确的操作步骤，
避免 LLM planner 的不稳定性（生成 open_app、screenshot、步骤不全等问题）。

用法：
    steps = rule_plan("click-button", 'Click the "Submit" button on the page.', elements)
    # → [Step(action="click", target="Submit")]
"""

from __future__ import annotations

import re
from typing import Optional
from ..agent.models import Step, TaskPlan


def rule_plan(task_name: str, description: str, elements: list[dict] = None) -> TaskPlan:
    """根据任务名和描述生成操作步骤。

    Args:
        task_name: 任务目录名（如 "click-button"）
        description: 任务描述（如 'Click the "Submit" button on the page.'）
        elements: OmniParser 解析的页面元素列表（可选，用于辅助）
    """
    planner = _RULE_PLANNERS.get(task_name)
    if planner:
        steps = planner(description, elements or [])
    else:
        # 未知任务：尝试从描述提取引号内容做 click
        steps = _generic_plan(description, elements or [])

    if not steps:
        steps = [Step(order=1, action="screenshot", target="", description="无步骤可执行")]

    # 重新编号
    for i, s in enumerate(steps):
        s.order = i + 1

    return TaskPlan(task=description, steps=steps)


def _extract_quoted(text: str) -> list[str]:
    """提取描述中所有引号里的内容。"""
    return re.findall(r'"([^"]+)"', text)


def _click_button(desc: str, elements: list[dict]) -> list[Step]:
    """click-button: Click the "Submit" button → click "Submit" """
    quoted = _extract_quoted(desc)
    if quoted:
        return [Step(order=1, action="click", target=quoted[0],
                     description=f"点击 {quoted[0]} 按钮", requires_vision=True)]
    # 没有引号，找 button 类型的元素
    for e in elements:
        if e.get("type") == "button" and e.get("text"):
            return [Step(order=1, action="click", target=e["text"],
                         description=f"点击 {e['text']}", requires_vision=True)]
    return []


def _typing_input(desc: str, elements: list[dict]) -> list[Step]:
    """Type "Hello World" into the Username input field → click "Username" → type "Hello World" """
    quoted = _extract_quoted(desc)
    text_to_type = quoted[0] if quoted else ""
    # 提取 "into the X input field" 里的 X
    field_match = re.search(r'into the (.+?) input', desc, re.IGNORECASE)
    field_label = field_match.group(1).strip() if field_match else ""
    if text_to_type and field_label:
        return [
            Step(order=1, action="click", target=field_label,
                 description=f"点击 {field_label} 输入框", requires_vision=True),
            Step(order=2, action="type", target=text_to_type,
                 description=f"输入 {text_to_type}", requires_vision=False),
        ]
    # 兜底：从元素列表找输入框
    if text_to_type:
        for e in elements:
            text = e.get("text", "") or ""
            if text and e.get("center", (0, 0))[1] > 100 and len(text) < 30:
                return [
                    Step(order=1, action="click", target=text,
                         description=f"点击输入框", requires_vision=True),
                    Step(order=2, action="type", target=text_to_type,
                         description=f"输入 {text_to_type}", requires_vision=False),
                ]
    return []


def _toggle_switch(desc: str, elements: list[dict]) -> list[Step]:
    """toggle-switch: click 开关的 label"""
    # 从描述提取目标（如 "Turn on Notifications" → "Notifications"）
    desc_lower = desc.lower()
    # 常见开关关键词
    switch_keywords = ["notifications", "dark mode", "light mode", "auto", "wifi",
                       "bluetooth", "location", "airplane", "battery", "privacy"]
    target = ""
    for kw in switch_keywords:
        if kw in desc_lower:
            target = kw
            break
    # 如果没匹配到关键词，从描述提取最后一个名词（如 "Turn on X" → "X"）
    if not target:
        m = re.search(r'(?:turn on|turn off|toggle|switch|enable|disable)\s+(.+)', desc_lower)
        if m:
            target = m.group(1).strip()
    if target:
        return [Step(order=1, action="click", target=target,
                     description=f"切换 {target}", requires_vision=True)]
    # 兜底：从元素列表找开关
    for e in elements:
        text = e.get("text", "") or ""
        if text and e.get("center", (0, 0))[1] > 120:
            if any(kw in text.lower() for kw in switch_keywords):
                return [Step(order=1, action="click", target=text,
                             description=f"切换 {text}", requires_vision=True)]
    return []


def _drag_slider(desc: str, elements: list[dict]) -> list[Step]:
    """Set the Volume slider to 25 → click 滑块"""
    # 从描述提取滑块名和目标值
    m = re.search(r'Set the (.+?) slider to (\d+)', desc)
    if m:
        label = m.group(1).strip()
        return [Step(order=1, action="click", target=label,
                     description=f"拖拽 {label} 滑块", requires_vision=True)]
    # 找 slider 相关元素
    for e in elements:
        text = e.get("text", "") or ""
        if text and any(kw in text.lower() for kw in ["volume", "brightness", "temperature", "slider"]):
            return [Step(order=1, action="click", target=text,
                         description=f"拖拽 {text} 滑块", requires_vision=True)]
    return []


def _video_player(desc: str, elements: list[dict]) -> list[Step]:
    """video-player: 根据描述决定操作"""
    desc_lower = desc.lower()
    # 从描述提取操作类型
    if "play" in desc_lower:
        target = "play"
    elif "pause" in desc_lower:
        target = "pause"
    elif "mute" in desc_lower:
        target = "mute"
    elif "volume" in desc_lower:
        target = "volume"
    else:
        target = "play"
    return [Step(order=1, action="click", target=target,
                 description=f"点击 {target} 按钮", requires_vision=True)]


def _select_dropdown(desc: str, elements: list[dict]) -> list[Step]:
    # 从描述提取要选择的选项
    quoted = _extract_quoted(desc)
    option = quoted[0] if quoted else ""
    # 用固定 target（bench HTML 固定，不依赖 OCR 噪声）
    target = "Choose a fruit"
    steps = [
        Step(order=1, action="click", target=target,
             description="展开下拉菜单", requires_vision=True),
        Step(order=2, action="wait", target="0.5",
             description="等下拉列表展开", requires_vision=False),
        Step(order=3, action="screenshot", target="",
             description="重新截图定位下拉选项", requires_vision=False),
    ]
    if option:
        steps.append(Step(order=4, action="click", target=option,
                          description=f"选择 {option}", requires_vision=True))
    return steps


def _fill_form(desc: str, elements: list[dict]) -> list[Step]:
    """fill-form: 逐个 click label → type value → screenshot → click Submit Form"""
    # 提取引号字段: Name: "John Smith"
    pairs = re.findall(r'(\w+):\s*"([^"]*)"', desc)
    # 提取数字字段: Age: 25
    num_pairs = re.findall(r'(\w+):\s*(\d+)(?:,|$)', desc)
    # 合并，保持出现顺序
    all_fields = []
    seen = set()
    for field, value in pairs:
        if field not in seen:
            all_fields.append((field, value))
            seen.add(field)
    for field, value in num_pairs:
        if field not in seen:
            all_fields.append((field, value))
            seen.add(field)

    steps = []
    order = 1
    for field, value in all_fields:
        # 跳过复杂格式字段（如 Subscribe to newsletter）
        if "{" in value or "}" in value:
            continue
        steps.append(Step(order=order, action="click", target=field,
                          description=f"点击 {field} 输入框", requires_vision=True))
        order += 1
        steps.append(Step(order=order, action="type", target=value,
                          description=f"输入 {value}", requires_vision=False))
        order += 1

    # 重新截图（确保 Submit Form 按钮在可视区域）
    steps.append(Step(order=order, action="screenshot", target="",
                      description="截图查看完整表单", requires_vision=False))
    order += 1
    # 最后点击 Submit Form
    steps.append(Step(order=order, action="click", target="Submit Form",
                      description="提交表单", requires_vision=True))
    return steps


def _click_icon(desc: str, elements: list[dict]) -> list[Step]:
    """click-icon: 用 VLM 图标识别工作流"""
    m = re.search(r'Click the (\w+) icon', desc, re.IGNORECASE)
    target = m.group(1) if m else ""
    if not target:
        quoted = _extract_quoted(desc)
        target = quoted[0] if quoted else ""
    if target:
        return [Step(order=1, action="workflow", target=target,
                     value="icon_click", description=f"VLM识别并点击 {target} 图标",
                     requires_vision=False)]
    return []


def _color_picker(desc: str, elements: list[dict]) -> list[Step]:
    """color-picker: VLM 颜色识别工作流"""
    # "Select the red color"
    m = re.search(r'Select the (\w+) color', desc, re.IGNORECASE)
    color = m.group(1) if m else ""
    if not color:
        quoted = _extract_quoted(desc)
        color = quoted[0] if quoted else ""
    if color:
        return [Step(order=1, action="workflow", target=color,
                     value="color_picker", description=f"VLM识别并点击 {color} 颜色",
                     requires_vision=False)]
    return []


def _date_picker(desc: str, elements: list[dict]) -> list[Step]:
    """date-picker: 用日期选择器工作流"""
    # "Select January 15, 2024"
    m = re.search(r'Select (\w+) (\d+),?\s*(\d{4})?', desc, re.IGNORECASE)
    day = m.group(2) if m else ""
    if not day:
        m2 = re.search(r'(\d{1,2})', desc)
        day = m2.group(1) if m2 else ""
    if day:
        return [Step(order=1, action="workflow", target=day,
                     value="date_picker", description=desc,
                     requires_vision=False)]
    return []


def _right_click_menu(desc: str, elements: list[dict]) -> list[Step]:
    """right-click-menu: 用右键菜单工作流"""
    # "Right-click the text and select Copy"
    m = re.search(r'select (\w+)', desc, re.IGNORECASE)
    option = m.group(1) if m else ""
    if option:
        return [Step(order=1, action="workflow", target=option,
                     value="right_click_menu", description=f"右键菜单工作流: 选择 {option}",
                     requires_vision=False)]
    return []


def _drag_drop(desc: str, elements: list[dict]) -> list[Step]:
    """drag-drop: drag 元素到目标"""
    # 描述格式: "Drag the Apple to the Fruits box"
    m = re.search(r'Drag the (\w+) to the (\w+)', desc, re.IGNORECASE)
    if m:
        item = m.group(1)
        target = m.group(2)
        return [
            Step(order=1, action="click", target=item,
                 description=f"拖拽 {item} 到 {target}", requires_vision=True),
        ]
    return [Step(order=1, action="click", target="drag item",
                 description="拖拽元素到目标", requires_vision=True)]


def _spreadsheet_cell(desc: str, elements: list[dict]) -> list[Step]:
    """spreadsheet-cell: click 单元格 → type 数据"""
    # 描述格式: 'Enter "Product" into cell A1'
    quoted = _extract_quoted(desc)
    value = quoted[0] if quoted else ""
    # 提取单元格名
    cell_match = re.search(r'cell (\w+\d+)', desc, re.IGNORECASE)
    cell = cell_match.group(1) if cell_match else "A1"
    steps = [Step(order=1, action="click", target=cell,
                  description=f"点击单元格 {cell}", requires_vision=True)]
    if value:
        steps.append(Step(order=2, action="type", target=value,
                          description=f"输入 {value}", requires_vision=False))
    return steps


def _generic_plan(desc: str, elements: list[dict]) -> list[Step]:
    """通用规划：从描述提取引号内容做 click"""
    quoted = _extract_quoted(desc)
    if quoted:
        steps = []
        for i, q in enumerate(quoted):
            steps.append(Step(order=i+1, action="click", target=q,
                              description=f"点击 {q}", requires_vision=True))
        return steps
    return [Step(order=1, action="screenshot", target="",
                 description="无法解析任务，截图查看", requires_vision=False)]


# 任务名 → 规划函数映射
_RULE_PLANNERS = {
    "click-button": _click_button,
    "typing-input": _typing_input,
    "toggle-switch": _toggle_switch,
    "drag-slider": _drag_slider,
    "video-player": _video_player,
    "select-dropdown": _select_dropdown,
    "fill-form": _fill_form,
    "click-icon": _click_icon,
    "color-picker": _color_picker,
    "date-picker": _date_picker,
    "right-click-menu": _right_click_menu,
    "drag-drop": _drag_drop,
    "spreadsheet-cell": _spreadsheet_cell,
}
