"""Ollama 客户端：调用本地视觉/文本模型。

关键避坑（来自过往调试记录）：
- httpx 超时设为 600s：模型未驻留 VRAM 时从磁盘加载需数十秒。
- 同时用 body `stream:false` 与 header `Ollama-No-Stream:true`，避免模型
  开启 long thinking 后非流式请求长时间阻塞、进程假死。
- 返回内容统一做 null/空字符串容错。
"""

from __future__ import annotations

import base64
import io
import json
from pathlib import Path
from typing import Any, Iterable

import httpx


class OllamaError(RuntimeError):
    """Ollama 调用异常。"""


class OllamaClient:
    def __init__(self, host: str = "http://localhost:11434", timeout: int = 600):
        self.host = self._normalize_host(host)
        self.timeout = timeout
        self._client = httpx.Client(timeout=timeout)
        # 经验性规避：某些模型开启 thinking 后非流式仍阻塞，加该头确保立即返回。
        self._client.headers["Ollama-No-Stream"] = "true"

    @staticmethod
    def _normalize_host(host: str) -> str:
        """把 OLLAMA_HOST 环境变量的各种写法归一为可访问 URL。

        Ollama 自身用 OLLAMA_HOST 指定绑定地址（如 0.0.0.0、127.0.0.1:11434），
        与本配置同名，需兼容：补协议、0.0.0.0→localhost、补默认端口 11434。
        """
        h = (host or "").strip()
        if not h:
            h = "http://localhost:11434"
        if not h.startswith(("http://", "https://")):
            h = "http://" + h
        # 0.0.0.0 作为客户端目标不可靠，改用 localhost
        h = h.replace("://0.0.0.0", "://localhost")
        from urllib.parse import urlparse

        if not urlparse(h).port:
            h = h + ":11434"
        return h.rstrip("/")

    # ------------------------------------------------------------------ chat
    def chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        images: Iterable[Any] | None = None,
        think: bool = False,
    ) -> str:
        """调用 Ollama，返回 assistant 文本内容。

        images 可为：文件路径(str)、bytes、PIL.Image.Image 的任意混合。

        关键避坑（2026-08-31 实测）：有图像时必须走 /api/generate 的 images 字段。
        /api/chat 的 images 字段对视觉模型不生效（模型会回答"纯文本模式，看不到图"），
        导致所有视觉验证/定位静默失败（报"未提供截图"）。无图时才走 /api/chat。
        """
        b64_list = [self._to_b64(img) for img in images] if images else None
        # 取最后一条 user 消息的文本作为 prompt（generate 用 prompt 而非 messages）
        prompt = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                c = m.get("content")
                prompt = c if isinstance(c, str) else str(c or "")
                break
        try:
            if b64_list:
                # 视觉输入走 /api/generate（Ollama 0.32 实测唯一生效路径）
                payload: dict[str, Any] = {
                    "model": model,
                    "prompt": prompt,
                    "images": b64_list,
                    "stream": False,
                }
                resp = self._client.post(f"{self.host}/api/generate", json=payload)
                resp.raise_for_status()
                data = resp.json()
                return str(data.get("response") or "")
            # 无图：走 /api/chat（保留 think 参数支持）
            payload = {
                "model": model,
                "messages": messages,
                "stream": False,
                "think": think,
            }
            resp = self._client.post(f"{self.host}/api/chat", json=payload)
            resp.raise_for_status()
            data = resp.json()
            msg = data.get("message") or {}
            content = msg.get("content")
            if content is None:
                content = ""
            return str(content)
        except httpx.HTTPError as exc:
            raise OllamaError(f"Ollama 请求失败: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise OllamaError(f"Ollama 返回非 JSON: {exc}") from exc

    # --------------------------------------------------------------- helpers
    @staticmethod
    def _to_b64(img: Any) -> str:
        if isinstance(img, (bytes, bytearray)):
            return base64.b64encode(img).decode()
        if isinstance(img, str):
            return base64.b64encode(Path(img).read_bytes()).decode()
        # PIL.Image
        try:
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return base64.b64encode(buf.getvalue()).decode()
        except AttributeError:
            raise OllamaError(f"不支持的图片类型: {type(img)!r}")

    def list_models(self) -> list[dict[str, Any]]:
        try:
            resp = self._client.get(f"{self.host}/api/tags")
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise OllamaError(f"获取模型列表失败: {exc}") from exc
        return resp.json().get("models", []) or []

    def loaded_models(self) -> list[dict[str, Any]]:
        """当前已驻留 VRAM 的模型（用于诊断冷加载超时）。"""
        try:
            resp = self._client.get(f"{self.host}/api/ps")
            resp.raise_for_status()
            return resp.json().get("models", []) or []
        except httpx.HTTPError:
            return []

    def close(self) -> None:
        self._client.close()
