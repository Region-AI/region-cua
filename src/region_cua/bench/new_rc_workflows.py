"""Replacement for right-click-menu workflow."""


def _verify_screenshot_change(executor, before_path, msg=""):
    """通过截图比对验证操作是否生效。"""
    from ..vision.screenshot import compute_similarity
    after = executor._capture("workflow_rc_verify" + ("_" + msg if msg else ""))
    try:
        sim = compute_similarity(before_path, after)
        return (1 - sim) > 0.03
    except Exception:
        return True


def workflow_right_click_menu(executor, step):
    """右键菜单策略：SAM3+融合布局定位候选区域 -> 遍历右键直到成功 -> 点击菜单项。

    三层兜底：
    L1: SAM3+OmniParser融合布局定位所有候选 -> 逐个右键验证菜单弹出
    L2: VLM直接看截图找到菜单项坐标 -> 点击验证
    L3: 盲目遍历所有候选区域中心点击，检测页面变化
    """
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
        executor.logger.info(f"融合布局分析失败（OmniParser 兜底）: {exc}")

    elements = fused_result.get("elements", omni_elements)
    relationships = fused_result.get("relationships", {})
    rel_count = sum(len(v) for v in relationships.values())
    executor.logger.info(f"融合布局: {len(elements)} 元素, {rel_count} 关系")

    # 过滤：工具栏(y<100)、包含在其他区域内的子元素、空bbox
    candidates_list = []
    for i, elem in enumerate(elements):
        cx, cy = elem.get("center", (9999, 9999))
        bbox = elem.get("bbox", [0, 0, 0, 0])

        if len(bbox) != 4 or bbox[0] >= bbox[2] or bbox[1] >= bbox[3]:
            continue
        x1, y1, x2, y2 = bbox

        # 工具栏/地址栏区域排除
        if cy < 100 or y2 < 50:
            continue

        # 检查是否被其他更大元素包含（跳过子元素）
        is_inside = False
        for j, other in enumerate(elements):
            if i == j:
                continue
            obb = other.get("bbox", [])
            if len(obb) != 4 or obb[0] >= obb[2]:
                continue
            ox1, oy1, ox2, oy2 = obb
            if (ox1 <= x1 and oy1 <= y1 and x2 <= ox2 and y2 <= oy2):
                is_inside = True
                break

        if not is_inside:
            candidates_list.append((cx, cy, elem))

    # 兜底：如果过滤完了为空，取页面中左上区域(y<400, x<800)的元素
    if not candidates_list:
        for elem in elements:
            cx, cy = elem.get("center", (9999, 9999))
            if cy < 400 and cx < 800:
                bbox = elem.get("bbox", [0, 0, 0, 0])
                if len(bbox) == 4:
                    candidates_list.append((cx, cy, elem))

    # 最终兜底：页面中心区域
    if not candidates_list:
        from ..vision.screenshot import screen_size as ss
        w, h = ss()
        candidates_list.append((w // 2, h // 3, {"text": "page_center", "bbox": [0, 0, w, h]}))

    executor.logger.info(f"候选区域: {len(candidates_list)} 个")

    # ======== L1: 遍历候选右键，逐一切击验证菜单弹出 ========
    menu_shot_path = None
    for cidx, (cx, cy, elem) in enumerate(candidates_list):
        text_info = str(elem.get("text", ""))[:30] or "(无文字)"
        executor.logger.info(f"  [{cidx}] ({cx},{cy}) [{text_info}]")

        inp.click_at(cx, cx, button="right")
        time.sleep(0.8)

        # 截图找菜单项（说明右键成功）
        shot_after = executor._capture(f"workflow_rc_check_{cidx}")
        menu_bboxes, _ = executor._locate(shot_after, "copy|paste|cut|delete|select")
        if menu_bboxes:
            # 菜单找到了！记录这个截图用于后续找菜单项位置
            menu_shot_path = shot_after
            executor.logger.info(f"  [{cidx}] 成功弹出菜单！开始找菜单项...")
            break

    # 如果第一轮没找到，再试一轮（可能第一次点击偏差）
    if not menu_shot_path:
        executor.logger.info("第一轮未弹出菜单，第二轮重试...")
        for cidx, (cx, cy, elem) in enumerate(candidates_list):
            inp.click_at(cx, cy, button="right")
            time.sleep(0.8)
            shot_after = executor._capture(f"workflow_rc_retry_{cidx}")
            menu_bboxes, _ = executor._locate(shot_after, "copy|paste|cut|delete")
            if menu_bboxes:
                menu_shot_path = shot_after
                break

    # 清理可能残留的菜单/状态
    if not menu_shot_path:
        inp.press_key("escape")
        time.sleep(0.3)

    # ======== L2: VLM直接看截图找菜单项坐标 ========
    vlm_menu_coord = None
    if not menu_shot_path:
        try:
            from ..vision.ollama_client import OllamaClient
            from ..config import get_settings
            settings = get_settings()
            client = OllamaClient(settings.ollama_host, settings.ollama_timeout)

            # 用最终截图（不管有没有菜单）让VLM找
            vlm_shot = executor._capture("workflow_rc_vlm")
            with open(vlm_shot, "rb") as vf:
                img_bytes = vf.read()

            resp = client.chat(
                settings.ollama_vision_model,
                [{"role": "user", "content": (
                    f"The target is \"{menu_item_target}\". If there is a right-click menu, "
                    f"find the \"{menu_item_target}\" item and return JSON: "
                    "{{\"found\": true, \"x\": number, \"y\": number}}."
                )}],
                images=[img_bytes],
            )
            client.close()

            import re as _re2
            import json as _j2
            mx = _re2.search(r'\{[^}]+\}', resp)
            if mx:
                dd = _j2.loads(mx.group(0))
                if dd.get("found"):
                    vlm_menu_coord = (int(dd["x"]), int(dd["y"]))
                    executor.logger.info(f"VLM 找到菜单项 at ({dd['x']},{dd['y']})")
        except Exception as exc:
            executor.logger.info(f"VLM 找菜单项失败: {exc}")

    # ======== L2继续: 如果 menu_shot_path 存在，用 _locate 找菜单项 ========
    locate_menu_coords = None
    if menu_shot_path:
        mcs, _ = executor._locate(menu_shot_path, "copy|paste|cut|delete|select|剪切|复制|粘贴")
        if mcs and len(mcs) > 0:
            # 找与 target 最匹配的
            locate_menu_coords = sorted(
                [m for m in mcs if menu_item_target in str(m.get("text", "")).lower()[:20]]
                or mcs,
                key=lambda m: abs(len(menu_item_target) - len(m.get("text", "")))
            )[:5]  # 取最匹配的5个

    # ======== L3: 盲目遍历所有候选中心点击 ========
    best_change_score = -1
    best_click_info = None

    # Merge all click candidates from different strategies
    all_click_candidates = []

    # From L1 locates
    if locate_menu_coords:
        for mc in locate_menu_coords:
            bbox = mc.get("bbox", [])
            if len(bbox) == 4:
                mx = (bbox[0] + bbox[2]) // 2
                my = (bbox[1] + bbox[3]) // 2
                all_click_candidates.append((mx, my, str(mc.get("text", ""))[:20]))

    # From L2 VLM
    if vlm_menu_coord:
        vx, vy = vlm_menu_coord
        all_click_candidates.append((vx, vy, "(VLM)" + menu_item_target))

    # From candidates_list (fallback)
    for cx, cy, elem in candidates_list:
        all_click_candidates.append((cx, cy, str(elem.get("text", ""))[:20]))

    executor.logger.info(f"总共 {len(all_click_candidates)} 个点击候选")

    # Try each candidate with screenshot diff
    found_success = False
    for cidx, (clkx, clky, desc) in enumerate(all_click_candidates):
        before_chk = executor._capture("wrc_before_" + str(cidx))
        inp.click_at(clkx, clky)
        time.sleep(0.5)
        after_chk = executor._capture("wrc_after_" + str(cidx))

        from ..vision.screenshot import compute_similarity as csim
        sim = csim(before_chk, after_chk)
        change_score = 1 - sim
        executor.logger.info(f"  click({clkx},{clky}) [{desc}] sim={sim:.4f} changed={change_score:.4f}")

        if change_score > best_change_score:
            best_change_score = change_score
            best_click_info = (clkx, clky, desc)
            found_success = change_score > 0.03

    # JS check on action-display
    if found_success and best_click_info:
        try:
            js_val = (executor._evaluate_js(
                "document.getElementById('action-display')?.innerText || ''"
            ) or "").strip()
            if menu_item_target in js_val.lower():
                return f"右键菜单：成功 action-display='{js_val}' ({best_click_info[0]},{best_click_info[1]}) [{best_click_info[2]}]"
        except Exception:
            pass

    if found_success and best_click_info:
        return f"右键菜单：检测到变化 sim={best_change_score:.4f} at ({best_click_info[0]},{best_click_info[1]}) [{best_click_info[2]}] ✅"

    return (
        f"右键菜单：遍历 {len(candidates_list)} 位置候选（含VLM+locate）"
        f"未确认成功，最佳变化={best_change_score:.4f}"
    )
