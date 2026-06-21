"""视觉层：客户端工厂 + Ollama 客户端 + vLLM 客户端。"""

from __future__ import annotations

from ..config import Settings
from .ollama_client import OllamaClient
from .vllm_client import VLLMClient


def create_vision_client(settings: Settings):
    """根据 provider 创建对应的视觉模型客户端。

    provider 可通过环境变量 PROVIDER 或 .env 文件设置：
      "ollama"（默认）— 使用 OllamaClient
      "vllm"          — 使用 VLLMClient
    """
    provider = (settings.provider or "ollama").strip().lower()
    if provider == "vllm":
        return VLLMClient(settings.vllm_host, settings.ollama_timeout)
    return OllamaClient(settings.ollama_host, settings.ollama_timeout)
