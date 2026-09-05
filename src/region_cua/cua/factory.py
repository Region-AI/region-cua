"""CuaBackend 工厂：根据 backend 名构造对应实例。

backend 取值：
- "trycua"   : trycua backend（UIA 控件树定位 + PostMessage 执行）
- "qwen-ui"  : Qwen-UI-Agent backend（Ollama VLM 视觉定位 + PostMessage 执行）
- 其它（foreground/background 等）: 返回 None，走 executor 原有逻辑（向后兼容）
"""

from __future__ import annotations

from typing import Optional

from ..cua import CuaBackend


def make_backend(name: Optional[str], **kwargs) -> Optional[CuaBackend]:
    name = (name or "").strip().lower()
    if name in ("trycua", "cua-driver", "cua_driver"):
        from .trycua_backend import TryCuaBackend

        return TryCuaBackend(**kwargs)
    if name in ("qwen-ui", "qwenui", "qwen-ui-agent", "qwen_ui_agent", "qwen-ui-agent"):
        from .qwenui_backend import QwenUIAgentBackend

        return QwenUIAgentBackend(**kwargs)
    return None  # 非 CUA backend，executor 走原前台/后台路径
