"""通用融合布局分析器：SAM3 bbox定位 + qwen3.5:0.8b ROI语义增强。

统一流水线（对所有工作流通用）：
1. SAM3 segment_multi() 输出所有区域的精确bbox（~9s/次推理）
2. ROI crop → qwen3.5:0.8b逐区域识别type+text（N×小ROI ≈ N×0.5-1s）
3. bbox几何融合拓扑（contains/touches/adjacent）→ 全局elements列表

输出结构统一给所有工作流消费：
{
  "elements": [...],      # {bbox: [x1,y1,x2,y2], center: (cx,cy), type, text, confidence, source}
  "relationships": {...}, # bbox拓扑 dict
}
"""

from __future__ import annotations

import json
import logging
import re
from typing import Optional

from PIL import Image

_log = logging.getLogger(__name__)


def _approx_same_box(box1: list, box2: list, iou_thresh: float = 0.9) -> bool:
    """判断两个bbox是否基本相同（IoU > iou_thresh）"""
    x1 = max(box1[0], box2[0])
    y1 = max(box1[1], box2[1])
    x2 = min(box1[2], box2[2])
    y2 = min(box1[3], box2[3])
    if x2 <= x1 or y2 <= y1:
        return False
    inter = (x2 - x1) * (y2 - y1)
    area1 = (box1[2] - box1[0]) * (box1[3] - box1[1])
    area2 = (box2[2] - box2[0]) * (box2[3] - box2[1])
    iou = inter / (area1 + area2 - inter + 1e-6)
    return iou > iou_thresh


def _bbox_iou(box1: list, box2: list) -> float:
    x1 = max(box1[0], box2[0])
    y1 = max(box1[1], box2[1])
    x2 = min(box1[2], box2[2])
    y2 = min(box1[3], box2[3])
    if x2 <= x1 or y2 <= y1:
        return 0.0
    inter = (x2 - x1) * (y2 - y1)
    a1 = (box1[2] - box1[0]) * (box1[3] - box1[1])
    a2 = (box2[2] - box2[0]) * (box2[3] - box2[1])
    return inter / (a1 + a2 - inter + 1e-6)


def _overlap_ratio(small_box: list, big_box: list) -> float:
    x1 = max(small_box[0], big_box[0])
    y1 = max(small_box[1], big_box[1])
    x2 = min(small_box[2], big_box[2])
    y2 = min(small_box[3], big_box[3])
    if x2 <= x1 or y2 <= y1:
        return 0.0
    inter = (x2 - x1) * (y2 - y1)
    s_area = (small_box[2] - small_box[0]) * (small_box[3] - small_box[1])
    return inter / (s_area + 1e-6)


# === 路径1: SAM3 bbox → ROI crop → qwen逐区语义识别 ===

def segment_roi_identify(
    image_path_or_stream: str | Image.Image,
    sam3_regions: dict[str, list],
    client,
    vlm_model: str = "qwen3.5:0.8b",
) -> list:
    """SAM3分割后，对每个区域做ROI crop + qwen类型+文字识别。

    Args:
        image_path_or_stream: 原始截图 path 或 PIL Image
        sam3_regions: SAM3 segment_multi返回 {"rectangle": [...], "button": [...]}
                        seg item format: [label, [x1,y1,x2,y2]]
        client: OllamaClient实例（用于qwen推理）
        vlm_model: qwen模型名

    Returns:
        [{"bbox":[],"center":[],"type":"button/icon/...","text":"","confidence":0.9,"source":"sam3_qwen_fused"}]
    """
    if isinstance(image_path_or_stream, str):
        image = Image.open(image_path_or_stream).convert("RGB")
    elif image_path_or_stream.mode != "RGB":
        image = image_path_or_stream.convert("RGB")
    else:
        image = image_path_or_stream.copy()

    w, h = image.size

    # 1) SAM3所有bbox去重（重叠>90%算同一个）
    all_bboxes = []
    for seg_list in sam3_regions.values():
        for seg in seg_list:
            bbox = list(seg[1]) if isinstance(seg, (list, tuple)) and len(seg) >= 2 else seg
            is_dup = False
            for exist_box in all_bboxes:
                if _approx_same_box(bbox, exist_box):
                    is_dup = True
                    break
            if not is_dup:
                x1, y1, x2, y2 = bbox
                if (x2 - x1) * (y2 - y1) < 400:  # >20x20px
                    all_bboxes.append(bbox)

    _log.info(f"收集到 {len(all_bboxes)} 个去重SAM3 bbox")

    if not all_bboxes:
        return []

    # 2) Prompt：对单一ROI做类型+文字识别（非常具体）
    roi_prompt = (
        "You are analyzing a SINGLE cropped UI element from a web page or desktop app. Tell me what type this is and what text it has.\n"
        "Respond in JSON ONLY with NO markdown code fences:\n"
        "{\n"
        '  "type": "<button | icon | text_button | input_field | label_text | image_link | checkbox | radio | divider | header_menu | toolbar_icon | tab | empty>",\n'
        '  "text": "<visible text inside, or empty if none>",\n'
        '  "confidence": <0.0 to 1.0>,\n'
        '  "has_text_icon": <true if it contains a recognizable icon/symbol>\n'
        "}\n"
        "* type MUST be one of the listed exact strings.*\n"
        "* confidence >= 0.3 even if uncertain.*\n"
        "* Do NOT output explanations or code fences — just JSON object."
    )

    elements = []
    for idx, box in enumerate(all_bboxes):
        x1, y1, x2, y2 = [int(c) for c in box]
        cx, cy = (x1 + x2) // 2, (y1 + y2) // 2

        # ROI crop（边缘+8%防止裁剪误差）
        pad_x = min(int((x2 - x1) * 0.08), 10)
        pad_y = min(int((y2 - y1) * 0.08), 10)
        if isinstance(image, str):
            roi = Image.open(image).crop(
                (max(0, x1-pad_x), max(0, y1-pad_y), min(w, x2+pad_x), min(h, y2+pad_y)))
        else:
            roi = image.crop((max(0, x1-pad_x), max(0, y1-pad_y),
                              min(w, x2+pad_x), min(h, y2+pad_y)))

        import io
        buf = io.BytesIO()
        roi.save(buf, format="PNG")
        roi_bytes = buf.getvalue()

        try:
            resp = client.chat(
                vlm_model,
                [{"role": "user", "content": roi_prompt}],
                images=[roi_bytes]
            )
            _log.debug(f"ROI {idx} qwen: {resp[:80]}")

            # 提取JSON（可能带代码围栏或多余文本）
            json_match = re.search(r'\{[^{}]+\}', resp, re.DOTALL)
            if json_match:
                arr = json.loads(json_match.group(0))
                box_type = str(arr.get("type", "unknown"))
                # 只保留合法类型
                valid_types = {"button","icon","text_button","input_field","label_text",
                               "image_link","checkbox","radio","divider","header_menu",
                               "toolbar_icon","tab","empty"}
                if box_type not in valid_types:
                    box_type = "unknown"
                text = str(arr.get("text", "")).strip()
                conf = max(float(arr.get("confidence", 0.5)), 0.1)
            else:
                box_type, text, conf = "unknown", "", 0.1

        except Exception as exc:
            _log.warning(f"ROI {idx} qwen识别失败: {exc}")
            box_type, text, conf = "unknown", "", 0.0

        elements.append({
            "bbox": [x1, y1, x2, y2],
            "center": (cx, cy),
            "text": text,
            "type": box_type,
            "confidence": conf,
            "source": "sam3_qwen_fused",
        })

    _log.info(f"qwen对{len(all_bboxes)}个ROI识别成功: {len(elements)}个元素，类型分布={dict((t, sum(1 for e in elements if e['type']==t)) for t in set(e['type'] for e in elements))}")
    return elements


# === 路径2: 全图VLM bbox检测（快速fallback）===

def analyze_with_vlm(image: str | Image.Image, client, model_name: str) -> list:
    """Qwen3.5一次性输出所有UI元素bbox+type（~2s但小区域框不准，做fallback）"""
    if isinstance(image, str):
        image = Image.open(image).convert("RGB")
    img_w, img_h = image.size

    prompt = (
        "Analyze screenshot and extract ALL interactive elements. JSON only:\n"
        '[{"bbox":[x1,y1,x2,y2],"type":"button|icon|text_button|input|label","confidence":float}]\n'
        "* x1<x2, y1<y2. Include all clickable/interactive items.*\n"
        "* Exclude browser toolbar (top ~6%)*. "
    )

    buf = io.BytesIO()
    image.save(buf, format="PNG")
    resp = client.chat(model_name, [{"role": "user", "content": prompt}], images=[buf.getvalue()])
    json_match = re.search(r'\[.*?\]', resp, re.DOTALL)
    if not json_match:
        return []

    arr = json.loads(json_match.group(0))
    elements = []
    for item in arr:
        bbox = item.get("bbox")
        if not bbox or len(bbox) != 4:
            continue
        x1,y1,x2,y2 = int(bbox[0]),int(bbox[1]),int(bbox[2]),int(bbox[3])
        if x1>=x2 or y1>=y2 or (x2-x1)*(y2-y1)<400:
            continue
        if y2 < img_h*0.06:  # toolbar filter
            continue
        elements.append({
            "bbox":[x1,y1,x2,y2],
            "center":((x1+x2)//2,(y1+y2)//2),
            "type":str(item.get("type","unknown")),
            "text":"",
            "confidence":float(item.get("confidence",0.5)),
            "source":"vlm_bbox",
        })
    _log.info(f"VLM全图识别: {len(elements)}个元素")
    return elements


# === 路径3: SAM3 bbox → ROI-crop-qwen 与 OmniParser融合 ===

def fuse_layout_roi_qwen(
    image_path_or_stream: str,
    sam3_regions: dict,
    client,
    omni_elements: list = None,
) -> dict:
    """核心融合路径：SAM3 bbox → ROIQ→qwen类别+OCR → Fusion result."""

    # step1: SAM3 bbox ROI crop识别
    elements = segment_roi_identify(image_path_or_stream, sam3_regions, client)
    if not elements:
        return {"elements": omni_elements or [], "relationships": {}}

    # step2 + OmniParser text增强（重叠IoU>0.2的OCR文本覆盖qwen识别的text）
    enhanced = []
    for elem in elements:
        bbox = elem["bbox"]
        best_omni_text = ""
        best_conf = 0
        if omni_elements:
            for oe in omni_elements:
                obb = oe.get("bbox") or [0,0,0,0]
                iou = _bbox_iou(bbox, obb)
                ratio = _overlap_ratio(ob_obb, bbox) if isinstance(obb, list) and len(obb)==4 else 0
                if iou > 0.2 and ratio > 0.15:
                    otext = (oe.get("text") or "").strip()
                    oconf = float(oe.get("confidence",0))
                    if otext and (not best_omni_text or oconf > best_conf):
                        best_omni_text, best_conf = otext, oconf

        # 用OCR文字增强qwen识别的text（但保留qwen type）
        final_text = best_omni_text if best_omni_text and len(best_omni_text) <= elem["text"] else elem["text"]
        enhanced.append({
            **elem,
            "text": final_text,
            "source": "sam3_qwen_fused" if not omni_elements else "fusion_sam3_omni",
        })

    # step3: 计算拓扑关系（contains/touches/adjacent）
    relationships = _compute_relationships(enhanced)

    return {"elements": enhanced, "relationships": relationships}


# === 拓扑关系：bbox几何计算（contains/touches/adjacent）===

def _compute_relationships(elements: list) -> dict:
    """纯bbox几何计算拓扑关系"""
    rels = {}
    for i in range(len(elements)):
        b1 = elements[i]["bbox"]
        rels[i] = []
        for j in range(len(elements)):
            if i == j:
                continue
            b2 = elements[j]["bbox"]

            ov1 = _overlap_ratio(b1, b2)  # fraction of |e1| inside e2
            ov2 = _overlap_ratio(b2, b1)  # fraction of |e2| inside e1

            if ov1 > 0.85:
                rels[i].append({"rel": "contains_within", "target": j, "overlap": ov1})
            elif ov2 > 0.85:
                rels[i].append({"rel": "contains", "target": j, "overlap": ov2})
            else:
                iou_val = _bbox_iou(b1, b2)
                if iou_val < 0.05:
                    # Calculate gaps in px
                    dx_right = b2[0] - b1[2]
                    dx_left = b1[0] - b2[2]
                    dy_down = b2[1] - b1[3]
                    dy_up = b1[1] - b2[3]

                    tight_x = abs(dx_right) < 5 or abs(dx_left) < 5
                    tight_y = abs(dy_down) < 5 or abs(dy_up) < 5

                    if tight_x or tight_y:
                        # touches
                        if tight_x and not tight_y:
                            d = "left" if abs(dx_left) < abs(dx_right) else "right"
                        elif tight_y and not tight_x:
                            d = "up" if abs(dy_up) < abs(dy_down) else "down"
                        else:
                            c1c = ((b1[0]+b1[2])//2,(b1[1]+b1[3])//2)
                            c2c = ((b2[0]+b2[2])//2,(b2[1]+b2[3])//2)
                            d = "left" if abs(c1c[0]-c2c[0]) > abs(c1c[1]-c2c[1]) and c1c[0]<c2c[0] else \
                                "right" if abs(c1c[0]-c2c[0]) > abs(c1c[1]-c2c[1]) and c1c[0]>c2c[0] else \
                                "up" if abs(c1c[1]-c2c[1]) >= abs(c1c[0]-c2c[0]) and c1c[1]<c2c[1] else "down"
                        rels[i].append({"rel": "touches", "dir": d, "target": j})
                    elif min(abs(dx_right) if dx_right>0 else 9999, abs(dx_left) if dx_left>0 else 9999,
                            abs(dy_down) if dy_down>0 else 9999, abs(dy_up) if dy_up>0 else 9999) < min((b1[2]-b1[0]) + (b2[2]-b2[0]),(b1[3]-b1[1])+(b2[3]-b2[1]))*0.4:
                        c1c = ((b1[0]+b1[2])//2,(b1[1]+b1[3])//2)
                        c2c = ((b2[0]+b2[2])//2,(b2[1]+b2[3])//2)
                        d = "left" if abs(c1c[0]-c2c[0])>abs(c1c[1]-c2c[1]) and c1c[0]<c2c[0] else \
                            "right" if abs(c1c[0]-c2c[0])>abs(c1c[1]-c2c[1]) and c1c[0]>c2c[0] else \
                            "up" if abs(c1c[1]-c2c[1])>=abs(c1c[0]-c2c[0]) and c1c[1]<c2c[1] else "down"
                        rels[i].append({"rel": "adjacent", "dir": d, "target": j})

    return rels


def analyze_sam3_roi_qwen(
    image_path_or_stream: str | Image.Image,
    client,
    vlm_model: str = "qwen3.5:0.8b",
    sam3_types: list[str] = ["rectangle", "button"],
) -> dict:
    """主入口：SAM3 bbox → ROI crop → qwen识别 → Fusion result。

    返回统一结构给所有工作流消费。
    """
    from ..omniparser import OmniParser
    parser = OmniParser(box_threshold=0.01)
    omni_elements = parser.parse(image_path_or_stream)

    # step1: SAM3 segment_multi (9s/次推理 × N个prompt)
    try:
        from ..sam3_analyzer import SAM3Analyzer
        analyzer = SAM3Analyzer()
        sam3_regions = analyzer.segment_multi(image_path_or_stream, sam3_types, threshold=0.25)
    except Exception as exc:
        _log.warning(f"SAM3分割失败: {exc}")
        return {"elements": omni_elements, "relationships": {}}

    # step2: SAM3 bbox ROI crop识别
    elements = segment_roi_identify(image_path_or_stream, sam3_regions, client, vlm_model)
    if not elements:
        _log.warning("qwen ROI识别未返回有效元素，fallback OmniParser")
        return {"elements": omni_elements, "relationships": {}}

    # step3: 拓扑关系计算
    relationships = _compute_relationships(elements)
    _log.info(f"融合成功: {len(elements)}个元素（SAM3 bbox+qwen类型），{sum(len(v) for v in relationships.values())}条关系")

    return {"elements": elements, "relationships": relationships}
