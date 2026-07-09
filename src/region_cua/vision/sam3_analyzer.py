"""SAM3 区域分割分析器：用文本提示分割 UI 元素。

SAM3 支持文本提示（如 "button"、"scrollbar"、"calendar"），
输出所有匹配对象的 mask 和 bbox。

在 RegionCUA 中用于：
1. OmniParser 检测不到的元素（滚动条、日历区域）
2. 复杂控件工作流中的区域理解
3. 补充 YOLO 漏检的 UI 元素

用法：
    analyzer = SAM3Analyzer()
    results = analyzer.segment(image, "scrollbar")
    # results = [{"score": 0.85, "box": [x1,y1,x2,y2], "mask": np.array}]
"""

from __future__ import annotations

import sys
import time
from typing import Optional

# 清除 Hermes 环境污染
sys.path = [p for p in sys.path if "hermes" not in p.lower()]

import torch
from PIL import Image

_MODEL = None
_PROCESSOR = None
_MODEL_PATH = "models/sam3"


class SAM3Analyzer:
    """SAM3 文本提示分割分析器。"""

    def __init__(self, model_path: str = _MODEL_PATH, lazy_load: bool = True):
        self.model_path = model_path
        self._loaded = False
        if not lazy_load:
            self._load()

    def _load(self):
        """加载模型（约 0.5 秒，内存映射）。"""
        global _MODEL, _PROCESSOR
        if _MODEL is not None:
            self.model = _MODEL
            self.processor = _PROCESSOR
            self._loaded = True
            return

        from transformers import Sam3Model, Sam3Processor

        self.model = Sam3Model.from_pretrained(
            self.model_path, torch_dtype=torch.float32
        )
        self.model.eval()
        self.processor = Sam3Processor.from_pretrained(self.model_path)
        _MODEL = self.model
        _PROCESSOR = self.processor
        self._loaded = True

    def segment(
        self,
        image: Image.Image | str,
        prompt: str,
        threshold: float = 0.5,
    ) -> list[dict]:
        """用文本提示分割图片中的对象。

        Args:
            image: PIL Image 或图片路径
            prompt: 文本提示（如 "button", "scrollbar", "calendar"）
            threshold: 置信度阈值

        Returns:
            [{"score": float, "box": [x1,y1,x2,y2], "mask": np.ndarray}]
        """
        if not self._loaded:
            self._load()

        if isinstance(image, str):
            image = Image.open(image).convert("RGB")
        elif image.mode != "RGB":
            image = image.convert("RGB")

        inputs = self.processor(images=image, text=prompt, return_tensors="pt")
        with torch.no_grad():
            outputs = self.model(**inputs)

        results = self.processor.post_process_instance_segmentation(
            outputs,
            threshold=threshold,
            mask_threshold=0.5,
            target_sizes=inputs.get("original_sizes").tolist(),
        )[0]

        segments = []
        for i in range(len(results["masks"])):
            segments.append({
                "score": float(results["scores"][i]),
                "box": [int(v) for v in results["boxes"][i].tolist()],
                "mask": results["masks"][i].numpy(),
            })
        return segments

    def segment_multi(
        self,
        image: Image.Image | str,
        prompts: list[str],
        threshold: float = 0.5,
    ) -> dict[str, list[dict]]:
        """用多个文本提示分割图片，返回按提示分组的结果。

        每个提示需要一次推理（约 9 秒），所以多提示时注意耗时。
        """
        results = {}
        for prompt in prompts:
            segs = self.segment(image, prompt, threshold)
            if segs:
                results[prompt] = segs
        return results

    def find_region(
        self,
        image: Image.Image | str,
        prompt: str,
        threshold: float = 0.5,
    ) -> Optional[dict]:
        """找到置信度最高的单个区域。

        Returns:
            {"score": float, "box": [x1,y1,x2,y2], "center": (x,y)} 或 None
        """
        segments = self.segment(image, prompt, threshold)
        if not segments:
            return None
        best = max(segments, key=lambda s: s["score"])
        x1, y1, x2, y2 = best["box"]
        best["center"] = ((x1 + x2) // 2, (y1 + y2) // 2)
        return best
