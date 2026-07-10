"""SAM3 + OmniParser 融合布局分析器。

融合策略：
1. 区域位置以 SAM3 为准（分割边界精确）
2. 文字内容以 OmniParser 为准（OCR 识别准确）
3. 图标识别用 SAM3 + qwen VLM 互相验证
4. 输出区域间的拓扑关系（包含、相邻、接触/上下左右）

输出统一的 elements 列表，每个元素包含：
- bbox: [x1, y1, x2, y2]
- center: (x, y)
- text: str (可能为空)
- type: str
- source: "sam3" / "omniparser" / "fused"
- relationships: list of {"rel": "contains"/"adjacent"/"touches", "dir": "up/down/left/right", "target": index}
"""

from __future__ import annotations

import logging
from typing import Optional, Literal

import numpy as np
from PIL import Image

_log = logging.getLogger(__name__)


RelationshipType = Literal["contains", "contains_within", "adjacent", "touches"]
DirectionType = Literal["up", "down", "left", "right", None]


def _iou(box1: list[int], box2: list[int]) -> float:
    """计算两个 bbox 的 IoU。"""
    x1 = max(box1[0], box2[0])
    y1 = max(box1[1], box2[1])
    x2 = min(box1[2], box2[2])
    y2 = min(box1[3], box2[3])
    if x2 <= x1 or y2 <= y1:
        return 0.0
    inter = (x2 - x1) * (y2 - y1)
    area1 = (box1[2] - box1[0]) * (box1[3] - box1[1])
    area2 = (box2[2] - box2[0]) * (box2[3] - box2[1])
    return inter / (area1 + area2 - inter + 1e-6)


def _overlap_ratio(small_box: list[int], big_box: list[int]) -> float:
    """小框在大框中的占比（小框面积中与大框重叠的比例）。"""
    x1 = max(small_box[0], big_box[0])
    y1 = max(small_box[1], big_box[1])
    x2 = min(small_box[2], big_box[2])
    y2 = min(small_box[3], big_box[3])
    if x2 <= x1 or y2 <= y1:
        return 0.0
    inter = (x2 - x1) * (y2 - y1)
    small_area = (small_box[2] - small_box[0]) * (small_box[3] - small_box[1])
    return inter / (small_area + 1e-6)


def _get_direction(box1: list[int], box2: list[int]) -> DirectionType:
    """计算 box1 相对于 box2 的方向。

    Returns: "up" / "down" / "left" / "right" / None (相交或重合)
    """
    x1, y1, x2, y2 = box1
    x3, y3, x4, y4 = box2

    cx1, cy1 = (x1 + x2) // 2, (y1 + y2) // 2
    cx2, cy2 = (x3 + x4) // 2, (y3 + y4) // 2

    # 计算重叠区域
    ox1 = max(x1, x3)
    oy1 = max(y1, y3)
    ox2 = min(x2, x4)
    oy2 = min(y2, y4)

    if ox1 < ox2 and oy1 < oy2:
        # 有重叠（相交），不判断方向，因为它们在同一个区域
        pass

    dx = cx1 - cx2  # >0 表示 box1 在 box2 右边
    dy = cy1 - cy2  # >0 表示 box1 在 box2 下边

    if abs(dx) > abs(dy):
        return "right" if dx > 0 else "left"
    elif abs(dy) > abs(dx):
        return "down" if dy > 0 else "up"
    else:
        # 对角线方向，返回主方向（哪个更大）
        if dx > 0 and dy > 0:
            return "right"
        elif dx < 0 and dy < 0:
            return "left"
        elif dx > 0 and dy < 0:
            return "right"
        else:
            return "up"


def _compute_relationships(
    elements: list[dict],
    gap_threshold: float = 1.5,
) -> dict[str, list[dict]]:
    """计算所有元素之间的拓扑关系。

    关系类型：
    - contains: A 完全包含 B（B 的 bbox 在 A 内部）- 用于父子结构推断
    - contains_within: B 完全包含 A（A 在 B 内部）- 与 contains 相反
    - adjacent: 两个 bbox 距离很近但不重叠 - 表示并列关系
    - touches: 边界接触（间隔 < box 宽度的 gap_threshold%）
      - dir: "up"/"down"/"left"/"right"

    Args:
        elements: 带有 bbox 的元素列表
        gap_threshold: 判定为 adjacent/touches 的最大间隙（box 尺寸的百分比）

    Returns:
        {element_index: [{"rel": str, "dir": str, "target": int, "gap": float, "overlap": float}]}
    """
    # 初始化关系字典
    relationships = {i: [] for i in range(len(elements))}

    gaps_thresholds_px = {}

    for i, e1 in enumerate(elements):
        box1 = e1["bbox"]
        area1 = _bbox_area(box1) if "area" not in e1 else (
            box1[2] - box1[0]) * (box1[3] - box1[1])  # type: ignore

        for j, e2 in enumerate(elements):
            if i == j:
                continue
            box2 = e2["bbox"]

            # 计算 IoU（重叠程度）
            iou_val = _iou(box1, box2)
            overlap_e1_in_e2 = _overlap_ratio(box1, box2)
            overlap_e2_in_e1 = _overlap_ratio(box2, box1)

            # 1. check contains (e2 contains e1) or contained within (e1 contains e2)
            if overlap_e1_in_e2 > 0.9:
                # e1 的绝大部分在 e2 内 -> e1 contains_within e2
                relationships[i].append({
                    "rel": "contains_within",
                    "dir": None,  # 包含没有方向
                    "target": j,
                    "overlap": overlap_e1_in_e2,
                })
            elif overlap_e2_in_e1 > 0.9:
                # e2 的绝大部分在 e1 内 -> e1 contains e2
                relationships[i].append({
                    "rel": "contains",
                    "dir": None,
                    "target": j,
                    "overlap": overlap_e2_in_e1,
                })

            # 2. check adjacent/touches (无重叠或极少重叠)
            elif iou_val < 0.05:
                # 计算最小间隙（px）
                # left/right gap
                if box1[2] <= box2[0]:  # e1 在 e2 左侧
                    min_dx = box2[0] - box1[2]
                elif box2[2] <= box1[0]:  # e1 在 e2 右侧
                    min_dx = box1[0] - box2[2]
                else:
                    min_dx = 0

                # up/down gap
                if box1[3] <= box2[1]:  # e1 在 e2 上方
                    min_dy = box2[1] - box1[3]
                elif box2[3] <= box1[1]:  # e1 在 e2 下方
                    min_dy = box1[1] - box2[3]
                else:
                    min_dy = 0

                min_gap_px = max(min_dx, min_dy) if min_dx > 0 or min_dy > 0 else 0  # type: ignore

                # check threshold (box dimension * gap_threshold / 100)
                dim_factor = max(
                    (box1[2] - box1[0]) * (box1[3] - box1[1]),
                    (box2[2] - box2[0]) * (box2[3] - box2[1]),
                )  # type: ignore
                threshold = dim_factor * gap_threshold / 100

                direction = _get_direction(box1, box2)

                if min_gap_px <= 5:
                    # touches (接触）
                    rel_type = "touches"
                elif min_gap_px <= threshold:
                    rel_type = "adjacent"
                else:
                    continue  # not close enough

                relationships[i].append({
                    "rel": rel_type,
                    "dir": direction,
                    "target": j,
                    "gap": float(min_gap_px),
                    "overlap": iou_val,
                })

    return relationships


def _bbox_center(box: list[int]) -> tuple[int, int]:
    return ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2)


def _bbox_area(box: list[int]) -> int:
    return (box[2] - box[0]) * (box[3] - box[1])


def fuse_layout(
    omniparser_elements: list[dict],
    sam3_segments: list[dict],
    img_width: int = 1920,
    img_height: int = 1080,
    iou_threshold: float = 0.3,
    overlap_threshold: float = 0.5,
) -> dict[str, object]:
    """融合 OmniParser 和 SAM3 的检测结果。

    融合规则：
    - SAM3 检测到的区域作为"骨架"，每个 SAM3 区域是一个 element
    - OmniParser 的文字框如果落在某个 SAM3 区域内（overlap > threshold），
      把文字赋给该 SAM3 区域
    - OmniParser 独有的元素（没有匹配到任何 SAM3 区域）保留为单独元素
    - SAM3 独有的区域（OmniParser 没检测到）保留为无文字元素

    Args:
        omniparser_elements: OmniParser.parse() 返回的元素列表
        sam3_segments: SAM3Analyzer.segment() 返回的分割结果
        img_width: 图片宽度
        img_height: 图片高度
        iou_threshold: IoU 匹配阈值
        overlap_threshold: 重叠占比阈值

    Returns:
        {
            "elements": list[dict],  # 融合后的元素列表
            "relationships": dict,   # 拓扑关系映射 (index -> [rel_dict])
        }
    """
    fused: list[dict] = []
    matched_omni_indices: set[int] = set()

    # 1. 遍历 SAM3 区域，尝试与 OmniParser 元素匹配
    for seg in sam3_segments:
        sam3_box = seg["box"]
        sam3_area = _bbox_area(sam3_box)

        # 过滤掉太大或太小的区域
        if sam3_area < 50:
            continue
        if sam3_area > img_width * img_height * 0.5:
            continue

        best_text = ""
        best_conf = 0.0
        best_omni_type = ""

        for i, omni_elem in enumerate(omniparser_elements):
            if i in matched_omni_indices:
                continue
            omni_box = omni_elem.get("bbox", [0, 0, 0, 0])
            if not omni_box or len(omni_box) != 4:
                continue

            # 检查两种重叠关系
            iou = _iou(sam3_box, omni_box)
            omni_in_sam3 = _overlap_ratio(omni_box, sam3_box)

            if iou > iou_threshold or omni_in_sam3 > overlap_threshold:
                # 匹配成功，取 OCR 文字
                omni_text = omni_elem.get("text", "") or ""
                omni_conf = omni_elem.get("confidence", 0.0)
                if omni_text and (not best_text or omni_conf > best_conf):
                    best_text = omni_text.strip()
                    best_conf = omni_conf
                    best_omni_type = omni_elem.get("type", "")
                matched_omni_indices.add(i)

        element = {
            "bbox": sam3_box,
            "center": _bbox_center(sam3_box),
            "text": best_text,
            "type": best_omni_type if best_text else seg.get("type", "region"),
            "source": "fused" if best_text else "sam3",
            "sam3_score": seg.get("score", 0.0),
            "ocr_confidence": best_conf if best_text else 0.0,
        }
        fused.append(element)

    # 2. 添加 OmniParser 独有的元素（未匹配到任何 SAM3 区域）
    for i, omni_elem in enumerate(omniparser_elements):
        if i in matched_omni_indices:
            continue
        omni_box = omni_elem.get("bbox", [0, 0, 0, 0])
        if not omni_box or len(omni_box) != 4:
            continue
        element = {
            "bbox": omni_box,
            "center": omni_elem.get("center", _bbox_center(omni_box)),
            "text": omni_elem.get("text", "") or "",
            "type": omni_elem.get("type", "text"),
            "source": "omniparser",
            "sam3_score": 0.0,
            "ocr_confidence": omni_elem.get("confidence", 0.0),
        }
        fused.append(element)

    # 3. 按 y 坐标排序（方便 planner 阅读）
    fused.sort(key=lambda e: (e["center"][1], e["center"][0]))

    # 4. 计算拓扑关系
    relationships = _compute_relationships(fused)

    return {
        "elements": fused,
        "relationships": relationships,
    }


def verify_icon_with_vlm(
    image: Image.Image | str,
    sam3_segments: list[dict],
    target: str,
    vlm_client,
    vlm_model: str,
    logger=None,
) -> Optional[dict]:
    """用 VLM 逐个验证 SAM3 检测到的 icon 区域。

    SAM3 和 VLM 互相验证：
    - SAM3 提供 icon 的精确位置
    - VLM 判断 icon 的语义含义
    - 两者一致才确认

    Args:
        image: 截图
        sam3_segments: SAM3 分割结果
        target: 目标图标名称（如 "Home"）
        vlm_client: OllamaClient 实例
        vlm_model: VLM 模型名
        logger: 日志器

    Returns:
        匹配的 element dict 或 None
    """
    if isinstance(image, str):
        image = Image.open(image).convert("RGB")
    elif image.mode != "RGB":
        image = image.convert("RGB")

    import io as _io

    for seg in sam3_segments:
        x1, y1, x2, y2 = seg["box"]
        w, h = x2 - x1, y2 - y1
        # icon 区域应该比较小
        if w < 10 or h < 10 or w > 200 or h > 200:
            continue
        # 过滤浏览器工具栏区域（y < 100 的都是地址栏/标签栏）
        cy = (y1 + y2) // 2
        if cy < 100:
            continue

        crop = image.crop((max(0, x1 - 5), max(0, y1 - 5), x2 + 5, y2 + 5))
        buf = _io.BytesIO()
        crop.save(buf, format="PNG")

        resp = vlm_client.chat(
            vlm_model,
            [{"role": "user", "content": (
                f"这个图标是什么？用一个英文单词回答（如 home, settings, play, pause, search, bell）。"
                f"如果是 {target} 图标，回答 YES。"
            )}],
            images=[buf.getvalue()],
        )

        resp_lower = resp.lower().strip()
        is_match = target.lower() in resp_lower or "yes" in resp_lower

        if logger:
            logger.info(
                f"  VLM 验证 icon at ({x1},{y1},{x2},{y2}): "
                f"resp={resp_lower!r} match={is_match}"
            )

        if is_match:
            cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
            return {
                "bbox": seg["box"],
                "center": (cx, cy),
                "text": target,
                "type": "icon",
                "source": "sam3+vlm_verified",
                "sam3_score": seg.get("score", 0.0),
                "vlm_response": resp_lower,
            }

    return None


def verify_color_with_vlm(
    image: Image.Image | str,
    sam3_segments: list[dict],
    target_color: str,
    vlm_client,
    vlm_model: str,
    logger=None,
) -> Optional[dict]:
    """用 VLM 逐个验证 SAM3 检测到的颜色方块区域。

    SAM3 提供 rectangle 的精确位置，VLM 判断颜色。

    Args:
        image: 截图
        sam3_segments: SAM3 分割结果
        target_color: 目标颜色（如 "red"）
        vlm_client: OllamaClient 实例
        vlm_model: VLM 模型名
        logger: 日志器

    Returns:
        匹配的 element dict 或 None
    """
    if isinstance(image, str):
        image = Image.open(image).convert("RGB")
    elif image.mode != "RGB":
        image = image.convert("RGB")

    import io as _io

    # 颜色名称中英文对照
    color_map = {
        "red": ("红", "#ff0000", "#FF0000"),
        "green": ("绿", "#00ff00", "#00FF00"),
        "blue": ("蓝", "#0000ff", "#0000FF"),
        "yellow": ("黄", "#ffff00", "#FFFF00"),
        "purple": ("紫", "#800080", "#800080"),
        "orange": ("橙", "#ffa500", "#FFA500"),
        "pink": ("粉", "#ffc0cb", "#FFC0CB"),
        "black": ("黑", "#000000", "#000000"),
        "white": ("白", "#ffffff", "#FFFFFF"),
    }
    color_aliases = color_map.get(target_color.lower(), (target_color, "", ""))

    candidates = []
    for seg in sam3_segments:
        x1, y1, x2, y2 = seg["box"]
        w, h = x2 - x1, y2 - y1
        # 颜色方块应该是接近正方形的小区域
        if w < 15 or h < 15:
            continue
        if w > 200 or h > 200:
            continue
        # 宽高比应该接近 1（颜色方块）
        aspect = w / h if h > 0 else 0
        if aspect < 0.3 or aspect > 3.0:
            continue
        # 过滤浏览器工具栏区域（y < 100 的都是地址栏/标签栏）
        cy = (y1 + y2) // 2
        if cy < 100:
            continue

        candidates.append(seg)

    if logger:
        logger.info(f"  SAM3 颜色候选区域: {len(candidates)} 个")

    # 按面积排序，优先验证面积适中的（不太大不太小）
    candidates.sort(key=lambda s: abs(_bbox_area(s["box"]) - 6400))  # 80x80=6400

    for seg in candidates:
        x1, y1, x2, y2 = seg["box"]
        crop = image.crop((x1, y1, x2, y2))
        buf = _io.BytesIO()
        crop.save(buf, format="PNG")

        resp = vlm_client.chat(
            vlm_model,
            [{"role": "user", "content": (
                f"这个方块是什么颜色？只回答颜色名称（如 red, green, blue, yellow）。"
                f"如果是 {target_color}（{color_aliases[0]}色），回答 YES。"
            )}],
            images=[buf.getvalue()],
        )

        resp_lower = resp.lower().strip()
        is_match = (
            target_color.lower() in resp_lower
            or "yes" in resp_lower
            or color_aliases[0] in resp
        )

        if logger:
            logger.info(
                f"  VLM 验证颜色 at ({x1},{y1},{x2},{y2}): "
                f"resp={resp_lower!r} match={is_match}"
            )

        if is_match:
            cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
            return {
                "bbox": seg["box"],
                "center": (cx, cy),
                "text": target_color,
                "type": "color_swatch",
                "source": "sam3+vlm_verified",
                "sam3_score": seg.get("score", 0.0),
                "vlm_response": resp_lower,
            }

    return None
