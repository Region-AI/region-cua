"""控件交互知识库：控件类型 → 交互策略 + planner 操作指南。

两层用途：
1. executor 查 get_strategy() 决定物理操作（单击/双击/右键/拖拽/滚动）
2. planner 查 get_planner_guide() 获得分步操作模板（如 dropdown 需要2步）

用法：
    # executor 用
    strategy = get_strategy("submit", "button")
    # → {"action": "click", "button": "left", "clicks": 1}

    # planner 用（注入 system prompt）
    guide = get_planner_guide("dropdown")
    # → "步骤1: click 下拉框展开选项列表\\n步骤2: wait 0.5秒等列表渲染\\n步骤3: click 目标选项"
"""

from __future__ import annotations

import re
from typing import Optional


# ================================================================
# 控件类型 → 交互策略（executor 用）
# ================================================================
CONTROL_STRATEGIES: dict[str, dict] = {
    # --- 按钮/提交类 ---
    "button": {
        "action": "click", "button": "left", "clicks": 1,
        "notes": "单击触发。",
    },
    "submit": {
        "action": "click", "button": "left", "clicks": 1,
        "notes": "提交按钮，点击后等待页面响应。不要重复点击。",
    },
    "cancel": {
        "action": "click", "button": "left", "clicks": 1,
        "notes": "取消按钮，点击后关闭对话框或表单。",
    },

    # --- 输入类 ---
    "input": {
        "action": "click_then_type", "button": "left", "clicks": 1,
        "notes": "先单击聚焦，再输入文字。输入前确保英文输入法。",
    },
    "textarea": {
        "action": "click_then_type", "button": "left", "clicks": 1,
        "notes": "文本区域，先单击聚焦，再输入多行文字。",
    },
    "search": {
        "action": "click_type_enter", "button": "left", "clicks": 1,
        "notes": "搜索框：单击聚焦 → 输入关键词 → 按 Enter。",
    },

    # --- 选择类（需要多步） ---
    "dropdown": {
        "action": "click_then_click", "button": "left", "clicks": 1,
        "notes": "下拉菜单：需要两步操作。",
    },
    "select": {
        "action": "click_then_click", "button": "left", "clicks": 1,
        "notes": "选择框：需要两步操作。",
    },
    "checkbox": {
        "action": "click", "button": "left", "clicks": 1,
        "notes": "复选框：单击切换勾选状态。",
    },
    "radio": {
        "action": "click", "button": "left", "clicks": 1,
        "notes": "单选按钮：单击选中。同组只能选一个。",
    },

    # --- 开关/滑块类 ---
    "toggle": {
        "action": "click", "button": "left", "clicks": 1,
        "notes": "开关：单击切换开/关。",
    },
    "switch": {
        "action": "click", "button": "left", "clicks": 1,
        "notes": "开关控件：单击切换状态。",
    },
    "slider": {
        "action": "drag", "button": "left", "clicks": 1,
        "notes": "滑块：需要拖拽。方向和距离取决于目标值。",
    },

    # --- 拖拽类 ---
    "drag": {
        "action": "drag", "button": "left", "clicks": 1,
        "notes": "可拖拽元素：按住左键从当前位置拖到目标位置。",
    },

    # --- 菜单类 ---
    "menu": {
        "action": "click", "button": "left", "clicks": 1,
        "notes": "菜单项：单击触发。",
    },
    "context_menu": {
        "action": "right_click", "button": "right", "clicks": 1,
        "notes": "右键菜单：先右键单击展开，再左键单击选项。",
    },

    # --- 链接/表格 ---
    "link": {
        "action": "click", "button": "left", "clicks": 1,
        "notes": "超链接：单击跳转。",
    },
    "cell": {
        "action": "click_then_type", "button": "left", "clicks": 1,
        "notes": "表格单元格：先单击选中，再输入数据。",
    },

    # --- 日期/颜色选择器 ---
    "date_picker": {
        "action": "click_then_click", "button": "left", "clicks": 1,
        "notes": "日期选择器：需要导航到正确月份再选日期。",
    },
    "color_picker": {
        "action": "click", "button": "left", "clicks": 1,
        "notes": "颜色选择器：单击目标颜色。",
    },

    # --- 视频播放器 ---
    "video_play": {
        "action": "click", "button": "left", "clicks": 1,
        "notes": "播放/暂停按钮：单击切换播放状态。",
    },
    "video_pause": {
        "action": "click", "button": "left", "clicks": 1,
        "notes": "暂停按钮：单击暂停。",
    },
    "video_mute": {
        "action": "click", "button": "left", "clicks": 1,
        "notes": "静音按钮：单击切换静音。",
    },
    "video_volume": {
        "action": "click", "button": "left", "clicks": 1,
        "notes": "音量按钮：单击切换静音，或悬停展开音量滑块。",
    },

    # --- 滚动条 ---
    "scrollbar": {
        "action": "scroll", "button": "left", "clicks": 0,
        "notes": "滚动条：用 scroll 动作滚动页面内容。",
    },

    # --- 通用 ---
    "unknown": {
        "action": "click", "button": "left", "clicks": 1,
        "notes": "未知控件类型，尝试单击。",
    },
}


# ================================================================
# 控件类型 → planner 分步操作指南
# ================================================================
# 每种控件类型的完整操作流程，planner 读取后生成对应步骤
PLANNER_GUIDES: dict[str, str] = {
    "button": (
        "【按钮】单击即可。生成1步：click 按钮文字。"
    ),
    "submit": (
        "【提交按钮】单击提交。生成1步：click 'Submit'（或对应文字）。"
        "点击后等页面响应，不要重复点击。"
    ),
    "input": (
        "【输入框】需要2步：\n"
        "  步骤1: click 输入框的 label 文字（如 'Username'）\n"
        "  步骤2: type 要输入的内容\n"
        "注意：输入英文前确保英文输入法。"
    ),
    "textarea": (
        "【文本区域】需要2步：\n"
        "  步骤1: click 文本区域的 label 文字\n"
        "  步骤2: type 要输入的内容"
    ),
    "search": (
        "【搜索框】需要3步：\n"
        "  步骤1: click 'Search' 或搜索框\n"
        "  步骤2: type 搜索关键词\n"
        "  步骤3: hotkey 'enter'"
    ),
    "dropdown": (
        "【下拉菜单】需要3步：\n"
        "  步骤1: click 下拉框本身（不是选项文字，是下拉框控件）\n"
        "  步骤2: wait 0.5（等下拉列表展开渲染）\n"
        "  步骤3: click 要选择的选项文字\n"
        "注意：必须先展开再选，不能直接点击选项。"
    ),
    "select": (
        "【选择框】需要3步：\n"
        "  步骤1: click 选择框控件\n"
        "  步骤2: wait 0.5（等选项列表展开）\n"
        "  步骤3: click 要选择的选项文字"
    ),
    "checkbox": (
        "【复选框】单击切换。生成1步：click 复选框的 label 文字。"
    ),
    "radio": (
        "【单选按钮】单击选中。生成1步：click 选项的 label 文字。"
    ),
    "toggle": (
        "【开关】单击切换。生成1步：click 开关旁边的 label 文字或开关本身。"
    ),
    "switch": (
        "【开关控件】单击切换。生成1步：click 开关的 label 文字。"
    ),
    "slider": (
        "【滑块】需要拖拽。生成1步：click 滑块控件。\n"
        "注意：executor 会自动处理拖拽。如果目标值比当前值大，向右拖；\n"
        "如果比当前值小，向左拖。拖拽距离根据差值比例估算。"
    ),
    "drag": (
        "【拖拽元素】需要拖拽。生成1步：click 要拖拽的元素。\n"
        "注意：executor 会自动从当前位置拖到目标位置。"
    ),
    "date_picker": (
        "【日期选择器】需要3-5步：\n"
        "  步骤1: click 日期输入框（展开日历）\n"
        "  步骤2: wait 0.5（等日历渲染）\n"
        "  步骤3: 如果目标月份不是当前月，click 日历上的 '‹' 或 '›' 按钮翻月\n"
        "         （可能需要多次翻月，每次 click 后 wait 0.3）\n"
        "  步骤4: click 日历中目标日期的数字（如 '15'）\n"
        "注意：先看截图中日历显示的是哪个月，再决定翻月方向和次数。"
    ),
    "color_picker": (
        "【颜色选择器】生成1步：click 目标颜色区域。\n"
        "注意：颜色可能没有文字标签，根据位置描述定位（如'左上角的红色方块'）。"
    ),
    "context_menu": (
        "【右键菜单】需要3步：\n"
        "  步骤1: 右键单击目标区域（用 click，value='right'）\n"
        "  步骤2: wait 0.5（等右键菜单展开）\n"
        "  步骤3: click 菜单中的目标选项文字"
    ),
    "cell": (
        "【表格单元格】需要2步：\n"
        "  步骤1: click 单元格位置（如 'A1' 或具体坐标）\n"
        "  步骤2: type 要输入的数据"
    ),
    "video_play": (
        "【播放/暂停按钮】单击切换。生成1步：click 'Play/Pause' 按钮。"
    ),
    "video_mute": (
        "【静音按钮】单击切换。生成1步：click 'Volume' 或静音按钮。"
    ),
    "video_volume": (
        "【音量控制】可能需要2步：\n"
        "  步骤1: click 音量按钮（展开音量滑块）或悬停\n"
        "  步骤2: click 或拖拽音量滑块到目标位置\n"
        "注意：有些播放器单击音量按钮直接切换静音。"
    ),
    "scrollbar": (
        "【滚动条】当页面内容显示不完整时：\n"
        "  生成1步：scroll 方向和量（正数向上/负数向下）\n"
        "注意：如果目标元素不在可视区域，先滚动再操作。"
    ),
    "link": (
        "【超链接】单击跳转。生成1步：click 链接文字。"
    ),
    "menu": (
        "【菜单项】单击触发。生成1步：click 菜单项文字。"
    ),
}


# ================================================================
# 文字关键词 → 控件类型推断
# ================================================================
TEXT_TO_TYPE: dict[str, str] = {
    # 按钮
    "submit": "submit", "提交": "submit",
    "cancel": "cancel", "取消": "cancel",
    "ok": "button", "确定": "button", "确认": "button",
    "save": "button", "保存": "button",
    "delete": "button", "删除": "button",
    "close": "button", "关闭": "button",
    "start": "button", "开始": "button",
    "stop": "button", "停止": "button",
    "continue": "button", "继续": "button",
    "next": "button", "下一步": "button",
    "back": "button", "返回": "button",
    # 播放控制
    "play": "video_play", "播放": "video_play",
    "play/pause": "video_play",
    "pause": "video_pause", "暂停": "video_pause",
    "mute": "video_mute", "静音": "video_mute",
    "volume": "video_volume", "音量": "video_volume",
    # 搜索
    "search": "search", "搜索": "search",
    # 开关
    "toggle": "toggle", "switch": "switch", "开关": "toggle",
    # 下拉
    "dropdown": "dropdown", "下拉": "dropdown",
    "select": "select", "选择": "select",
    # 滑块
    "slider": "slider", "滑块": "slider",
    # 日期
    "date": "date_picker", "日期": "date_picker",
    # 颜色
    "color": "color_picker", "颜色": "color_picker",
    # 滚动
    "scroll": "scrollbar", "滚动": "scrollbar",
}


def infer_control_type(text: str, element_type: str = "") -> str:
    """根据元素文字和已有类型推断控件类型。"""
    text_lower = text.lower().strip()

    # 1. 精确文字匹配
    if text_lower in TEXT_TO_TYPE:
        return TEXT_TO_TYPE[text_lower]

    # 2. 中文匹配
    cn_map = {
        "提交": "submit", "取消": "cancel", "搜索": "search",
        "播放": "video_play", "暂停": "video_pause", "静音": "video_mute",
        "音量": "video_volume", "开关": "toggle", "滑块": "slider",
        "下拉": "dropdown", "日期": "date_picker", "颜色": "color_picker",
        "滚动": "scrollbar",
    }
    for cn, ctype in cn_map.items():
        if cn in text:
            return ctype

    # 3. 模糊英文匹配
    fuzzy_map = [
        (r"submit", "submit"),
        (r"cancel", "cancel"),
        (r"search", "search"),
        (r"play.*pause|play/pause", "video_play"),
        (r"play", "video_play"),
        (r"pause", "video_pause"),
        (r"mute|volume", "video_mute"),
        (r"dropdown|drop-down", "dropdown"),
        (r"slider", "slider"),
        (r"date.*pick|calendar", "date_picker"),
        (r"color.*pick", "color_picker"),
        (r"scroll", "scrollbar"),
        (r"checkbox|check.*box", "checkbox"),
        (r"radio", "radio"),
        (r"toggle|switch", "toggle"),
    ]
    for pattern, ctype in fuzzy_map:
        if re.search(pattern, text_lower):
            return ctype

    # 4. 如果已有类型是 button，默认返回 button
    if element_type == "button":
        return "button"

    return element_type or "unknown"


def get_strategy(text: str, element_type: str = "") -> dict:
    """获取控件的交互策略（executor 用）。"""
    ctype = infer_control_type(text, element_type)
    strategy = CONTROL_STRATEGIES.get(ctype, CONTROL_STRATEGIES["unknown"]).copy()
    strategy["control_type"] = ctype
    return strategy


def get_planner_guide(control_type: str) -> str:
    """获取控件类型的 planner 操作指南。"""
    return PLANNER_GUIDES.get(control_type, PLANNER_GUIDES.get("button", ""))


def build_planner_kb_prompt() -> str:
    """构建完整的控件知识库提示词，注入 planner 的 system prompt。

    从 skill 文件 references/control-kb.md 加载，修改文件不需要改代码。
    """
    import os
    from pathlib import Path

    # 查找 control-kb.md 文件（多级向上搜索）
    candidates = [
        # 1. 环境变量指定
        Path(os.environ.get("REGIONCUA_CONTROL_KB", "")) if os.environ.get("REGIONCUA_CONTROL_KB") else None,
        # 2. skills/region-cua/references/control-kb.md
        Path(__file__).resolve().parents[3] / "skills" / "region-cua" / "references" / "control-kb.md",
        # 3. 项目根目录下
        Path(__file__).resolve().parents[3] / "control-kb.md",
        # 4. skills 目录下
        Path(__file__).resolve().parents[3] / "skills" / "control-kb.md",
    ]

    for candidate in candidates:
        if candidate and candidate.exists():
            try:
                content = candidate.read_text(encoding="utf-8")
                return f"## 控件交互知识库\n（来源: {candidate.name}，修改该文件可更新知识库）\n\n{content}"
            except Exception:
                pass

    # 文件没找到 → 用内置的精简版兜底
    return _builtin_kb_fallback()


def _builtin_kb_fallback() -> str:
    """内置精简知识库兜底（当外部文件不存在时用）。"""
    return """## 控件交互知识库

### 通用规则
- click 的 target 必须是页面上实际显示的文字
- type 的 target 必须是要输入的具体文字内容，不能为空
- 下拉菜单需要3步：click 下拉框 → wait 0.5 → click 选项
- 输入框需要2步：click label → type 内容
- 滑块需要拖拽：click 滑块
- 日期选择器：click 展开 → 翻月(‹›) → click 日期
- 右键菜单：右键 click → wait → click 选项
- 内容不完整时先 scroll 滚动
"""
