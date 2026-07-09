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

    # 4. 重新截图，找目标年份（年月选择视图中年份列表可能需要滚动）
    # Chrome 年月视图：年份列表右侧有滚动条，但太细 OmniParser 检测不到
    # 用键盘上下箭头键滚动年份列表（年月视图支持键盘导航）
    year_found = False

    # 先尝试当前视图
    if _find_and_click(target_year, y_range=(250, 600)):
        year_found = True
        executor.logger.info(f"找到并点击年份: {target_year}")

    # 当前视图没找到，用布局分析判断滚动方向，然后用键盘滚动
    if not year_found:
        _move_cursor_away(inp)
        ym_shot = executor._capture("workflow_dp_year_list")
        try:
            if not hasattr(executor, "_omniparser") or executor._omniparser is None:
                from ..vision.omniparser import OmniParser
                executor._omniparser = OmniParser(enable_vlm_icons=False)
            ym_elements = executor._omniparser.parse(ym_shot)

            # 看可见年份判断滚动方向
            visible_years = []
            for e in ym_elements:
                text = (e.get("text") or "").strip()
                if text.isdigit() and 2000 < int(text) < 2100:
                    visible_years.append(int(text))
                    cx, cy = e["center"]
                    visible_years.append((int(text), cx, cy))

            if visible_years:
                # 提取纯年份
                year_values = [y for y in visible_years if isinstance(y, int)]
                min_visible = min(year_values) if year_values else 2026
                target_y = int(target_year)

                # 判断方向
                if target_y < min_visible:
                    direction = "up"
                    executor.logger.info(f"目标年份 {target_year} < 最小可见 {min_visible}，向上滚动")
                else:
                    direction = "down"
                    executor.logger.info(f"目标年份 {target_year} > 最大可见 {max(year_values)}，向下滚动")

                # 用键盘箭头键滚动（年月视图支持键盘导航）
                # 先点击年份列表区域确保焦点在列表上
                for yv in visible_years:
                    if isinstance(yv, tuple):
                        _, cx, cy = yv
                        inp.click_at(cx, cy)
                        time.sleep(0.3)
                        break

                key = "up" if direction == "up" else "down"
                for _ in range(30):  # 最多按 30 次箭头键
                    inp.press_key(key)
                    time.sleep(0.15)
                    if _find_and_click(target_year, y_range=(250, 600)):
                        year_found = True
                        executor.logger.info(f"键盘滚动找到年份: {target_year}")
                        break
        except Exception as exc:
            executor.logger.info(f"布局分析年份列表失败: {exc}")

    # 兜底：盲滚（鼠标滚轮 + 键盘箭头）
    if not year_found:
        for method in ["keyboard_up", "keyboard_down", "scroll_up", "scroll_down"]:
            if "keyboard" in method:
                key = "up" if "up" in method else "down"
                for _ in range(10):
                    inp.press_key(key)
                    time.sleep(0.15)
                    if _find_and_click(target_year, y_range=(250, 600)):
                        year_found = True
                        executor.logger.info(f"兜底键盘找到年份: {target_year}")
                        break
            else:
                direction = 5 if "up" in method else -5
                for _ in range(5):
                    inp.scroll(direction)
                    time.sleep(0.3)
                    if _find_and_click(target_year, y_range=(250, 600)):
                        year_found = True
                        executor.logger.info(f"兜底滚轮找到年份: {target_year}")
                        break
            if year_found:
                break
    if not year_found:
        executor.logger.info(f"未找到目标年份: {target_year}")

    # 5. 选完年份后会回到月历视图，需要重新点击年月区域展开月份选择
    if year_found:
        _move_cursor_away(inp)
        ym_shot = executor._capture("workflow_dp_after_year")
        try:
            if not hasattr(executor, "_omniparser") or executor._omniparser is None:
                from ..vision.omniparser import OmniParser
                executor._omniparser = OmniParser(enable_vlm_icons=False)
            ym_elements = executor._omniparser.parse(ym_shot)
            for e in ym_elements:
                text = (e.get("text") or "").strip()
                # 找年月显示区域（如 "2024年01月" 或含目标年份的文字）
                if (len(text) > 4 and len(text) < 20
                        and target_year in text
                        and e.get("center", (0, 0))[1] < 350):
                    cx, cy = e["center"]
                    inp.click_at(cx, cy)
                    time.sleep(0.8)
                    executor.logger.info(f"选完年份后重新点击年月区域: {text}")
                    break
        except Exception:
            pass

    # 6. 重新截图，找目标月份（年月视图中月份是网格按钮）
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

    # 7. 重新截图，找目标日期数字
    day_int = int(target_day) if target_day.isdigit() else None
    if day_int:
        if _find_and_click(target_day):
            executor.logger.info(f"找到并点击日期: {target_day}")
            return f"日期选择器：选择 {target_year}-{target_month}-{target_day}"

    return f"日期选择器：选择 {target_year}-{target_month}-{target_day}（部分步骤可能失败）"


def workflow_icon_click(executor, step) -> str:
    """图标点击工作流：截图 → OmniParser+SAM3 检测 → VLM 识别 → click。

    纯图标按钮没有文字，需要 VLM 识别图标含义。
    SAM3 用 "icon" 提示补充检测 OmniParser 漏检的图标。
    """
    from ..automation import input as inp

    # 1. 激活窗口 + 截图
    if executor.window_keyword:
        executor._activate_target_window()
        time.sleep(0.5)

    before = executor._capture("workflow_icon_before")

    # 2. 先用 OmniParser（启用 VLM 图标识别）解析
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

    # 4. OmniParser 没找到，用 SAM3 检测 icon 区域
    try:
        from ..vision.sam3_analyzer import SAM3Analyzer
        analyzer = SAM3Analyzer()
        sam3_results = analyzer.segment(before, "icon", threshold=0.3)
        if sam3_results:
            # 用 VLM 识别每个 SAM3 检测到的 icon 区域
            executor.logger.info(f"SAM3 检测到 {len(sam3_results)} 个 icon")
            # 裁剪每个 icon 区域，用 VLM 识别
            from PIL import Image as _Img
            img = _Img.open(before).convert("RGB")
            from ..vision.ollama_client import OllamaClient
            from ..config import get_settings
            settings = get_settings()
            client = OllamaClient(settings.ollama_host, settings.ollama_timeout)
            for r in sam3_results:
                x1, y1, x2, y2 = r["box"]
                # 裁剪 icon 区域（扩大一点边界）
                crop = img.crop((max(0, x1-5), max(0, y1-5), x2+5, y2+5))
                import io as _io
                buf = _io.BytesIO()
                crop.save(buf, format="PNG")
                resp = client.chat(
                    settings.ollama_vision_model,
                    [{"role": "user", "content": f"这个图标是什么？用一个英文单词回答（如 home, settings, play, pause, search）。如果是 {target} 图标，回答 YES。"}],
                    images=[buf.getvalue()],
                )
                if target.lower() in resp.lower() or "yes" in resp.lower():
                    cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
                    inp.click_at(cx, cy)
                    client.close()
                    return f"图标点击：SAM3+VLM 找到 {target} at ({cx},{cy}) score={r['score']:.2f}"
            client.close()
    except Exception as exc:
        executor.logger.info(f"SAM3 图标检测失败: {exc}")

    return f"图标点击：未找到 {target}"


def workflow_color_picker(executor, step) -> str:
    """颜色选择器工作流：截图 → VLM 识别颜色方块 → click。

    颜色方块没有文字，用 VLM 直接识别颜色位置。
    SAM3 用 "rectangle" 提示补充检测颜色方块区域。
    """
    from ..automation import input as inp

    # 1. 激活窗口 + 截图
    if executor.window_keyword:
        executor._activate_target_window()
        time.sleep(0.5)

    before = executor._capture("workflow_color_before")
    color = step.target or "red"

    # 2. 用 VLM 直接问"颜色方块在哪里"
    try:
        from ..vision.ollama_client import OllamaClient
        from ..config import get_settings
        settings = get_settings()
        client = OllamaClient(settings.ollama_host, settings.ollama_timeout)

        prompt = (
            f"这张截图中有一个颜色选择器，请找到「{color}」颜色方块的位置。"
            f"返回 JSON：{{\"found\": true, \"x\": 整数, \"y\": 整数}}\n"
            f"坐标基于截图左上角。只输出 JSON。"
        )

        with open(before, "rb") as f:
            img_bytes = f.read()

        resp = client.chat(
            settings.ollama_vision_model,
            [{"role": "user", "content": prompt}],
            images=[img_bytes],
        )
        client.close()

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

    # 3. VLM 没找到，用 SAM3 检测 rectangle 区域（颜色方块）
    try:
        from ..vision.sam3_analyzer import SAM3Analyzer
        analyzer = SAM3Analyzer()
        sam3_results = analyzer.segment(before, "rectangle", threshold=0.3)
        if sam3_results:
            executor.logger.info(f"SAM3 检测到 {len(sam3_results)} 个 rectangle")
            # 用 VLM 识别每个 rectangle 是否是目标颜色
            from PIL import Image as _Img
            img = _Img.open(before).convert("RGB")
            from ..vision.ollama_client import OllamaClient
            from ..config import get_settings
            settings = get_settings()
            client = OllamaClient(settings.ollama_host, settings.ollama_timeout)
            for r in sam3_results:
                x1, y1, x2, y2 = r["box"]
                # 只看面积适中的方块（排除太大或太小的）
                w, h = x2 - x1, y2 - y1
                if w < 10 or h < 10 or w > 200 or h > 200:
                    continue
                crop = img.crop((x1, y1, x2, y2))
                import io as _io
                buf = _io.BytesIO()
                crop.save(buf, format="PNG")
                resp = client.chat(
                    settings.ollama_vision_model,
                    [{"role": "user", "content": f"这个方块是什么颜色？如果是 {color}，回答 YES。否则回答 NO。"}],
                    images=[buf.getvalue()],
                )
                if "yes" in resp.lower():
                    cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
                    inp.click_at(cx, cy)
                    client.close()
                    return f"颜色选择器：SAM3+VLM 定位 {color} at ({cx},{cy}) score={r['score']:.2f}"
            client.close()
    except Exception as exc:
        executor.logger.info(f"SAM3 颜色检测失败: {exc}")

    # 4. 兜底：用 OmniParser 找无文字的彩色元素
    try:
        from ..vision.omniparser import OmniParser
        parser = executor._omniparser or OmniParser(box_threshold=0.01)
        elements = parser.parse(before)
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
