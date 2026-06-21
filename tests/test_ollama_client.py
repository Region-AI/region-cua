"""OllamaClient 主机归一化测试（兼容 Ollama 自身的 OLLAMA_HOST 绑定变量）。"""

from __future__ import annotations

from region_cua.vision.ollama_client import OllamaClient


def test_normalize_bare_bind_address():
    assert OllamaClient._normalize_host("0.0.0.0") == "http://localhost:11434"


def test_normalize_bare_ip_with_port():
    assert OllamaClient._normalize_host("127.0.0.1:11434") == "http://127.0.0.1:11434"


def test_normalize_zero_with_port():
    assert OllamaClient._normalize_host("http://0.0.0.0:11434") == "http://localhost:11434"


def test_normalize_full_url_unchanged():
    assert OllamaClient._normalize_host("http://localhost:11434") == "http://localhost:11434"


def test_normalize_empty():
    assert OllamaClient._normalize_host("") == "http://localhost:11434"


def test_normalize_strips_trailing_slash():
    assert OllamaClient._normalize_host("http://localhost:11434/") == "http://localhost:11434"
