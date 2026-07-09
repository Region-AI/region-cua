"""轻量级布局分析器：在 OmniParser 元素列表上做空间聚类和布局推理。

不依赖额外模型，只用几何关系推断 UI 布局结构：
1. 空间聚类：把距离相近的元素分组
2. 布局检测：网格/列表/导航栏/工具栏
3. 区域语义推断：年份列表/月份网格/滚动区域
4. 滚动检测：检测被截断的元素（说明有滚动条）

用法：
    from region_cua.vision.layout_analyzer import analyze_layout
    regions = analyze_layout(elements, image_width, image_height)
    # regions = [{"type": "grid", "elements": [...], "bbox": [...], "rows": 3, "cols": 4}]
"""

from __future__ import annotations

import math
from typing import Optional


def _distance(e1: dict, e2: dict) -> float:
    """两个元素中心点的欧氏距离。"""
    cx1, cy1 = e1["center"]
    cx2, cy2 = e2["center"]
    return math.sqrt((cx1 - cx2) ** 2 + (cy1 - cy2) ** 2)


def _bbox_of_elements(elements: list[dict]) -> tuple[int, int, int, int]:
    """计算元素列表的整体 bbox。"""
    if not elements:
        return (0, 0, 0, 0)
    x1 = min(e["bbox"][0] for e in elements)
    y1 = min(e["bbox"][1] for e in elements)
    x2 = max(e["bbox"][2] for e in elements)
    y2 = max(e["bbox"][3] for e in elements)
    return (x1, y1, x2, y2)


def _cluster_elements(elements: list[dict], max_gap: int = 60) -> list[list[dict]]:
    """按空间距离聚类元素。

    两个元素中心距离 < max_gap 时归为同一组。
    """
    if not elements:
        return []
    clusters = [[elements[0]]]
    for e in elements[1:]:
        assigned = False
        for cluster in clusters:
            # 和簇中任意元素距离足够近就加入
            for ce in cluster:
                if _distance(e, ce) < max_gap:
                    cluster.append(e)
                    assigned = True
                    break
            if assigned:
                break
        if not assigned:
            clusters.append([e])
    return clusters


def _detect_grid(elements: list[dict]) -> Optional[dict]:
    """检测元素是否构成网格布局。

    网格特征：元素按行列对齐，行间距和列间距大致相等。
    """
    if len(elements) < 4:
        return None

    # 按 y 坐标排序，分行
    sorted_by_y = sorted(elements, key=lambda e: e["center"][1])
    rows = []
    current_row = [sorted_by_y[0]]
    for e in sorted_by_y[1:]:
        # y 差距 < 20 视为同一行
        if abs(e["center"][1] - current_row[0]["center"][1]) < 20:
            current_row.append(e)
        else:
            rows.append(current_row)
            current_row = [e]
    rows.append(current_row)

    # 至少 2 行 2 列才算网格
    if len(rows) < 2:
        return None
    cols = max(len(r) for r in rows)
    if cols < 2:
        return None

    # 检查列对齐：每行元素按 x 排序，列间距应该一致
    for row in rows:
        row.sort(key=lambda e: e["center"][0])

    # 计算平均列间距
    col_gaps = []
    for row in rows:
        for i in range(len(row) - 1):
            gap = row[i + 1]["center"][0] - row[i]["center"][0]
            col_gaps.append(gap)
    if not col_gaps:
        return None
    avg_gap = sum(col_gaps) / len(col_gaps)
    # 列间距方差不能太大
    if avg_gap < 10:
        return None

    return {
        "type": "grid",
        "elements": elements,
        "bbox": _bbox_of_elements(elements),
        "rows": len(rows),
        "cols": cols,
        "avg_col_gap": avg_gap,
    }


def _detect_list(elements: list[dict]) -> Optional[dict]:
    """检测元素是否构成列表布局（纵向排列）。

    列表特征：元素 x 坐标接近，y 坐标递增，间距大致相等。
    """
    if len(elements) < 3:
        return None

    # 按 y 排序
    sorted_by_y = sorted(elements, key=lambda e: e["center"][1])

    # 检查 x 坐标是否接近（同一列）
    xs = [e["center"][0] for e in sorted_by_y]
    x_range = max(xs) - min(xs)
    if x_range > 50:  # x 跨度太大，不是列表
        return None

    # 检查 y 间距是否大致均匀
    y_gaps = []
    for i in range(len(sorted_by_y) - 1):
        gap = sorted_by_y[i + 1]["center"][1] - sorted_by_y[i]["center"][1]
        y_gaps.append(gap)
    avg_gap = sum(y_gaps) / len(y_gaps)
    if avg_gap < 5:
        return None

    return {
        "type": "list",
        "elements": sorted_by_y,
        "bbox": _bbox_of_elements(elements),
        "count": len(elements),
        "avg_y_gap": avg_gap,
    }


def _detect_scrollbar(elements: list[dict], img_w: int, img_h: int) -> list[dict]:
    """检测可能的滚动条区域。

    滚动条特征：右侧或底部有细长的无文字元素。
    """
    scrollbars = []
    for e in elements:
        if e.get("text"):
            continue  # 滚动条没有文字
        x1, y1, x2, y2 = e["bbox"]
        w = x2 - x1
        h = y2 - y1
        # 垂直滚动条：高度 > 宽度 * 3
        if h > w * 3 and h > 100:
            scrollbars.append({
                "type": "scrollbar_vertical",
                "bbox": e["bbox"],
                "center": e["center"],
                "element": e,
            })
        # 水平滚动条：宽度 > 高度 * 3
        elif w > h * 3 and w > 100:
            scrollbars.append({
                "type": "scrollbar_horizontal",
                "bbox": e["bbox"],
                "center": e["center"],
                "element": e,
            })
    return scrollbars


def analyze_layout(
    elements: list[dict],
    img_w: int = 1920,
    img_h: int = 1080,
) -> dict:
    """分析元素列表的布局结构。

    Returns:
        {
            "regions": [...],      # 语义区域列表
            "scrollbars": [...],   # 滚动条列表
            "grids": [...],        # 网格布局列表
            "lists": [...],        # 列表布局列表
        }
    """
    # 过滤掉浏览器工具栏等无关元素
    content_elements = [
        e for e in elements
        if e.get("center", (0, 0))[1] > 80  # 排除顶部工具栏
        and e.get("center", (0, 0))[0] < img_w - 10  # 排除右侧边缘
    ]

    # 1. 检测滚动条
    scrollbars = _detect_scrollbar(elements, img_w, img_h)

    # 2. 空间聚类
    clusters = _cluster_elements(content_elements, max_gap=80)

    # 3. 对每个聚类检测布局类型
    grids = []
    lists = []
    regions = []
    for cluster in clusters:
        if len(cluster) < 2:
            continue
        grid = _detect_grid(cluster)
        if grid:
            grids.append(grid)
            regions.append(grid)
            continue
        lst = _detect_list(cluster)
        if lst:
            lists.append(lst)
            regions.append(lst)

    return {
        "regions": regions,
        "scrollbars": scrollbars,
        "grids": grids,
        "lists": lists,
    }


def find_scrollable_region(
    elements: list[dict],
    img_w: int = 1920,
    img_h: int = 1080,
) -> Optional[dict]:
    """找到可滚动区域（有滚动条的区域）。

    Returns:
        {"scrollbar": {...}, "content_region": {...}} 或 None
    """
    layout = analyze_layout(elements, img_w, img_h)
    if not layout["scrollbars"]:
        return None

    for sb in layout["scrollbars"]:
        sb_x, sb_y = sb["center"]
        # 垂直滚动条：内容在其左侧
        if sb["type"] == "scrollbar_vertical":
            # 找滚动条左侧最近的列表或网格
            for lst in layout["lists"]:
                lst_x2 = lst["bbox"][2]
                if abs(lst_x2 - sb_x) < 50 and lst["bbox"][1] < sb_y < lst["bbox"][3]:
                    return {"scrollbar": sb, "content_region": lst}
            for grid in layout["grids"]:
                grid_x2 = grid["bbox"][2]
                if abs(grid_x2 - sb_x) < 50 and grid["bbox"][1] < sb_y < grid["bbox"][3]:
                    return {"scrollbar": sb, "content_region": grid}

    return None
