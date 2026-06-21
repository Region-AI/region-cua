"""测试公共夹具：模拟 Ollama 客户端、桌面操作桩。"""

from __future__ import annotations

import types

import pytest


class FakeOllamaClient:
    """按「内容子串 → 响应」映射返回的 Ollama 客户端 mock。

    - chat(): 取最后一条消息内容，返回首个命中的映射值；未命中返回 default
    - 也可注入 raise_on=True 让 chat 抛异常，用于测试失败隔离
    """

    def __init__(self, responses=None, default="", raise_on=False):
        self.responses = responses or {}
        self.default = default
        self.raise_on = raise_on
        self.calls = []

    def chat(self, model, messages, images=None, think=False):
        self.calls.append({"model": model, "messages": messages, "images": images})
        if self.raise_on:
            raise RuntimeError("模拟 Ollama 故障")
        content = messages[-1]["content"] if messages else ""
        for key, val in self.responses.items():
            if key in content:
                return val
        return self.default

    def list_models(self):
        return [
            {"name": "qwen3.5:latest", "size": 6600000000},
            {"name": "qwen3.6:27b", "size": 17000000000},
        ]

    def loaded_models(self):
        return []

    def close(self):
        pass


@pytest.fixture
def fake_client_cls():
    return FakeOllamaClient


@pytest.fixture
def sample_plan():
    from region_cua.agent.models import Step, TaskPlan

    return TaskPlan(
        task="打开计算器计算1024乘以768",
        steps=[
            Step(order=1, action="open_app", target="calc", description="打开计算器", requires_vision=False),
            Step(order=2, action="click", target="数字1", value="left", description="点击1", requires_vision=True),
            Step(order=3, action="type", target="1024", description="输入1024", requires_vision=False),
            Step(order=4, action="hotkey", target="ctrl+s", description="保存", requires_vision=False),
            Step(order=5, action="done", value="完成", description="完成", requires_vision=False),
        ],
    )


@pytest.fixture
def stub_desktop(monkeypatch):
    """桩掉所有真实桌面操作，返回记录字典供断言。"""
    calls = {"click": [], "type": [], "hotkey": [], "scroll": [], "wait": [], "open_app": [], "key": []}
    import region_cua.automation.appfinder as af
    import region_cua.automation.input as inp
    import region_cua.vision.screenshot as shot

    monkeypatch.setattr(inp, "click_at", lambda x, y, button="left", clicks=1: calls["click"].append((x, y, button, clicks)))
    monkeypatch.setattr(inp, "type_text", lambda t, interval=0.02: calls["type"].append(t))
    monkeypatch.setattr(inp, "press_hotkey", lambda *k: calls["hotkey"].append(k))
    monkeypatch.setattr(inp, "press_key", lambda k: calls["key"].append(k))
    monkeypatch.setattr(inp, "scroll", lambda a: calls["scroll"].append(a))
    monkeypatch.setattr(inp, "wait", lambda s: calls["wait"].append(s))
    monkeypatch.setattr(af, "open_app", lambda n: calls["open_app"].append(n))
    monkeypatch.setattr(shot, "capture_screen", lambda: "fakeimg")
    monkeypatch.setattr(shot, "save_screenshot", lambda img, path: str(path))
    monkeypatch.setattr(shot, "screen_size", lambda: (1920, 1080))
    # 屏蔽 executor 内的 time.sleep，避免测试真实等待
    import region_cua.agent.executor as ex

    monkeypatch.setattr(ex, "time", types.SimpleNamespace(sleep=lambda *a, **k: None))
    return calls


def ollama_reachable(host="http://localhost:11434") -> bool:
    try:
        import httpx

        r = httpx.get(f"{host}/api/tags", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


@pytest.fixture
def require_ollama():
    if not ollama_reachable():
        pytest.skip("Ollama 不可达，跳过集成测试")
