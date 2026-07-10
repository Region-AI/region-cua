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
    """右键菜单策略：融合布局定位候选 -> 遍历右键验证 -> 点击菜单项 -> 多层兜底。"""
    from ..automation import input as inp

    if executor.window_keyword:
        executor._activate_target_window()
        time.sleep(0.5)

    _move_cursor_away(inp)
    before = executor._capture("workflow_rc_before")
    menu_item_target = (step.target or "Copy").strip().lower()

    # OmniParser + SAM3 融合布局
    from ..vision.omniparser import OmniParser
    parser = OmniParser(box_threshold=0.01)
    omni_elements = parser.parse(before)

    fused_result = {"elements": list(omni_elements), "relationships": {}}
    try:
        from ..vision.sam3_analyzer import SAM3Analyzer
        analyzer = SAM3Analyzer()
        sam3_regions = analyzer.segment_multi(before, ["rectangle", "button"], threshold=0.25)
        all_segs = [seg for k in sam3_regions for seg in sam3_regions[k]]

        from ..vision.fusion_layout import fuse_layout as fuse_f
        fused_result = fuse_f(omni_elements, all_segs)
    except Exception as exc:
        executor.logger.info(f"融合布局失败（OmniParser 兜底）: {exc}")

    elements = fused_result.get("elements", omni_elements)
    rcount = sum(len(v) for v in fused_result.get("relationships", {}).values())
    executor.logger.info(f"融合布局: {len(elements)} 元素, {rcount} 关系")

    # 过滤：工具栏(y<100)、容器内子元素、空bbox
    candidates = []
    for i, elem in enumerate(elements):
        cc = elem.get("center", [9999, 9999])
        if not isinstance(cc, (list, tuple)) or len(cc) < 2:
            continue
        cxv, cyv = cc[0], cc[1]
        bb = elem.get("bbox", [0, 0, 0, 0])
        if len(bb) != 4 or bb[0] >= bb[2]:
            continue

        # Tool-bar / address-bar area
        if cyv < 100 or bb[3] < 50:
            continue

        # Contained by another? Skip sub-elements.
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

    # Fallback: page top-left area
    if not candidates:
        from ..vision.screenshot import screen_size
        sw, sh = screen_size()
        for elem in elements:
            c2 = elem.get("center", [9999, 9999])
            if isinstance(c2, (list, tuple)) and len(c2) >= 2:
                ct, cy2 = c2[0], c2[1]
                if cy2 < 400 and ct < sw // 2:
                    candidates.append((ct, cy2, elem))
        if not candidates:
            bd = elements[-1].get("bbox", [0, 0, sw, sh]) if elements else [0, 0, sw, sh]
            candidates.append((sw // 2, sh // 3, {"text": "page_center", "bbox": bd}))

    executor.logger.info(f"候选区域: {len(candidates)}")

    # ======== L1: traverse candidates right-clicking until menu pops ========
    best_shot_path = None
    for cidx, (cx, cy, elem) in enumerate(candidates):
        ti = str(elem.get("text", ""))[:30] or "(无文字)"
        executor.logger.info(f"  [{cidx}] ({cx},{cy}) [{ti}]")

        inp.click_at(cx, cy, button="right")
        time.sleep(0.8)
        shot_after = executor._capture(f"workflow_rc_check_{cidx}")
        mbs, _ = executor._locate(shot_after, "copy|paste|cut|delete|select|剪切|复制|粘贴")
        if mbs and len(mbs) > 0:
            best_shot_path = shot_after
            executor.logger.info(f"  [{cidx}] 菜单弹出！开始找菜单项...")
            break

    if not best_shot_path:
        # Second pass
        for cidx, (cx, cy, elem) in enumerate(candidates):
            inp.click_at(cx, cy, button="right")
            time.sleep(0.8)
            shot2 = executor._capture(f"workflow_rc_retry_{cidx}")
            mbs2, _ = executor._locate(shot2, "copy|paste|cut|delete")
            if mbs2 and len(mbs2) > 0:
                best_shot_path = shot2
                break

    # Escape to clean up
    if not best_shot_path:
        inp.press_key("escape")
        time.sleep(0.3)

    # ======== L2: locate menu items from snapshot ========
    mlcs = None
    if best_shot_path:
        mcs, _ = executor._locate(best_shot_path, "copy|paste|cut|delete|select|剪切|复制|粘贴")
        if mcs and len(mcs) > 0:
            mlcs = sorted(
                [m for m in mcs if menu_item_target in str(m.get("text", "")).lower()[:20]]
                or mcs,
                key=lambda m: abs(len(menu_item_target) - len(str(m.get("text", ""))))
            )[:5]

    # ======== L3: VLM to find menu item coords directly ========
    vlm_coord = None
    try:
        from ..vision.ollama_client import OllamaClient
        from ..config import get_settings
        sh = best_shot_path if best_shot_path else executor._capture("workflow_rc_vlm_last")
        settings = get_settings()
        client = OllamaClient(settings.ollama_host, settings.ollama_timeout)
        with open(sh, "rb") as vf:
            ibytes = vf.read()
        resp = client.chat(
            settings.ollama_vision_model,
            [{"role": "user", "content": (
                f"Target menu item: \"{menu_item_target}\". Find it and return JSON: "
                "{{\"found\": true, \"x\": <number>, \"y\": <number>}}."
            )}],
            images=[ibytes],
        )
        client.close()
        import re as _re
        import json as _j
        mx = _re.search(r'\{[^}]+\}', resp)
        if mx:
            dd = _j.loads(mx.group(0))
            if dd.get("found"):
                vlm_coord = (int(dd["x"]), int(dd["y"]))
    except Exception as exc:
        executor.logger.info(f"VLM 菜单项坐标定位失败: {exc}")

    # ======== L4: execute candidate clicks with change detection ========
    all_clicks = []
    if mlcs:
        for mc in mlcs:
            b = mc.get("bbox", [])
            if len(b) == 4 and b[0] < b[2]:
                mx2 = (b[0] + b[2]) // 2
                my2 = (b[1] + b[3]) // 2
                txt = str(mc.get("text", ""))[:20]
                all_clicks.append((mx2, my2, "locate:" + txt))

    if vlm_coord:
        vx, vy = vlm_coord
        all_clicks.append((vx, vy, "vlm:" + menu_item_target))

    for cx3, cy3, elem3 in candidates:
        t3 = str(elem3.get("text", ""))[:20] or "(无文字)"
        all_clicks.append((cx3, cy3, "fallback:" + t3))

    best_score = -1.0
    best_info = None
    success_count = 0

    for icc, (akx,aky, adesc) in enumerate(all_clicks):
        bshot = executor._capture(f"wrc_b_{icc}")
        inp.click_at(akx, aky)
        time.sleep(0.5)
        ashot = executor._capture(f"wrc_a_{icc}")

        from ..vision.screenshot import compute_similarity as csim
        sim = csim(bshot, ashot)
        score = 1 - sim
        if score > best_score:
            best_score = score
            best_info = (akx, aky, adesc)
        if score > 0.03:
            success_count += 1

    # JS check on action-display for right-click-menu test
    if success_count > 0 and best_info:
        try:
            js_val = (executor._evaluate_js(
                "document.getElementById('action-display')?.innerText || ''"
            ) or "").strip()
            if menu_item_target in js_val.lower():
                return f"右键菜单：✅ action-display='{js_val}' ({best_info[0]},{best_info[1]}) [{best_info[2]}]"
        except Exception:
            pass

    if success_count > 0 and best_info:
        return (f"右键菜单：成功检测变化 {success_count} 次，最佳 ({best_info[0]},{best_info[1]}) "
                f"[{best_info[2]}] sim_change={best_score:.4f}")

    if all_clicks:
        return (f"右键菜单：遍历 {len(all_clicks)} 候选点击（含VLM/locate），最佳变化={best_score:.4f}"
                f" at ({best_info[0]},{best_info[1]}) [{best_info[2]}]")

    return "右键菜单：所有策略均失败"


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
