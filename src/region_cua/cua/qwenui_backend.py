"""Qwen-UI-Agent backend —— 阿里 Qwen-UI-Agent（Qwen3-VL 系）适配层。

与 trycua 的核心差异在「视觉定位」：
- trycua : UIA 控件树文本匹配（结构化、稳，不依赖 VLM）
- qwen-ui: 视觉大模型直接看截图输出目标元素像素坐标
           （Qwen-UI-Agent 论文的核心 grounding 能力，端到端 VLM 定位）

视觉推理引擎：本机 transformers 加载 MAI-UI-8B 在纯 CPU 上太慢（8B+1080p >8min），
故默认走 Ollama 的视觉模型（ROCm GPU 加速，实测 6.4s/张）。可配置：
- OLLAMA_VISION_MODEL : 视觉模型名（默认取本机可用的视觉模型）
- QWENUI_VIA           : "ollama"(默认) | "transformers"

操作执行：复用 cua-driver（PostMessage 后台，不抢前台），与 trycua 同一执行手，
保证 A/B 评测时「执行」一致，差异只落在「视觉定位」策略。
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import time
import urllib.request
from typing import Optional

from PIL import Image

from ..cua import CuaBackend, Located

# 复用 trycua 的窗口解析/执行（同一个执行手）
from .trycua_backend import TryCuaBackend


class QwenUIAgentBackend(CuaBackend):
    name = "qwen-ui"

    def __init__(
        self,
        host: str = "http://localhost:11434",
        vision_model: Optional[str] = None,
        via: Optional[str] = None,
        max_img_width: int = 1024,
        timeout: int = 60,
        bin_path: Optional[str] = None,
    ):
        self.host = host
        self.via = (via or os.environ.get("QWENUI_VIA") or "ollama").lower()
        self.max_img_width = max_img_width
        self.timeout = timeout
        # 执行手：内嵌一个 TryCuaBackend（纯执行，不做定位）
        self._exec = TryCuaBackend(bin_path=bin_path, timeout=timeout)
        # 视觉模型
        self.vision_model = vision_model or os.environ.get("OLLAMA_VISION_MODEL")
        if self.vision_model is None:
            self.vision_model = self._auto_pick_vision_model()
        # transformers 模式延迟加载（默认不用，太慢）
        self._tf_model = None

    # ------------------------------------------------------------ 视觉模型选择
    def _auto_pick_vision_model(self) -> str:
        """从 Ollama 列表里挑一个视觉定位模型。

        A/B 实测 grounding 精度：qwen3.6:latest(27b, 准) > llava:7b(不稳) > minicpm-v(拒坐标)。
        优先 qwen3.6；PaddleOCR-VL 不支持图像输入（缺 mmproj），弃用。
        """
        try:
            req = urllib.request.Request(f"{self.host}/api/tags")
            data = json.load(urllib.request.urlopen(req, timeout=10))
            models = data.get("models", [])
            # 优先 qwen3.6（本地 27b 视觉 grounding 最准）
            for pref in ("qwen3.6", "qwen2.5vl", "qwen3vl", "llava"):
                for m in models:
                    n = m.get("name", "")
                    if pref in n:
                        return n
            # 兜底：任何带 vision capability 的
            for m in models:
                if "vision" in m.get("capabilities", []):
                    return m.get("name", "")
        except Exception:
            pass
        return "llava:7b"

    # ------------------------------------------------------------ 截图
    def capture(self, shot_path: str, window_keyword: Optional[str] = None) -> str:
        return self._exec.capture(shot_path, window_keyword)

    def activate_window(self, keyword: str) -> None:
        self._exec.activate_window(keyword)

    def ensure_target(self, window_keyword: Optional[str] = None) -> None:
        self._exec.ensure_target(window_keyword)

    # ------------------------------------------------------------ 视觉定位
    def locate(self, screenshot_path: str, target_desc: str) -> Located:
        if self.via == "transformers":
            return self._locate_transformers(screenshot_path, target_desc)
        return self._locate_ollama(screenshot_path, target_desc)

    def _locate_ollama(self, screenshot_path: str, target_desc: str) -> Located:
        """Ollama 视觉模型直接输出坐标（Qwen-UI-Agent 端到端 grounding）。"""
        img = self._load_scaled(screenshot_path)
        b64 = base64.b64encode(img._raw).decode()
        # scale=1.0（喂原图），坐标即原图坐标
        scale = img._scale
        # 读原图尺寸，写进 prompt 让模型坐标对齐（VLM grounding 关键）
        from PIL import Image as _PILImage
        _ow, _oh = _PILImage.open(screenshot_path).size
        prompt = (
            f"这张截图原始尺寸 {_ow} x {_oh} 像素。\n"
            f"请查找界面元素「{target_desc}」的位置。\n"
            f"返回它中心点在这张 {_ow} x {_oh} 原图中的像素坐标。\n"
            f"返回严格 JSON：\n"
            '{"found": true, "x": 整数, "y": "整数", "description": "简短描述"}\n'
            '找不到则：{"found": false, "x": 0, "y": 0, "description": "未找到"}\n'
            f"坐标基于左上角原点(0,0)，x 在 0~{_ow}、y 在 0~{_oh} 范围内。"
            "只输出 JSON，不要其他文字。"
        )
        payload = {
            "model": self.vision_model,
            "stream": False,
            "prompt": prompt,  # /api/generate 用 prompt（不是 messages）
            "images": [b64],
        }
        t0 = time.time()
        try:
            # Ollama 0.32 视觉输入走 /api/generate 的 images 字段
            # （/api/chat 的 images 字段对视觉模型不生效，模型会说"看不到图"）
            req = urllib.request.Request(
                f"{self.host}/api/generate",
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            resp = json.load(urllib.request.urlopen(req, timeout=self.timeout))
            text = resp.get("response", "")
        except Exception as exc:
            return self._locate_regionai(screenshot_path, target_desc,
                                         reason=f"Ollama 定位失败: {exc}")
        coords = self._parse_coords(text)
        if not coords:
            return self._locate_regionai(screenshot_path, target_desc,
                                         reason=f"Ollama 解析失败 {text[:120]}")
        x, y = coords
        # 还原到原图坐标
        x, y = int(x / scale), int(y / scale)
        return Located(x=x, y=y, found=True,
                      analysis=f"qwen-ui({self.vision_model}) {time.time()-t0:.1f}s @({x},{y})")

    def _locate_regionai(self, screenshot_path: str, target_desc: str, reason: str = "") -> Located:
        """Fallback 视觉定位：region-ai 的 qwen3.x-27b（OpenAI 兼容 API）。

        本地 Ollama 视觉失败时兜底。API key 从环境变量 REGION_AI_API_KEY 读取
        （不硬编码/不落盘到 repo）。
        """
        t0 = time.time()
        api_key = os.environ.get("REGION_AI_API_KEY") or os.environ.get("REGIONAI_API_KEY")
        if not api_key:
            return Located(x=0, y=0, found=False,
                           analysis=f"qwen-ui region-ai fallback: 未设置 REGION_AI_API_KEY ({reason})")
        base = os.environ.get("REGION_AI_BASE_URL", "https://llm.region-ai.cloud/v1")
        model = os.environ.get("REGION_AI_MODEL", "qwen3.8-27b")
        from PIL import Image as _PILImage
        _ow, _oh = _PILImage.open(screenshot_path).size
        b64 = base64.b64encode(open(screenshot_path, "rb").read()).decode()
        prompt = (
            f"这张截图原始尺寸 {_ow} x {_oh} 像素。\n"
            f"请查找界面元素「{target_desc}」的位置。\n"
            f"返回它中心点在这张 {_ow} x {_oh} 原图中的像素坐标。\n"
            '返回严格 JSON：{"found": true, "x": 整数, "y": 整数, "description": "简短描述"}\n'
            '找不到则：{"found": false, "x": 0, "y": 0, "description": "未找到"}\n'
            f"坐标基于左上角原点(0,0)，x 在 0~{_ow}、y 在 0~{_oh} 范围内。只输出 JSON。"
        )
        payload = {
            "model": model,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                    {"type": "text", "text": prompt},
                ],
            }],
            "max_tokens": 128,
        }
        try:
            req = urllib.request.Request(
                f"{base}/chat/completions",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
            )
            resp = json.load(urllib.request.urlopen(req, timeout=120))
            text = resp["choices"][0]["message"]["content"]
        except Exception as exc:
            return Located(x=0, y=0, found=False,
                           analysis=f"qwen-ui region-ai fallback 失败: {exc} ({reason})")
        coords = self._parse_coords(text)
        if not coords:
            return Located(x=0, y=0, found=False,
                           analysis=f"qwen-ui region-ai 解析失败 {text[:120]} ({reason})")
        x, y = coords
        return Located(x=x, y=y, found=True,
                       analysis=f"region-ai({model}) {time.time()-t0:.1f}s @({x},{y})")

    def _locate_transformers(self, screenshot_path: str, target_desc: str) -> Located:
        """transformers 本地加载 MAI-UI-8B（慢，仅作备选）。"""
        if self._tf_model is None:
            import torch
            from transformers import AutoModelForImageTextToText, AutoProcessor

            base = os.path.expanduser(
                "~/.cache/huggingface/hub/models--Tongyi-MAI--MAI-UI-8B/snapshots"
            )
            snap = os.path.join(base, os.listdir(base)[0])
            self._tf_model, self._tf_proc = (
                AutoModelForImageTextToText.from_pretrained(snap, dtype=torch.float16).eval(),
                AutoProcessor.from_pretrained(snap),
            )
        img = Image.open(screenshot_path)
        prompt = (
            f"Find the UI element: {target_desc}. Return strict JSON "
            '{"found": true, "x": int, "y": int}. Top-left origin (0,0).'
        )
        msgs = [{"role": "user", "content": [{"type": "image", "image": img}, {"type": "text", "text": prompt}]}]
        import torch
        inp = self._tf_proc.apply_chat_template(
            msgs, add_generation_prompt=True, tokenize=True, return_dict=True, return_tensors="pt"
        ).to(self._tf_model.device)
        with torch.no_grad():
            out = self._tf_model.generate(**inp, max_new_tokens=128, do_sample=False)
        text = self._tf_proc.batch_decode(out[:, inp["input_ids"].shape[1]:], skip_special_tokens=True)[0]
        coords = self._parse_coords(text)
        return Located(*coords, found=bool(coords)) if coords else Located(0, 0, found=False, analysis=text[:120])

    @staticmethod
    def _parse_coords(text: str) -> Optional[tuple[int, int]]:
        """从模型输出里解析 JSON 坐标。"""
        t = text.strip()
        # 抽第一个 {...} JSON 块
        import re
        m = re.search(r"\{.*?\}", t, re.DOTALL)
        if m:
            try:
                d = json.loads(m.group(0))
                if d.get("found") and d.get("x") is not None:
                    return int(d["x"]), int(d["y"])
                return None
            except (json.JSONDecodeError, KeyError, ValueError):
                pass
        # 兜底：两个整数
        nums = re.findall(r"\d+", t)
        if len(nums) >= 2:
            return int(nums[0]), int(nums[1])
        return None

    def _load_scaled(self, path: str) -> "_ScaledImage":
        """读原图（不缩放）。Ollama 内部会 resize，缩放反而破坏坐标校准。

        返回 scale=1.0（坐标即原图坐标），raw=原图 PNG bytes。
        """
        img = Image.open(path).convert("RGB")
        import io
        buf = io.BytesIO()
        img.save(buf, "PNG")
        return _ScaledImage(raw=buf.getvalue(), scale=1.0)

    # ------------------------------------------------------------ 操作（委托执行手）
    def click(self, x, y, button="left", clicks=1) -> None:
        self._exec.click(x, y, button, clicks)

    def _type_native(self, text: str) -> None:
        self._exec._type_native(text)

    def hotkey(self, *keys) -> None:
        self._exec.hotkey(*keys)

    def scroll(self, amount: int) -> None:
        self._exec.scroll(amount)

    def close(self) -> None:
        pass


class _ScaledImage:
    def __init__(self, raw: bytes, scale: float):
        self._raw = raw
        self._scale = scale
