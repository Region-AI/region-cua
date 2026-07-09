"""OmniParser 精简版：YOLO 检测 UI 元素 + OCR 识别文字 → 结构化元素列表。

不需要 VLM/LLM。输出纯文本元素列表，供文字 LLM 或简单匹配使用。

架构：
  截图 → YOLO（检测按钮/图标/输入框边界框）
       → PaddleOCR（识别文字内容 + 位置）
       → 合并去重 → 元素列表 [{id, text, type, bbox:[x1,y1,x2,y2]}]

用法：
  parser = OmniParser()
  elements = parser.parse("screenshot.png")
  # elements = [
  #   {"id": 0, "text": "Submit", "type": "button", "bbox": [120,200,180,230]},
  #   {"id": 1, "text": "Cancel", "type": "button", "bbox": [220,200,280,230]},
  #   ...
  # ]
  # 点击：取 elements[0]["bbox"] 中心点
"""

from __future__ import annotations

import io
import os
from pathlib import Path
from typing import Optional

# 模型缓存目录
_MODEL_DIR = Path(os.environ.get("OMNIPARSER_WEIGHTS", Path.home() / ".cache" / "omniparser"))
_MODEL_DIR.mkdir(parents=True, exist_ok=True)

# 模型全局单例（避免重复加载）
_yolo_model = None
_ocr_engine = None


def _get_yolo_model():
    """加载 YOLO UI 元素检测模型（OmniParser V2 的 icon_detect）。"""
    global _yolo_model
    if _yolo_model is not None:
        return _yolo_model

    from ultralytics import YOLO

    model_path = _MODEL_DIR / "icon_detect" / "model.pt"
    if not model_path.exists():
        model_path = _download_yolo_weights()

    _yolo_model = YOLO(str(model_path))
    return _yolo_model


def _download_yolo_weights() -> Path:
    """从 HuggingFace 下载 OmniParser V2 的 YOLO 权重。"""
    import urllib.request

    model_dir = _MODEL_DIR / "icon_detect"
    model_dir.mkdir(parents=True, exist_ok=True)
    model_path = model_dir / "model.pt"

    urls = [
        "https://huggingface.co/microsoft/OmniParser-v2.0/resolve/main/icon_detect/model.pt",
        "https://hf-mirror.com/microsoft/OmniParser-v2.0/resolve/main/icon_detect/model.pt",
    ]

    for url in urls:
        try:
            print(f"下载 OmniParser YOLO 权重: {url}")
            urllib.request.urlretrieve(url, model_path)
            if model_path.stat().st_size > 1_000_000:  # 至少 1MB
                print(f"下载完成: {model_path} ({model_path.stat().st_size // 1024 // 1024}MB)")
                return model_path
        except Exception as exc:
            print(f"下载失败: {exc}")

    raise RuntimeError(
        f"无法下载 OmniParser YOLO 权重。请手动下载 model.pt 到 {model_path}\n"
        f"下载地址: https://huggingface.co/microsoft/OmniParser-v2.0/tree/main/icon_detect"
    )


def _get_ocr_engine():
    """加载 OCR 引擎（优先 EasyOCR，PaddleOCR 3.x 在 Windows 有 oneDNN bug）。

    OmniParser 原始代码同时支持 EasyOCR 和 PaddleOCR，这里用 EasyOCR 更稳定。
    """
    global _ocr_engine
    if _ocr_engine is not None:
        return _ocr_engine

    try:
        import easyocr
        # 只用英文模型（中文模型 ch_sim 约 500MB，下载慢）
        # 如果需要中文支持，改为 ['ch_sim', 'en']
        lang = os.environ.get("OMNIPARSER_OCR_LANG", "en").split(",")
        _ocr_engine = {"engine": "easyocr", "reader": easyocr.Reader(lang, gpu=False, verbose=False)}
        return _ocr_engine
    except Exception as exc:
        raise RuntimeError(f"EasyOCR 加载失败: {exc}\n请安装: uv pip install easyocr")


def _bbox_center(bbox: list[int]) -> tuple[int, int]:
    """计算边界框中心点。"""
    x1, y1, x2, y2 = bbox
    return (x1 + x2) // 2, (y1 + y2) // 2


def _bbox_area(bbox: list[int]) -> int:
    x1, y1, x2, y2 = bbox
    return max(0, x2 - x1) * max(0, y2 - y1)


def _iou(box1: list[int], box2: list[int]) -> float:
    """计算两个边界框的 IoU。"""
    x1 = max(box1[0], box2[0])
    y1 = max(box1[1], box2[1])
    x2 = min(box1[2], box2[2])
    y2 = min(box1[3], box2[3])
    if x2 <= x1 or y2 <= y1:
        return 0.0
    inter = (x2 - x1) * (y2 - y1)
    area1 = _bbox_area(box1)
    area2 = _bbox_area(box2)
    union = area1 + area2 - inter
    return inter / union if union > 0 else 0.0


def _is_inside(inner: list[int], outer: list[int]) -> bool:
    """inner 是否大部分在 outer 内。"""
    x1 = max(inner[0], outer[0])
    y1 = max(inner[1], outer[1])
    x2 = min(inner[2], outer[2])
    y2 = min(inner[3], outer[3])
    if x2 <= x1 or y2 <= y1:
        return False
    inter = (x2 - x1) * (y2 - y1)
    return inter > 0.7 * _bbox_area(inner)


class OmniParser:
    """截图解析器：YOLO + OCR → 结构化元素列表。"""

    def __init__(self, box_threshold: float = 0.05, iou_threshold: float = 0.1,
                 enable_vlm_icons: bool = False):
        self.box_threshold = box_threshold
        self.iou_threshold = iou_threshold
        self.enable_vlm_icons = enable_vlm_icons  # VLM 图标识别开关

    def parse(self, image) -> list[dict]:
        """解析截图，返回元素列表。

        Args:
            image: PIL.Image 或文件路径

        Returns:
            [{"id": 0, "text": "Submit", "type": "button", "bbox": [x1,y1,x2,y2]}, ...]
        """
        from PIL import Image
        import numpy as np

        if isinstance(image, (str, Path)):
            image = Image.open(image)
        image = image.convert("RGB")
        w, h = image.size
        img_array = np.array(image)

        # 1. YOLO 检测 UI 元素
        icon_elements = self._detect_icons(image)

        # 2. OCR 识别文字
        text_elements = self._detect_text(img_array)

        # 3. 合并去重
        elements = self._merge_elements(icon_elements, text_elements, w, h)

        # 4. VLM 批量识别无文字图标（可选，默认关闭避免 Ollama 模型切换冲突）
        if self.enable_vlm_icons:
            self._vlm_label_icons(elements, image)

        # 5. 编号
        for i, elem in enumerate(elements):
            elem["id"] = i
            elem["center"] = _bbox_center(elem["bbox"])

        return elements

    def _detect_icons(self, image) -> list[dict]:
        """用 YOLO 检测 UI 元素（按钮、图标、输入框等）。"""
        model = _get_yolo_model()
        result = model.predict(
            source=image,
            conf=self.box_threshold,
            iou=self.iou_threshold,
            verbose=False,
        )
        if not result or len(result[0].boxes) == 0:
            return []

        boxes = result[0].boxes.xyxy.tolist()  # 像素坐标
        confs = result[0].boxes.conf.tolist()

        elements = []
        for box, conf in zip(boxes, confs):
            x1, y1, x2, y2 = [int(v) for v in box]
            if _bbox_area([x1, y1, x2, y2]) < 10:  # 过滤太小的
                continue
            elements.append({
                "text": "",
                "type": "icon",
                "bbox": [x1, y1, x2, y2],
                "confidence": round(conf, 3),
            })
        return elements

    def _detect_text(self, img_array) -> list[dict]:
        """用 EasyOCR 识别文字。"""
        engine = _get_ocr_engine()
        if engine["engine"] == "easyocr":
            reader = engine["reader"]
            try:
                # 降低阈值以识别小字体按钮文字（默认 text_threshold=0.7 太高）
                results = reader.readtext(
                    img_array,
                    text_threshold=0.3,
                    low_text=0.3,
                    link_threshold=0.3,
                )
            except Exception:
                return []
            # EasyOCR 返回: [(bbox_points, text, confidence), ...]
            # bbox_points = [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
            elements = []
            for bbox_points, text, conf in results:
                xs = [p[0] for p in bbox_points]
                ys = [p[1] for p in bbox_points]
                x1, y1, x2, y2 = int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))
                if _bbox_area([x1, y1, x2, y2]) < 5:
                    continue
                elements.append({
                    "text": text.strip(),
                    "type": "text",
                    "bbox": [x1, y1, x2, y2],
                    "confidence": round(float(conf), 3),
                })
            return elements
        return []

    def _merge_elements(self, icons: list[dict], texts: list[dict], w: int, h: int) -> list[dict]:
        """合并 YOLO 和 OCR 结果，去重。

        规则：
        - OCR 文字框如果大部分在 YOLO 图标框内 → 合并（图标框获得文字内容）
        - 否则各自保留
        """
        merged = []

        # 给每个图标框匹配 OCR 文字
        icon_used = [False] * len(icons)
        for text_elem in texts:
            absorbed = False
            for i, icon_elem in enumerate(icons):
                if icon_used[i]:
                    continue
                if _is_inside(text_elem["bbox"], icon_elem["bbox"]) or _iou(text_elem["bbox"], icon_elem["bbox"]) > 0.3:
                    # OCR 文字在图标框内 → 合并（图标框获得文字内容）
                    icon_elem["text"] = text_elem["text"]
                    icon_elem["type"] = "button" if text_elem["text"] else "icon"
                    icon_used[i] = True
                    absorbed = True
                    break
            if not absorbed:
                # OCR 文字不在任何图标框内 → 作为独立文字元素保留
                merged.append(text_elem)

        # 加上所有图标框（包括合并了文字的）
        for i, icon_elem in enumerate(icons):
            merged.append(icon_elem)

        # 按位置排序（从上到下，从左到右）
        merged.sort(key=lambda e: (e["bbox"][1], e["bbox"][0]))
        return merged

    def find_element(self, elements: list[dict], description: str,
                     screenshot_path: str = "") -> Optional[dict]:
        """从元素列表中按描述查找最匹配的元素。

        OCR 文字和 VLM 图标描述在 parse() 阶段已合并到 elements 的 text 字段，
        这里统一做文字匹配。

        Args:
            elements: parse() 返回的元素列表
            description: 要查找的元素描述
            screenshot_path: 保留参数兼容旧调用（不再使用）
        """
        import re as _re
        desc = description.lower().strip()

        # 提取括号里的英文关键词
        paren_match = _re.search(r'\(([^)]+)\)', desc)
        if paren_match:
            desc = paren_match.group(1).strip()

        # 提取引号里的内容
        quote_match = _re.search(r"['\"]([^'\"]+)['\"]", desc)
        if quote_match:
            desc = quote_match.group(1).strip()

        # 去掉常见无意义词（用单词边界匹配，避免破坏其他单词）
        for word in ["按钮", "输入框", "图标", "链接", "菜单", "包含文本", "的",
                      "区域", "控件", "选项", "目标", "下拉", "复选框", "单选",
                      "单元格", "开关", "滑块"]:
            desc = desc.replace(word, "").strip()
        # 英文去词用单词边界（避免 "a" 破坏 "Username"）
        for word in [r"\bbutton\b", r"\binput\b", r"\bicon\b", r"\blink\b",
                      r"\bmenu\b", r"\bthe\b", r"\ba\b", r"\bfield\b",
                      r"\boption\b", r"\belement\b", r"\btext area\b",
                      r"\bcheckbox\b", r"\bradio\b", r"\bdropdown\b",
                      r"\bcell\b", r"\bswitch\b", r"\btoggle\b", r"\bslider\b"]:
            desc = _re.sub(word, "", desc, flags=_re.IGNORECASE).strip()
            desc = _re.sub(r'\s+', ' ', desc).strip()

        if not desc:
            return None

        # 中英文按钮名称对照
        cn_en_map = {
            "提交": "submit", "取消": "cancel", "确定": "ok", "确认": "confirm",
            "保存": "save", "删除": "delete", "关闭": "close", "搜索": "search",
            "登录": "login", "登出": "logout", "注册": "register", "重置": "reset",
            "下一步": "next", "上一步": "back", "previous": "back",
            "开始": "start", "停止": "stop", "播放": "play", "暂停": "pause",
            "继续": "continue", "完成": "done", "返回": "back",
            "姓名": "name", "邮箱": "email", "年龄": "age", "国家": "country",
            "性别": "gender", "评论": "comments", "订阅": "subscribe",
            "音量": "volume", "亮度": "brightness", "温度": "temperature",
        }
        if desc in cn_en_map:
            desc = cn_en_map[desc]

        best = None
        best_score = 0
        desc_norm = _re.sub(r'[^a-z0-9\u4e00-\u9fff]', '', desc)
        for elem in elements:
            text = elem.get("text", "").lower().strip()
            if not text:
                continue
            # 降权页面标题和提示文字（长文字通常不是可交互控件）
            # 但不跳过，因为某些 placeholder 可能需要匹配
            text_len_penalty = 1.0
            if len(text) > 15 and elem.get("type", "") in ("text", ""):
                text_len_penalty = 0.3  # 长文字降权 70%
            # 页面标题（h1 在页面顶部）进一步降权——只对 text 类型，不对 button
            if (elem.get("center", (0, 0))[1] < 200
                    and len(text) > 5
                    and elem.get("type", "") in ("text", "")):
                text_len_penalty *= 0.1  # 标题区域大幅降权
            # 完全匹配（不受降权影响）
            if text == desc:
                return elem
            # 纯数字描述：只匹配纯数字元素
            if desc.isdigit() and text.isdigit() and text == desc:
                return elem
            # 归一化匹配（不受降权影响）
            text_norm = _re.sub(r'[^a-z0-9\u4e00-\u9fff]', '', text)
            if desc_norm and text_norm == desc_norm:
                return elem
            # 子串匹配（OCR 可能误读，如 "Submit Form" -> "Ibmit Form"）
            # 检查 desc 的关键词是否都在 text 中（允许 OCR 字符替换）
            if desc_norm and len(desc_norm) > 3:
                # 取 desc 的后半部分（OCR 常误读前几个字符）
                desc_tail = desc_norm[len(desc_norm)//3:]
                if desc_tail in text_norm:
                    score = len(desc_tail) / max(len(text_norm), 1) * text_len_penalty
                    if score > best_score and score > 0.2:
                        best_score = score
                        best = elem
            # 纯数字描述不参与模糊匹配（避免 "15" 匹配到含 15 的长文字）
            if desc.isdigit():
                continue  # 纯数字已在上面精确匹配处理
            if desc_norm and desc_norm in text_norm:
                score = len(desc_norm) / max(len(text_norm), 1) * text_len_penalty
                if score > best_score:
                    best_score = score
                    best = elem
            elif text_norm and text_norm in desc_norm:
                score = len(text_norm) / max(len(desc_norm), 1) * text_len_penalty
                if score > best_score:
                    best_score = score
                    best = elem
            # 包含匹配（要求相似度 > 0.5，避免 "Contact Form" 匹配 "Submit Form"）
            if desc in text:
                score = len(desc) / max(len(text), 1) * text_len_penalty
                if score > best_score and score > 0.4:
                    best_score = score
                    best = elem
            elif text in desc:
                score = len(text) / max(len(desc), 1) * text_len_penalty
                if score > best_score and score > 0.5:
                    best_score = score
                    best = elem
            # 词级匹配
            desc_words = set(desc.split())
            text_words = set(text.split())
            if desc_words & text_words:
                score = len(desc_words & text_words) / max(len(desc_words), 1) * text_len_penalty
                if score > best_score and score > 0.3:
                    best_score = score
                    best = elem

        # 最低分数阈值：如果最佳匹配分数太低，返回 None 避免误匹配
        if best_score < 0.15:
            return None
        return best

    def _vlm_label_icons(self, elements: list[dict], source_image) -> None:
        """批量识别无文字图标，给它们补充文字描述。

        把所有无文字的图标元素裁剪成一张拼图，一次 VLM 调用识别所有图标。
        结果直接写回 elements[i]["text"]。
        """
        # 筛选无文字的图标元素（面积合理，在页面内容区）
        icon_indices = []
        for i, e in enumerate(elements):
            if not e.get("text") and _bbox_area(e["bbox"]) > 200 and e["bbox"][1] > 80:
                icon_indices.append(i)

        if not icon_indices:
            return

        # 最多取 12 个（避免拼图太大）
        icon_indices = icon_indices[:12]
        if len(icon_indices) < 2:
            return  # 只有一两个图标不值得调 VLM

        try:
            import io as _io
            import base64
            from PIL import Image, ImageDraw
            from ..vision.ollama_client import OllamaClient
            from ..config import get_settings
        except ImportError:
            return

        try:
            settings = get_settings()
            client = OllamaClient(settings.ollama_host, settings.ollama_timeout)
            vlm_model = "qwen3.5:latest"

            # 裁剪每个图标，拼成网格图
            if isinstance(source_image, (str, Path)):
                source_image = Image.open(source_image)
            img = source_image.convert("RGB")

            crops = []
            for idx in icon_indices:
                x1, y1, x2, y2 = elements[idx]["bbox"]
                crop = img.crop((max(0, x1-5), max(0, y1-5),
                                min(img.width, x2+5), min(img.height, y2+5)))
                crop = crop.resize((80, 80))
                crops.append((idx, crop))

            # 拼成 4 列网格，加编号
            cols = 4
            rows = (len(crops) + cols - 1) // cols
            grid = Image.new("RGB", (cols * 90, rows * 90), (255, 255, 255))
            draw = ImageDraw.Draw(grid)
            for i, (idx, crop) in enumerate(crops):
                col = i % cols
                row = i // cols
                x = col * 90 + 5
                y = row * 90 + 5
                grid.paste(crop, (x, y))
                draw.text((x, y + 82), str(i), fill="red")

            # 发给 VLM
            buf = _io.BytesIO()
            grid.save(buf, format="PNG")
            prompt = (
                "以下是截图中检测到的一系列图标，每个图标有编号（红色数字，从0开始）。\n"
                "请逐一识别每个图标是什么（如 play、pause、home、settings、search、volume 等），\n"
                "返回 JSON 数组，如 [\"play\", \"settings\", \"home\"]。\n"
                "如果某个图标无法识别，对应位置返回 null。只返回 JSON，不要其他文字。"
            )

            resp = client.chat(
                vlm_model,
                [{"role": "user", "content": prompt}],
                images=[buf.getvalue()],
            )
            client.close()

            # 解析 VLM 返回的 JSON 数组
            import json
            import re as _re
            # 提取 JSON 数组
            match = _re.search(r'\[.*?\]', resp, _re.DOTALL)
            if not match:
                return
            labels = json.loads(match.group(0))

            # 写回 elements
            for i, (idx, _) in enumerate(crops):
                if i < len(labels) and labels[i]:
                    elements[idx]["text"] = str(labels[i]).strip().lower()
                    elements[idx]["type"] = "icon_labeled"

        except Exception:
            pass  # VLM 识别失败不影响主流程

    def parse_and_find(self, image, description: str) -> Optional[tuple[int, int]]:
        """一步到位：解析截图 + 查找元素 → 返回中心坐标。"""
        elements = self.parse(image)
        elem = self.find_element(elements, description)
        if elem:
            return _bbox_center(elem["bbox"])
        return None
