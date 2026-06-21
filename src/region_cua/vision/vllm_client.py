"""vLLM 客户端：通过 OpenAI 兼容接口调用 vLLM 视觉模型。

vLLM 提供 OpenAI 兼容的 /v1/chat/completions 端点，
请求/响应格式与 OpenAI API 一致，支持多模态（文字 + base64 图片）。
"""

from __future__ import annotations

import base64
import io
import json
from pathlib import Path
from typing import Any, Iterable

import httpx


class VLLMError(RuntimeError):
    """vLLM 调用异常。"""


class VLLMClient:
    def __init__(self, host: str = "http://localhost:8000", timeout: int = 600):
        self.host = host.rstrip("/")
        self.timeout = timeout
        self._client = httpx.Client(timeout=timeout)

    # ------------------------------------------------------------------ chat
    def chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        images: Iterable[Any] | None = None,
        think: bool = False,
    ) -> str:
        """调用 /v1/chat/completions，返回 assistant 文本内容。

        images 可为：文件路径(str)、bytes、PIL.Image.Image 的任意混合。
        """
        body = self._build_body(model, messages, images)
        try:
            resp = self._client.post(f"{self.host}/v1/chat/completions", json=body)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise VLLMError(f"vLLM 请求失败: {exc}") from exc

        try:
            data = resp.json()
        except json.JSONDecodeError as exc:
            raise VLLMError(f"vLLM 返回非 JSON: {exc}") from exc

        choices = data.get("choices") or []
        if not choices:
            raise VLLMError("vLLM 返回 choices 为空")

        content = (choices[0].get("message") or {}).get("content")
        if content is None:
            content = ""
        return str(content)

    def _build_body(
        self,
        model: str,
        messages: list[dict[str, Any]],
        images: Iterable[Any] | None = None,
    ) -> dict[str, Any]:
        """组装 OpenAI 兼容的请求体，支持多模态 content 数组。"""
        openai_messages: list[dict[str, Any]] = []
        for msg in messages:
            role = msg.get("role", "user")
            text = msg.get("content", "")
            entry: dict[str, Any] = {"role": role}

            if images:
                parts: list[dict[str, Any]] = [{"type": "text", "text": text}]
                for img in images:
                    b64 = self._to_b64(img)
                    parts.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{b64}"},
                    })
                entry["content"] = parts
            else:
                entry["content"] = text
            openai_messages.append(entry)

        return {
            "model": model,
            "messages": openai_messages,
            "stream": False,
        }

    # --------------------------------------------------------------- helpers
    @staticmethod
    def _to_b64(img: Any) -> str:
        if isinstance(img, (bytes, bytearray)):
            return base64.b64encode(img).decode()
        if isinstance(img, str):
            return base64.b64encode(Path(img).read_bytes()).decode()
        try:
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return base64.b64encode(buf.getvalue()).decode()
        except AttributeError:
            raise VLLMError(f"不支持的图片类型: {type(img)!r}")

    def list_models(self) -> list[dict[str, Any]]:
        try:
            resp = self._client.get(f"{self.host}/v1/models")
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise VLLMError(f"获取模型列表失败: {exc}") from exc
        return resp.json().get("data", []) or []

    def close(self) -> None:
        self._client.close()
