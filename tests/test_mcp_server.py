"""MCP 服务器测试：工具注册、导入、路径清理。

不测真实桌面操作，只验证 MCP server 的结构正确性。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest


def _ensure_project_venv(monkeypatch):
    """清理 hermes 注入路径，确保用项目 .venv 的依赖。"""
    project_root = Path(__file__).resolve().parents[1]
    venv_site = str(project_root / ".venv" / "Lib" / "site-packages")
    src = str(project_root / "src")
    # 过滤掉 hermes 路径
    monkeypatch.setattr(sys, "path", [p for p in sys.path if "hermes" not in p.lower()])
    for p in (venv_site, src):
        if p not in sys.path:
            sys.path.insert(0, p)


def test_mcp_import_and_tools(monkeypatch):
    """MCP 服务器能导入，且注册了全部预期工具。"""
    _ensure_project_venv(monkeypatch)
    from region_cua.mcp_server import mcp

    async def get_names():
        tools = await mcp.list_tools()
        return [t.name for t in tools]

    names = asyncio.run(get_names())
    expected = {"screenshot", "analyze", "click", "type_text", "hotkey",
                "scroll", "wait", "open_app", "activate_window_tool",
                "run_task", "list_models"}
    assert expected.issubset(set(names)), f"缺少工具: {expected - set(names)}"


def test_mcp_tool_descriptions_nonempty(monkeypatch):
    """每个工具应有描述文本。"""
    _ensure_project_venv(monkeypatch)
    from region_cua.mcp_server import mcp

    async def get_tools():
        return await mcp.list_tools()

    tools = asyncio.run(get_tools())
    for t in tools:
        assert t.description, f"工具 {t.name} 缺少描述"


def test_mcp_server_has_main(monkeypatch):
    """main() 入口存在且可调用（不实际 run）。"""
    _ensure_project_venv(monkeypatch)
    from region_cua import mcp_server

    assert callable(mcp_server.main)
    assert mcp_server.mcp is not None
