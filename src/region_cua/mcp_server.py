"""RegionCUA MCP 服务器：把桌面自动化能力暴露为标准 MCP 工具。

启动方式：
    region-cua mcp                 # stdio 传输（默认，接 Claude Code / Hermes）
    region-cua mcp --transport sse # SSE 传输

暴露的工具：
    screenshot       截屏，返回 base64 PNG
    analyze          用视觉模型分析截图（找元素 / 描述界面 / 验证操作）
    click            点击坐标
    type             输入文本（支持中文）
    hotkey           组合键
    scroll           滚动
    wait             等待
    open_app         启动应用
    run_task         完整执行一个自然语言任务（规划+执行+产出文档）

这样 Claude Code / Cursor / Hermes / OpenClaw 等任何支持 MCP 的 Agent，
都可以通过 @region-cua 自然语言驱动桌面，无需了解 region-cua 的 CLI。
"""

from __future__ import annotations

import base64
import io
import sys
from pathlib import Path
from typing import Optional


def _clean_hermes_path() -> None:
    """清理 Hermes 注入到 sys.path 的环境路径，避免依赖冲突。

    Hermes 把自己的 venv site-packages 放在 sys.path 最前面，会导致
    region-cua 项目 .venv 里的 mcp/pydantic 等依赖被 hermes 的覆盖。
    在 MCP 服务器入口处过滤掉非项目路径，确保用项目自己的依赖。
    """
    project_venv = str(Path(__file__).resolve().parents[3] / ".venv")
    project_src = str(Path(__file__).resolve().parents[3] / "src")
    keep: list[str] = []
    for p in sys.path:
        low = p.replace("\\", "/").lower()
        if "hermes" in low and project_venv.lower() not in low:
            continue  # 跳过 hermes 注入的路径
        keep.append(p)
    sys.path = keep
    # 确保项目 .venv 和 src 在最前
    for p in (project_venv + "/Lib/site-packages", project_src):
        if p not in sys.path:
            sys.path.insert(0, p)


_clean_hermes_path()

from mcp.server.fastmcp import FastMCP  # noqa: E402

from .agent.executor import TaskExecutor  # noqa: E402
from .agent.monitor import Monitor  # noqa: E402
from .agent.planner import TaskPlanner  # noqa: E402
from .automation import appfinder, input as inp  # noqa: E402
from .automation.windows import activate_window, find_window_by_title  # noqa: E402
from .config import get_settings  # noqa: E402
from .vision import screenshot as shot  # noqa: E402
from .vision.ollama_client import OllamaClient  # noqa: E402

mcp = FastMCP("region-cua")

# OmniParser 全局单例（首次调用时延迟加载 YOLO + OCR 模型）
_omniparser = None


def _get_omniparser():
    """获取 OmniParser 单例。"""
    global _omniparser
    if _omniparser is None:
        from .vision.omniparser import OmniParser
        _omniparser = OmniParser()
    return _omniparser


def _img_to_b64(img) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def _get_client() -> OllamaClient:
    s = get_settings()
    return OllamaClient(s.ollama_host, s.ollama_timeout)


# ================================================================ OmniParser 工具
@mcp.tool()
def parse_screen(window_keyword: Optional[str] = None) -> str:
    """截屏并用 OmniParser 解析为结构化元素列表。

    返回 JSON 格式的元素列表，每个元素包含 id/text/type/bbox/center。
    宿主 LLM 读取列表后，可以用 click_element(id) 点击对应元素。

    Args:
        window_keyword: 可选，只截取标题包含该关键词的窗口（后台模式，被遮挡也能截到）
    """
    import json

    # 截图（后台模式截特定窗口，前台模式截全屏）
    if window_keyword:
        img = shot.capture(window_keyword=window_keyword)
    else:
        img = shot.capture_screen()

    # OmniParser 解析
    parser = _get_omniparser()
    elements = parser.parse(img)

    # 格式化输出
    lines = [f"共检测到 {len(elements)} 个元素："]
    for e in elements:
        text = e.get("text", "") or "(无文字)"
        etype = e.get("type", "unknown")
        cx, cy = e["center"]
        lines.append(f'  [{e["id"]}] {etype}: "{text}" → 点击坐标 ({cx}, {cy})')
    return "\n".join(lines)


@mcp.tool()
def click_element(description: str, window_keyword: Optional[str] = None) -> str:
    """按文字描述查找并点击界面元素。

    先截屏用 OmniParser 解析，再从元素列表中找到最匹配 description 的元素并点击。
    不需要 LLM 输出坐标——OmniParser 的 YOLO+OCR 负责定位。

    Args:
        description: 要点击的元素描述，如 "Submit 按钮" 或 "搜索框" 或 "确定"
        window_keyword: 可选，只截取特定窗口
    """
    # 截图 + 解析
    if window_keyword:
        img = shot.capture(window_keyword=window_keyword)
    else:
        img = shot.capture_screen()

    # 保存临时截图（find_element 文字匹配失败时需要裁剪图标给 VLM 识别）
    import tempfile
    from pathlib import Path
    tmp_path = Path(tempfile.mktemp(suffix=".png"))
    img.save(str(tmp_path))

    parser = _get_omniparser()
    elements = parser.parse(img)
    elem = parser.find_element(elements, description, str(tmp_path))

    if not elem:
        try:
            tmp_path.unlink()
        except Exception:
            pass
        return f"未找到匹配「{description}」的元素。检测到 {len(elements)} 个元素，均不匹配。"

    cx, cy = elem["center"]
    inp.click_at(cx, cy)
    text = elem.get("text", "")

    # 清理临时文件
    try:
        tmp_path.unlink()
    except Exception:
        pass

    return f"已点击「{text}」(元素 [{elem['id']}])，坐标 ({cx}, {cy})"


@mcp.tool()
def type_in_element(description: str, text: str, window_keyword: Optional[str] = None) -> str:
    """在指定输入框中输入文本。

    先用 OmniParser 找到输入框位置，点击聚焦后输入文本。

    Args:
        description: 输入框描述，如 "用户名输入框" 或 "搜索框"
        text: 要输入的文字（支持中文）
        window_keyword: 可选，只截取特定窗口
    """
    if window_keyword:
        img = shot.capture(window_keyword=window_keyword)
    else:
        img = shot.capture_screen()

    # 保存临时截图
    import tempfile
    from pathlib import Path
    tmp_path = Path(tempfile.mktemp(suffix=".png"))
    img.save(str(tmp_path))

    parser = _get_omniparser()
    elements = parser.parse(img)
    elem = parser.find_element(elements, description, str(tmp_path))

    # 清理临时文件
    try:
        tmp_path.unlink()
    except Exception:
        pass

    if not elem:
        return f"未找到匹配「{description}」的输入框。"

    cx, cy = elem["center"]
    inp.click_at(cx, cy)  # 聚焦输入框
    import time
    time.sleep(0.3)
    inp.type_text(text)
    return f"已在「{elem.get('text', description)}」中输入 {len(text)} 个字符"


@mcp.tool()
def list_elements(window_keyword: Optional[str] = None) -> str:
    """截屏并列出所有可交互元素（不点击），用于查看当前界面结构。

    与 parse_screen 类似，但返回更简洁的列表格式。

    Args:
        window_keyword: 可选，只截取特定窗口
    """
    return parse_screen(window_keyword=window_keyword)


# ================================================================ 原有工具
@mcp.tool()
def screenshot() -> str:
    """截取当前屏幕，返回 base64 编码的 PNG 图片。"""
    img = shot.capture_screen()
    return _img_to_b64(img)


@mcp.tool()
def analyze(image_base64: str, question: str, model: Optional[str] = None) -> str:
    """用视觉模型分析一张截图。传入 base64 图片和问题（如"找到搜索框的坐标"），返回分析结果。

    Args:
        image_base64: base64 编码的 PNG 图片（可由 screenshot 工具获取）
        question: 要问视觉模型的问题，如"找到登录按钮的坐标"或"描述当前界面"
        model: 可选，覆盖默认视觉模型
    """
    s = get_settings()
    client = _get_client()
    vision_model = model or s.ollama_vision_model
    img_bytes = base64.b64decode(image_base64)
    try:
        result = client.chat(
            vision_model,
            [{"role": "user", "content": question}],
            images=[img_bytes],
        )
    finally:
        client.close()
    return result


@mcp.tool()
def click(x: int, y: int, button: str = "left", clicks: int = 1) -> str:
    """点击屏幕坐标 (x, y)。

    Args:
        x: 横坐标（像素）
        y: 纵坐标（像素）
        button: left / right / middle
        clicks: 点击次数（2=双击）
    """
    inp.click_at(x, y, button=button, clicks=clicks)
    return f"已点击 ({x}, {y}) button={button} clicks={clicks}"


@mcp.tool()
def type_text(text: str) -> str:
    """输入文本（支持中文等非 ASCII 字符，自动走剪贴板）。

    Args:
        text: 要输入的文字
    """
    inp.type_text(text)
    return f"已输入 {len(text)} 个字符"


@mcp.tool()
def hotkey(keys: str) -> str:
    """按下组合键，如 'ctrl+s'、'alt+tab'、'ctrl+shift+esc'。

    Args:
        keys: 组合键，用 + 连接
    """
    inp.press_hotkey(keys)
    return f"已按组合键 {keys}"


@mcp.tool()
def scroll(amount: int) -> str:
    """滚动鼠标滚轮。正数向上滚，负数向下滚。

    Args:
        amount: 滚动量，如 3 向上、-3 向下
    """
    inp.scroll(amount)
    return f"已滚动 {amount}"


@mcp.tool()
def wait(seconds: float) -> str:
    """等待指定秒数（用于应用启动、页面加载等）。

    Args:
        seconds: 等待秒数
    """
    inp.wait(seconds)
    return f"已等待 {seconds} 秒"


@mcp.tool()
def open_app(name: str) -> str:
    """启动一个桌面应用。

    Args:
        name: 应用名（如 'calc'、'WPS'、'notepad'）或可执行路径/URL
    """
    method = appfinder.open_app(name)
    # 尝试把窗口拉到前台
    from time import sleep

    sleep(2)
    activate_window(name.split()[0] if " " in name else name.replace(".exe", ""), wait=3.0)
    return f"已启动 {name}（方式: {method}）"


@mcp.tool()
def activate_window_tool(keyword: str) -> str:
    """把标题包含 keyword 的窗口激活到前台。

    Args:
        keyword: 窗口标题关键词，如 'WPS'、'计算器'
    """
    hwnd = find_window_by_title(keyword)
    if not hwnd:
        return f"未找到标题包含 '{keyword}' 的窗口"
    from .automation.windows import activate_window

    if activate_window(keyword):
        return f"已激活窗口（关键词: {keyword}）"
    return f"找到窗口但激活失败（关键词: {keyword}）"


@mcp.tool()
def run_task(task: str, no_video: bool = True, no_log: bool = False) -> str:
    """完整执行一个自然语言桌面自动化任务：自动规划步骤→逐步截图执行→产出文档/脚本/日志。

    适合多步骤复杂任务，如"打开 WPS 写一份周报并保存"。
    单步操作请直接用 screenshot/click/type 等工具。

    Args:
        task: 自然语言任务描述
        no_video: 是否跳过录屏（默认跳过，MCP 场景一般不需要视频）
        no_log: 是否跳过操作日志
    """
    from .main import run_task as _run_task

    plan, records, task_dir = _run_task(task, no_video=no_video, no_log=no_log)
    ok = sum(1 for r in records if r.success)
    result = (
        f"任务: {plan.task}\n"
        f"步骤: {ok}/{len(records)} 成功\n"
        f"输出目录: {task_dir}\n"
    )
    if task_dir:
        result += f"文档: {task_dir / '任务说明.md'}\n"
        result += f"脚本: {task_dir / 'scripts' / 'replay.py'}\n"
        if not no_log:
            result += f"日志: {task_dir / 'operation.log'}\n"
            result += f"轨迹: {task_dir / 'trajectory.jsonl'}\n"
    return result


@mcp.tool()
def list_models() -> str:
    """列出本地 Ollama 可用的模型。"""
    client = _get_client()
    try:
        models = client.list_models()
    finally:
        client.close()
    lines = [f"- {m.get('name', '')}" for m in models]
    loaded = client.loaded_models()
    if loaded:
        lines.append("\n已驻留 VRAM: " + ", ".join(m.get("name", "") for m in loaded))
    return "\n".join(lines)


def main(transport: str = "stdio") -> None:
    """MCP 服务器入口。"""
    mcp.run(transport=transport)


if __name__ == "__main__":
    transport = sys.argv[1] if len(sys.argv) > 1 else "stdio"
    main(transport)
