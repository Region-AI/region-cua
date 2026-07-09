"""复杂控件工作流：预定义操作序列，不依赖 planner 规划。

每个工作流是一个函数，接收 executor 上下文（截图能力、点击能力等），
直接执行多步操作，返回操作结果。

工作流在 rule_planner 里通过 action="workflow" 触发，
executor 检测到 workflow action 时调用对应的工作流函数。
"""

from __future__ import annotations

import time
from typing import Optional


def _move_cursor_away(inp_module) -> None:
    """截图前把光标移到屏幕右下角，避免遮挡界面元素。"""
    try:
        from ..vision.screenshot import screen_size
        w, h = screen_size()
        inp_module.move_to(w - 5, h - 5)
    except Exception:
        pass


def workflow_right_click_menu(executor, step) -> str:
    """右键菜单工作流：右键点击 → 等待 → 重新截图 → 找菜单项 → 点击。

    网页自定义右键菜单是 DOM 元素，OmniParser 能检测到。
    但浏览器原生右键菜单可能遮挡，所以需要先关闭原生菜单。
    """
    from ..automation import input as inp

    # 1. 激活窗口
    if executor.window_keyword:
        executor._activate_target_window()
        time.sleep(0.5)

    # 2. 截图定位右键目标区域
    _move_cursor_away(inp)
    before = executor._capture("workflow_rc_before")
    coords, analysis = executor._locate(before, step.target or "Right-click here")
    if not coords:
        # 兜底：点击页面中心
        from ..vision.screenshot import screen_size
        w, h = screen_size()
        coords = (w // 2, h // 2)

    # 3. 右键点击
    inp.click_at(coords[0], coords[1], button="right")
    time.sleep(0.5)

    # 4. 按 Escape 关闭浏览器原生菜单（网页自定义菜单用 JS 阻止了默认行为）
    # 但如果网页没阻止，原生菜单会遮挡。按 Escape 关闭它。
    # 注意：这也会关闭网页菜单，所以只在原生菜单弹出时才需要
    # 更好的方法：先左键点击空白处取消原生菜单，然后网页菜单可能还在
    # 最简单：直接重新截图看有没有菜单项

    # 5. 重新截图
    after = executor._capture("workflow_rc_after")
    time.sleep(0.3)

    # 6. 在新截图中找菜单项
    menu_item = step.target or "Copy"
    coords2, analysis2 = executor._locate(after, menu_item)
    if coords2:
        inp.click_at(coords2[0], coords2[1])
        return f"右键菜单：点击了 {menu_item} at {coords2}"

    # 7. 如果找不到菜单项，可能是原生菜单遮挡了，尝试用键盘
    # 常见右键菜单选项的键盘快捷键
    keyboard_map = {
        "copy": "c", "复制": "c",
        "paste": "v", "粘贴": "v",
        "cut": "x", "剪切": "x",
        "delete": "d", "删除": "d",
        "select_all": "a", "全选": "a",
    }
    key = keyboard_map.get(menu_item.lower(), "")
    if key:
        # 先 Escape 关闭原生菜单，再用 JS 重新打开网页菜单
        inp.press_key("escape")
        time.sleep(0.3)
        # 重新右键点击
        inp.click_at(coords[0], coords[1], button="right")
        time.sleep(0.5)
        # 用键盘选择
        inp.press_key(key)
        time.sleep(0.2)
        inp.press_key("enter")
        return f"右键菜单：用键盘选择了 {menu_item}（按 {key} + Enter）"

    return f"右键菜单：未找到 {menu_item}"


def workflow_date_picker(executor, step) -> str:
    """日期选择器工作流：分步选择年→月→日。

    1. click输入框 + Alt+Down 弹出日历
    2. 重新截图
    3. click顶部年月区域 → 切换到年月选择视图
    4. 重新截图 → 找目标年份（可能需要滚动）→ click
    5. 重新截图 → 找目标月份 → click
    6. 重新截图 → 找目标日期数字 → click
    每步都重新截图，根据实际弹出的界面操作。
    """
    from ..automation import input as inp

    # 解析目标日期
    import re as _re
    desc = step.description or ""
    month_map = {
        "january": "1", "february": "2", "march": "3", "april": "4",
        "may": "5", "june": "6", "july": "7", "august": "8",
        "september": "9", "october": "10", "november": "11", "december": "12",
    }
    m = _re.search(r'Select (\w+) (\d+),?\s*(\d{4})?', desc, _re.IGNORECASE)
    if m:
        month_name = m.group(1).lower()
        target_day = m.group(2)
        target_year = m.group(3) or "2024"
        target_month = month_map.get(month_name, "1")
    else:
        target_day = step.target or ""
        target_year = "2024"
        target_month = "1"

    # 辅助：截图+解析+定位+点击
    _dp_step_counter = [0]
    def _find_and_click(target_text, must_contain=None, exclude_texts=None, y_range=None):
        """截图->OmniParser解析->找匹配元素->点击。返回是否成功。

        y_range: (y_min, y_max) 限制搜索的 y 坐标范围。
        """
        _move_cursor_away(inp)
        _dp_step_counter[0] += 1
        shot_path = executor._capture(f"workflow_dp_s{_dp_step_counter[0]}")
        try:
            if not hasattr(executor, "_omniparser") or executor._omniparser is None:
                from ..vision.omniparser import OmniParser
                executor._omniparser = OmniParser(enable_vlm_icons=False)
            elements = executor._omniparser.parse(shot_path)
            exclude_texts = exclude_texts or []
            # 精确匹配
            for e in elements:
                text = (e.get("text") or "").strip()
                if text == target_text and text not in exclude_texts:
                    cx, cy = e["center"]
                    if y_range and not (y_range[0] <= cy <= y_range[1]):
                        continue
                    inp.click_at(cx, cy)
                    time.sleep(0.8)
                    return True
            # 模糊匹配
            best = None
            best_score = 0
            for e in elements:
                text = (e.get("text") or "").strip()
                if not text or text in exclude_texts:
                    continue
                if must_contain and must_contain not in text:
                    continue
                cx, cy = e["center"]
                if y_range and not (y_range[0] <= cy <= y_range[1]):
                    continue
                # 包含匹配
                if target_text in text:
                    score = len(target_text) / max(len(text), 1)
                    if score > best_score:
                        best_score = score
                        best = e
            if best and best_score > 0.3:
                cx, cy = best["center"]
                inp.click_at(cx, cy)
                time.sleep(0.8)
                return True
        except Exception as exc:
            executor.logger.info(f"日期选择器定位失败: {exc}")
        return False

    # 1. 激活窗口 + 截图定位日期输入框
    if executor.window_keyword:
        executor._activate_target_window()
        time.sleep(0.5)

    _move_cursor_away(inp)
    before = executor._capture("workflow_dp_before")
    coords, analysis = executor._locate(before, "Choose Date")
    if not coords:
        coords, analysis = executor._locate(before, "date")
    if not coords:
        return "日期选择器：未找到日期输入框"

    # 2. 点击输入框 + Alt+Down 弹出日历
    inp.click_at(coords[0], coords[1])
    time.sleep(0.5)
    inp.press_hotkey("alt+down")
    time.sleep(1.0)

    # 3. 重新截图，点击顶部的年月区域切换到年月选择视图
    _move_cursor_away(inp)
    cal_shot = executor._capture("workflow_dp_calendar")
    # 找顶部年月文字（如 "2026年07月" 或 "July 2026"）
    try:
        if not hasattr(executor, "_omniparser") or executor._omniparser is None:
            from ..vision.omniparser import OmniParser
            executor._omniparser = OmniParser(enable_vlm_icons=False)
        cal_elements = executor._omniparser.parse(cal_shot)
        # 找年月显示区域（含数字+年/月 或 月份英文+年份）
        year_month_clicked = False
        for e in cal_elements:
            text = (e.get("text") or "").strip()
            # 匹配 "2026年07月" 或 "July 2026" 等
            if (len(text) > 4 and len(text) < 20
                    and any(y in text for y in ["2024", "2025", "2026", "2027"])
                    and e.get("center", (0, 0))[1] < 350):
                cx, cy = e["center"]
                inp.click_at(cx, cy)
                time.sleep(0.8)
                year_month_clicked = True
                executor.logger.info(f"点击年月区域: {text} at ({cx},{cy})")
                break
        if not year_month_clicked:
            # 兜底：点击日历顶部中心
            from ..vision.screenshot import screen_size
            sw, sh = screen_size()
            inp.click_at(coords[0] + 50, coords[1] + 30)
            time.sleep(0.8)
    except Exception as exc:
        executor.logger.info(f"年月区域定位失败: {exc}")

    # 4. 重新截图，找目标年份（可能需要滚动）
    # 年月选择视图可能显示多个年份，需要滚动找到目标年份
    for _scroll_try in range(5):
        if _find_and_click(target_year):
            executor.logger.info(f"找到并点击年份: {target_year}")
            break
        # 没找到，滚动
        inp.scroll(-5)
        time.sleep(0.5)
    else:
        executor.logger.info(f"未找到目标年份: {target_year}")

    # 5. 重新截图，找目标月份
    # 月份可能是英文（January）或数字（1月），优先用长名匹配
    month_names = {
        "1": ["January", "Jan", "1月", "1"],
        "2": ["February", "Feb", "2月", "2"],
        "3": ["March", "Mar", "3月", "3"],
        "4": ["April", "Apr", "4月", "4"],
        "5": ["May", "5月", "5"],
        "6": ["June", "Jun", "6月", "6"],
        "7": ["July", "Jul", "7月", "7"],
        "8": ["August", "Aug", "8月", "8"],
        "9": ["September", "Sep", "9月", "9"],
        "10": ["October", "Oct", "10月", "10"],
        "11": ["November", "Nov", "11月", "11"],
        "12": ["December", "Dec", "12月", "12"],
    }
    month_found = False
    for month_text in month_names.get(target_month, [target_month]):
        # 排除年份文字，限制在日历区域内查找
        if _find_and_click(month_text,
                           exclude_texts=[target_year, "2024", "2025", "2026", "2027"],
                           y_range=(200, 500)):
            executor.logger.info(f"找到并点击月份: {month_text}")
            month_found = True
            break
    if not month_found:
        executor.logger.info(f"未找到目标月份: {target_month}")

    # 6. 重新截图，找目标日期数字
    day_int = int(target_day) if target_day.isdigit() else None
    if day_int:
        if _find_and_click(target_day):
            executor.logger.info(f"找到并点击日期: {target_day}")
            return f"日期选择器：选择 {target_year}-{target_month}-{target_day}"

    return f"日期选择器：选择 {target_year}-{target_month}-{target_day}（部分步骤可能失败）"


def workflow_icon_click(executor, step) -> str:
    """图标点击工作流：截图 → VLM 批量识别图标 → 匹配 → click。

    纯图标按钮没有文字，需要 VLM 识别图标含义。
    """
    from ..automation import input as inp

    # 1. 激活窗口 + 截图
    if executor.window_keyword:
        executor._activate_target_window()
        time.sleep(0.5)

    before = executor._capture("workflow_icon_before")

    # 2. 用启用 VLM 的 OmniParser 解析
    try:
        from ..vision.omniparser import OmniParser
        parser = OmniParser(box_threshold=0.01, enable_vlm_icons=True)
        elements = parser.parse(before)
    except Exception:
        parser = executor._omniparser or OmniParser()
        elements = parser.parse(before)

    # 3. 找匹配的图标
    target = step.target or ""
    elem = parser.find_element(elements, target, before)
    if elem:
        cx, cy = elem["center"]
        inp.click_at(cx, cy)
        return f"图标点击：找到 {target} at ({cx},{cy})"

    return f"图标点击：未找到 {target}"


def workflow_color_picker(executor, step) -> str:
    """颜色选择器工作流：截图 → VLM 识别颜色方块 → click。

    颜色方块没有文字，需要 VLM 识别颜色。
    """
    from ..automation import input as inp

    # 1. 激活窗口 + 截图
    if executor.window_keyword:
        executor._activate_target_window()
        time.sleep(0.5)

    before = executor._capture("workflow_color_before")

    # 2. 用 VLM 直接问"红色方块在哪里"
    try:
        from ..vision.ollama_client import OllamaClient
        from ..config import get_settings
        import base64 as _b64
        settings = get_settings()
        client = OllamaClient(settings.ollama_host, settings.ollama_timeout)

        color = step.target or "red"
        prompt = (
            f"这张截图中有一个颜色选择器，请找到「{color}」颜色方块的位置。"
            f"返回 JSON：{{\"found\": true, \"x\": 整数, \"y\": 整数}}\n"
            f"坐标基于截图左上角。只输出 JSON。"
        )

        # 读取截图文件
        with open(before, "rb") as f:
            img_bytes = f.read()

        resp = client.chat(
            "qwen3.5:latest",
            [{"role": "user", "content": prompt}],
            images=[img_bytes],
        )
        client.close()

        # 解析坐标
        import re
        import json
        match = re.search(r'\{[^}]+\}', resp)
        if match:
            data = json.loads(match.group(0))
            if data.get("found") and data.get("x") and data.get("y"):
                x, y = int(data["x"]), int(data["y"])
                inp.click_at(x, y)
                return f"颜色选择器：VLM 定位 {color} at ({x},{y})"
    except Exception:
        pass

    # 3. 兜底：用 OmniParser 找无文字的彩色元素
    try:
        from ..vision.omniparser import OmniParser
        parser = executor._omniparser or OmniParser(box_threshold=0.01)
        elements = parser.parse(before)
        # 找无文字的图标元素（颜色方块）
        for e in elements:
            if not e.get("text") and e.get("center", (0, 0))[1] > 120:
                cx, cy = e["center"]
                inp.click_at(cx, cy)
                return f"颜色选择器：兜底点击第一个无文字元素 at ({cx},{cy})"
    except Exception:
        pass

    return f"颜色选择器：未找到 {step.target}"


# 工作流注册表
WORKFLOWS = {
    "right_click_menu": workflow_right_click_menu,
    "date_picker": workflow_date_picker,
    "icon_click": workflow_icon_click,
    "color_picker": workflow_color_picker,
}


def run_workflow(name: str, executor, step) -> str:
    """执行指定的工作流。

    Args:
        name: 工作流名称
        executor: TaskExecutor 实例
        step: 当前步骤

    Returns:
        执行结果描述
    """
    wf = WORKFLOWS.get(name)
    if wf:
        return wf(executor, step)
    return f"未知工作流: {name}"
