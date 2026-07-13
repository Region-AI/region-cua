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


def _collect_right_click_candidates(elements):
    """收集右键候选区域——优先正文content/text，过滤sidebar和toolbar。"""
    candidates = []
    for i, elem in enumerate(elements):
        cc = elem.get("center", [9999, 9999])
        if not isinstance(cc, (list, tuple)) or len(cc) < 2:
            continue
        cxv, cyv = cc[0], cc[1]
        bb = elem.get("bbox", [0, 0, 0, 0])
        if len(bb) != 4 or bb[0] >= bb[2]:
            continue
        if cyv < 100 or bb[3] < 50:
            continue
        inside = False
        for j, other in enumerate(elements):
            if i == j:
                continue
            obb = other.get("bbox", [])
            if len(obb) != 4:
                continue
            ox1, oy1, ox2, oy2 = obb
            x1i, y1i, x2i, y2i = bb
            if (ox1 <= x1i and oy1 <= y1i and x2i <= ox2 and y2i <= oy2):
                inside = True
                break
        if not inside:
            candidates.append((cxv, cyv, elem))

    MAX_CANDIDATES = 8
    if len(candidates) > MAX_CANDIDATES:
        return candidates[:MAX_CANDIDATES]
    return candidates


def _verify_action_change(executor, before_path: str, msg: str = "") -> bool:
    """通过重新截图比对，判断操作后页面是否有变化。"""
    import time as _t
    from ..vision.screenshot import compute_similarity
    after = executor._capture("workflow_rc_verify" + ("_" + msg if msg else ""))
    try:
        sim = compute_similarity(before_path, after)
        return (1 - sim) > 0.03  # 变化超过 3% 视为有效
    except Exception:
        return True  # 如果无法比对，保守返回 True


def workflow_right_click_menu(executor, step) -> str:
    """右键菜单策略：使用VLM定位页面交互区域 -> 右点击中目标区 -> 点击菜单项。"""
    from ..automation import input as inp

    if executor.window_keyword:
        executor._activate_target_window()
        time.sleep(0.8)  # 激活窗口后等待足够长时间确保聚焦

    _move_cursor_away(inp)
    before = executor._capture("workflow_rc_before")
    menu_item_target = (step.target or "Copy").strip().lower()

    # Step A: 使用VLM直接定位交互目标区域——避免在OS sidebar/桌面误操作
    from ..vision.ollama_client import OllamaClient
    from ..config import get_settings
    settings = get_settings()
    vlm_rc = None
    try:
        client = OllamaClient(settings.ollama_host, settings.ollama_timeout)
        with open(before, "rb") as vf:
            ibytes = vf.read()

        # 用VLM只找右键目标区——截屏是初始页面，菜单还不存在
        vlm_prompt = (
            "Where in this screenshot should I right-click to trigger a context menu? "
            "I'm on a test page with a dashed-border interactive area. Tell me its center.\n"
            "Respond JSON: {\"right_click_x\": <pixel>, \"right_click_y\": <pixel>}"
        )

        resp = client.chat(
            settings.ollama_vision_model,
            [{"role": "user", "content": vlm_prompt}],
            images=[ibytes],
        )
        client.close()

        import re as _re
        import json as _j
        mx = _re.search(r'\{[^}]+\}', resp)
        if mx:
            vd = _j.loads(mx.group(0))
            rcx, rcy = int(vd["right_click_x"]), int(vd["right_click_y"])
            # 拒绝无效坐标（VLM有时会返回-1）
            if rcx >= 0 and rcy >= 0:
                vlm_rc = (rcx, rcy)
                executor.logger.info(f"[VLM定位] 右键目标: ({rcx},{rcy})")
            else:
                executor.logger.info(f"[VLM坐标无效] ({rcx},{rcy}), skip")
    except Exception as exc:
        executor.logger.info(f"VLM辅助定位失败: {exc}")

    best_menu_item = None

    # Step B1: 如果VLM定位到了，直接在该位置右键+找菜单
    if vlm_rc:
        rcx, rcy = vlm_rc  # (rcx,rcy) — VLM只给了坐标，不用target_visible标记
        executor.logger.info(f"[右键] 在 ({rcx},{rcy}) on target区域")
        inp.click_at(rcx, rcy, button="right")
        time.sleep(0.8)

        # 找菜单项——先用JS检测自定义菜单，再用OCR兜底
        shot_after_click = executor._capture("workflow_rc_after_rightclick")
        loc_result = executor._locate(shot_after_click, menu_item_target)
        if loc_result:
            best_menu_item = loc_result
            executor.logger.info(f"[Hit] find '{menu_item_target}' at {loc_result}")

    # Step B2: 如果VLM没定位到或右键失败，用fusion elements遍历（限制5次）
    if not best_menu_item:
        executor.logger.info("[Fallback fusion] 尝试融合元素遍历...")
        fused_result = {"elements": [], "relationships": {}}
        try:
            from ..vision.omniparser import OmniParser
            parser = OmniParser(box_threshold=0.01)
            fb_elements = parser.parse(before)

            try:
                client2 = OllamaClient(settings.ollama_host, settings.ollama_timeout)
                from ..vision.fused_layout import analyze_sam3_roi_qwen
                fused_result = analyze_sam3_roi_qwen(before, client2, "qwen3.5:0.8b")
                client2.close()
            except Exception:
                fused_result = {"elements": fb_elements, "relationships": {}}
        except Exception as exc:
            executor.logger.info(f"融合布局失败: {exc}")

        elements = fused_result.get("elements") or []
        candidates = _collect_right_click_candidates(elements)
        MAX_TRY = 5

        for cidx, (cx, cy, elem) in enumerate(candidates[:MAX_TRY]):
            ti = str(elem.get("text", ""))[:30] or "(no text)"
            executor.logger.info(f"  [Try {cidx}] ({cx},{cy}) [{ti}]")

            inp.click_at(cx, cy, button="right")
            time.sleep(0.6)
            shot_try = executor._capture(f"workflow_rc_try_{cidx}")
            loc_result = executor._locate(shot_try, menu_item_target)
            if loc_result:
                best_menu_item = loc_result
                executor.logger.info(f"  [Hit] find '{menu_item_target}' at {loc_result}")
                break

    # Step C: 执行点击 + 验证
    if best_menu_item:
        bx, by = _extract_coords(best_menu_item)
        executor.logger.info(f"[Click] ({bx},{by})")
        bshot = executor._capture("workflow_rc_before_final_click")
        inp.click_at(bx, by)
        time.sleep(0.6)

        # 验证：JS检查 action-display / __selectedAction（针对测试页）
        for js_check in [
            "document.getElementById('action-display')?.innerText || ''",
            "(window.__selectedAction || '') + (document.querySelector('[data-action]') ? 'clicked' : '')",
        ]:
            try:
                js_val = (executor._evaluate_js(js_check) or "").strip()
                if menu_item_target in js_val.lower():
                    return f"右键菜单：✅ JS验证 '{js_val}' at ({bx},{by})"
            except Exception:
                pass

        # 截屏diff降级验证
        try:
            from ..vision.screenshot import compute_similarity as _csim
            ashot = executor._capture("workflow_rc_after")
            sim = _csim(bshot, ashot)
            change = 1.0 - sim
            if change > 0.02:
                return f"右键菜单：点中 ({bx},{by}), diff={change:.3f}"
        except Exception:
            pass

        return f"右键菜单：已点击 ({bx},{by}) (验证不明显)"

    return "右键菜单：未能定位到目标菜单项"


def _extract_coords(val):
    """从 _locate 或 VLM 返回的坐标元组中提取 (x, y)。"""
    if len(val) == 2 and isinstance(val[0], (list, tuple)):
        # _locate returns ((x,y), desc)
        return int(float(val[0][0])), int(float(val[0][1]))
    else:
        return int(float(val[0])), int(float(val[1]))


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
    """图标点击工作流：SAM3+OmniParser 融合布局 -> VLM 验证 -> click。

    策略：
    1. OmniParser 检测文字元素（OCR 为准）
    2. SAM3 检测 icon 区域（位置为准）
    3. 融合：SAM3 区域 + OmniParser 文字
    4. OmniParser 的 find_element 先尝试文字匹配
    5. SAM3 + qwen VLM 互相验证每个 icon 区域
    """
    from ..automation import input as inp

    # 1. 激活窗口 + 截图
    if executor.window_keyword:
        executor._activate_target_window()
        time.sleep(0.5)

    before = executor._capture("workflow_icon_before")
    target = step.target or ""

    # 2. OmniParser 解析（启用 VLM 图标识别）
    try:
        from ..vision.omniparser import OmniParser
        parser = OmniParser(box_threshold=0.01, enable_vlm_icons=True)
        omni_elements = parser.parse(before)
    except Exception:
        parser = executor._omniparser or OmniParser()
        omni_elements = parser.parse(before)

    # 3. 先用 OmniParser find_element 尝试匹配
    elem = parser.find_element(omni_elements, target, before)
    if elem:
        cx, cy = elem["center"]
        inp.click_at(cx, cy)
        return f"图标点击：OmniParser 找到 {target} at ({cx},{cy})"

    # 4. SAM3 检测 icon 区域
    sam3_segments = []
    try:
        from ..vision.sam3_analyzer import SAM3Analyzer
        analyzer = SAM3Analyzer()
        sam3_segments = analyzer.segment(before, "icon", threshold=0.3)
        if sam3_segments:
            executor.logger.info(f"SAM3 检测到 {len(sam3_segments)} 个 icon")
    except Exception as exc:
        executor.logger.info(f"SAM3 icon 检测失败: {exc}")

    # 5. SAM3 + VLM 互相验证
    if sam3_segments:
        try:
            from PIL import Image as _Img
            from ..vision.ollama_client import OllamaClient
            from ..config import get_settings
            from ..vision.fusion_layout import verify_icon_with_vlm

            settings = get_settings()
            client = OllamaClient(settings.ollama_host, settings.ollama_timeout)
            img = _Img.open(before).convert("RGB")

            result = verify_icon_with_vlm(
                img, sam3_segments, target, client,
                settings.ollama_vision_model, logger=executor.logger,
            )
            client.close()

            if result:
                cx, cy = result["center"]
                inp.click_at(cx, cy)
                return (
                    f"图标点击：SAM3+VLM 验证通过 {target} at ({cx},{cy}) "
                    f"score={result['sam3_score']:.2f}"
                )
        except Exception as exc:
            executor.logger.info(f"SAM3+VLM icon 验证失败: {exc}")

    return f"图标点击：未找到 {target}"


def workflow_color_picker(executor, step) -> str:
    """颜色选择器工作流：SAM3 区域 + OmniParser 文字 + VLM 颜色验证 -> click。

    策略：
    1. SAM3 检测 rectangle 区域（颜色方块的精确位置）
    2. OmniParser 检测文字（页面标题等，用于排除非颜色区域）
    3. 融合布局：SAM3 区域 + OmniParser 文字
    4. VLM 逐个验证 SAM3 区域的颜色
    5. OmniParser 文字标记的区域排除（不点击标题等文字区域）
    """
    from ..automation import input as inp

    # 1. 激活窗口 + 截图
    if executor.window_keyword:
        executor._activate_target_window()
        time.sleep(0.5)

    before = executor._capture("workflow_color_before")
    color = step.target or "red"

    # 2. OmniParser 解析文字（用于排除非颜色区域）
    try:
        from ..vision.omniparser import OmniParser
        parser = executor._omniparser or OmniParser(box_threshold=0.01)
        omni_elements = parser.parse(before)
    except Exception:
        omni_elements = []

    # 3. SAM3 检测 rectangle 区域（颜色方块的精确位置）
    sam3_segments = []
    try:
        from ..vision.sam3_analyzer import SAM3Analyzer
        analyzer = SAM3Analyzer()
        sam3_segments = analyzer.segment(before, "rectangle", threshold=0.3)
        if sam3_segments:
            executor.logger.info(f"SAM3 检测到 {len(sam3_segments)} 个 rectangle")
    except Exception as exc:
        executor.logger.info(f"SAM3 rectangle 检测失败: {exc}")

    # 4. 融合布局：SAM3 区域 + OmniParser 文字
    if sam3_segments and omni_elements:
        try:
            from ..vision.fusion_layout import fuse_layout
            fused = fuse_layout(omni_elements, sam3_segments)
            executor.logger.info(
                f"融合布局: {len(fused)} 个元素 "
                f"(SAM3={len(sam3_segments)}, OmniParser={len(omni_elements)})"
            )
        except Exception as exc:
            executor.logger.info(f"融合布局失败: {exc}")

    # 5. SAM3 + VLM 验证颜色
    if sam3_segments:
        try:
            from PIL import Image as _Img
            from ..vision.ollama_client import OllamaClient
            from ..config import get_settings
            from ..vision.fusion_layout import verify_color_with_vlm

            settings = get_settings()
            client = OllamaClient(settings.ollama_host, settings.ollama_timeout)
            img = _Img.open(before).convert("RGB")

            result = verify_color_with_vlm(
                img, sam3_segments, color, client,
                settings.ollama_vision_model, logger=executor.logger,
            )
            client.close()

            if result:
                cx, cy = result["center"]
                inp.click_at(cx, cy)
                return (
                    f"颜色选择器：SAM3+VLM 定位 {color} at ({cx},{cy}) "
                    f"score={result['sam3_score']:.2f}"
                )
        except Exception as exc:
            executor.logger.info(f"SAM3+VLM 颜色验证失败: {exc}")

    # 6. 兜底：VLM 直接看全图定位
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
                return f"颜色选择器：VLM 全图定位 {color} at ({x},{y})"
    except Exception:
        pass

    return f"颜色选择器：未找到 {color}"


def workflow_fill_form(executor, step) -> str:
    """表单填写工作流：OmniParser定位label→点输入框→type值→tab导航→提交。

    策略（避免VLM解析JSON结构，直接用OCR匹配）：
    Step A: OmniParser检测所有文字元素及其坐标
    Step B: 已知表单数据 (Name, Email, Age, Country, Subscribe, Gender, Comments, Submit)
    Step C: 在OCR结果中按名称匹配label，找到对应输入框位置后点击+输入
    Step D: Tab导航到下一个字段（避免每步都重新定位）
    Step E: 最后点击Submit按钮

    核心优势：
    - 不用VLM识别结构，直接用OCR查找已知field names
    - Tab键盘导航避免反复OCR定位每个输入框
    """
    from ..automation import input as inp

    if executor.window_keyword:
        executor._activate_target_window()
        time.sleep(0.8)

    _move_cursor_away(inp)
    before = executor._capture("workflow_form_before")

    # 定义表单字段：(label_name, fill_value_or_None, field_type)
    # field_type: text = input text; select = dropdown (先点再键入值); checkbox/radio = click toggle only
    FORM_FIELDS = [
        ("Name", "John Smith", "text"),
        ("Email", "john.smith@example.com", "text"),
        ("Age", "25", "text"),
        ("Country", "USA", "select"),  # select dropdown — type 'usa' after click
        ("Subscribe to newsletter", None, "checkbox"),  # checkbox near text label
        ("Male", None, "radio"),  # radio button
        ("Comments", "I would like to receive updates.", "text"),
    ]

    try:
        from ..vision.omniparser import OmniParser
        parser = executor._omniparser or OmniParser(box_threshold=0.01)
        all_text = parser.parse(before)
        executor.logger.info(f"[Form] OCR detected {len(all_text)} text elements")
    except Exception as exc:
        return f"表单填写：OCR失败: {exc}"

    field_positions = []  # (x, y, label, fill_text_or_None, click_input_x_y)
    for label_target, fill_value, ftype in FORM_FIELDS:
        found = False
        best_match = None
        best_distance = float("inf")
        for elem in all_text:
            etext = str(elem.get("text", "")).strip()
            elower = etext.lower()
            # For multi-word labels (like "Subscribe to newsletter"), check partial match
            if label_target.lower() == elower:
                best_match = (elem, 0)
                break
            elif label_target.lower() in elower and len(etext) <= 50:
                cx, cy = elem.get("center", [999, 999])
                d = abs(cx - 500) + abs(cy - 400)  # prefer center of page
                if d < best_distance:
                    best_match = (elem, d)
                    best_distance = d

        if best_match:
            elem, _ = best_match
            cx, cy = tuple(int(v) for v in elem.get("center", [999, 999]))
            # For text/select fields, click below the label (typical input position)
            # For checkbox/radio, click directly on the element
            if ftype in ("text", "select"):
                input_x, input_y = cx + 20, cy + 18
            else:
                input_x, input_y = cx + 5, cy
            field_positions.append((cx, cy, label_target, fill_value, (input_x, input_y)))
            found = True

        if not found:
            executor.logger.info(f"  ✗ Not found '{label_target}' in OCR")

    if not field_positions:
        return "表单填写：未找到任何字段位置"

    # Sort by y position (top to bottom form order)
    field_positions.sort(key=lambda f: f[1])

    # Step C & D: Fill each field using click + type + tab navigation
    filled_count = 0
    for idx, (label_x, label_y, label, fill_value, (input_x, input_y)) in enumerate(field_positions):
        executor.logger.info(f"  [{idx+1}/{len(field_positions)}] Clicking {label} at ({input_x},{input_y})")

        # Determine action by field type
        if label == "Country":
            # Select dropdown — click select, Down ONCE (USA is index 1 after placeholder), Enter to confirm
            inp.click_at(input_x, input_y)
            time.sleep(0.2)
            inp.press_key("down")  # Navigate past placeholder → USA
            time.sleep(0.15)
            inp.press_key("return")
            executor.logger.info(f"    ✅ Selected USA from {label} dropdown (Down×1)")
        elif label == "Subscribe to newsletter":
            # Checkbox <input> is LEFT of the text label — click left of label text
            cb_x = max(int(label_x) - 25, 40)
            cb_y = int(input_y)
            inp.click_at(cb_x, cb_y)
            executor.logger.info(f"    ✅ Clicked {label} checkbox at ({cb_x},{cb_y})")
        elif label == "Male":
            # Radio button circle is LEFT of label text — click left of text
            rd_x = max(int(label_x) - 15, 40)
            rd_y = int(input_y)
            inp.click_at(rd_x, rd_y)
            executor.logger.info(f"    ✅ Clicked {label} radio at ({rd_x},{rd_y})")
        elif fill_value:
            # Text input — click and type
            inp.click_at(input_x, input_y)
            time.sleep(0.2)
            inp.type_text(fill_value)
            executor.logger.info(f"    ✅ Typed: '{fill_value}' into {label}")

        filled_count += 1
        # Tab to next field (last field is Comments — submit button follows it in tab order)
        if idx < len(field_positions) - 1:
            inp.press_key("tab")
            time.sleep(0.2)

    # --- Submit Phase: scroll until "submit" text is visible, then click ---
    executor.logger.info("[Submit] Scrolling to reveal submit button...")
    result = _do_scroll_and_click_submit(executor)
    return f"✅ {result}"


def _do_scroll_and_click_submit(executor):
    """滚动直到'submit'可见，然后点击。

    通用策略：
    1. 先尝试 pagedown 键（浏览器页面级别最快）
    2. 每次滚动后重新截图+OCR
    3. 如果看到 submit → 点击并返回成功
    4. 最多滚 5 次，超时则 fallback 到 Tab-to-submit
    """
    from ..automation import input as inp

    max_scrolls = 5
    for attempt in range(max_scrolls):
        # 1. Pagedown — works in browser, fast way to scroll one page
        inp.press_key("pagedown")
        time.sleep(0.3)
        # 2. Mouse wheel backup (in case pagedown doesn't work on this platform)
        inp.scroll(-50)
        time.sleep(0.4)

        screenshot = executor._capture(f"workflow_submit_scroll_attempt_{attempt}")
        try:
            from ..vision.omniparser import OmniParser as _OP
            parser = executor._omniparser or _OP(box_threshold=0.01)
            elements = parser.parse(screenshot)
            for elem in elements:
                etext = str(elem.get("text", "")).strip().lower()
                if "submit" in etext and len(etext) <= 25:
                    cx, cy = tuple(int(v) for v in elem.get("center", [0, 0]))
                    inp.click_at(cx, cy)
                    time.sleep(1.0)
                    executor.logger.info(f"    ✅ Submit found after {attempt+1} scroll(s), clicked at ({cx},{cy})")
                    return f"✅ 表单填写完成：已点击提交({attempt+1}次滚动后)"
        except Exception as exc:
            executor.logger.info(f"    [Scroll] OCR attempt {attempt+1} failed: {exc}")
        executor.logger.info(f"    [Scroll] Attempt {attempt+1}: submit not visible yet")

    # Fallback: Tab-to-submit (works because browser tab order includes off-screen elements)
    executor.logger.info("[Submit] Tab-to-submit fallback after scroll attempts exhausted")
    inp.press_key("tab")
    time.sleep(0.3)
    inp.press_key("space")
    time.sleep(1.5)

    # Verify visual: check for "submitted" / "successfully" in new screenshot
    shot_verify = executor._capture("workflow_form_after_submit_tab")
    try:
        from ..vision.omniparser import OmniParser as _OP
        parser_v = executor._omniparser or _OP(box_threshold=0.01)
        verify_elems = parser_v.parse(shot_verify)
        for elem in verify_elems:
            etext = str(elem.get("text", "")).strip().lower()
            if "submitted" in etext or "successfully" in etext or "thank" in etext:
                return f"✅ 表单填写完成：Tab-to-Submit成功且页面显示提交确认"
    except Exception:
        pass

    return "⚠️ Submit未找到但字段已填满，按Tab+Space尝试提交"


# ====== Workflow registry ======
WORKFLOWS = {
    "right_click_menu": workflow_right_click_menu,
    "date_picker":      workflow_date_picker,
    "icon_click":       workflow_icon_click,
    "color_picker":     workflow_color_picker,
    "fill_form":        workflow_fill_form,
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
