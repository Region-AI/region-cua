"""自由探索模式与 Skill 编译。

- explore_app: 联网收集背景 → 打开应用 → 视觉探索界面 → 生成使用说明.md + skill/SKILL.md
- compile_skill: 把已有说明文档（md/txt/html/pdf）结构化为操作 Skill
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .vision.protocol import VisionClient


# --------------------------------------------------------------------- web
def search_background(app: str) -> str:
    """尽力联网搜索应用背景信息（DuckDuckGo Instant Answer）。失败返回空串。"""
    import httpx

    try:
        r = httpx.get(
            "https://api.duckduckgo.com/",
            params={"q": app, "format": "json", "no_html": "1", "skip_disambig": "1"},
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
    except Exception:
        return ""
    parts = [data.get("AbstractText", "")]
    for topic in (data.get("RelatedTopics") or [])[:8]:
        if isinstance(topic, dict) and topic.get("Text"):
            parts.append(topic["Text"])
    return "\n".join(p for p in parts if p).strip()


# ------------------------------------------------------------------ explore
def explore_app(
    client: VisionClient,
    vision_model: str,
    app: str,
    task_dir: Path,
    record_video: bool = True,
) -> Path:
    """自由探索一个应用并产出说明文档 + Skill。"""
    from .automation import appfinder
    from .recorder.video import VideoRecorder
    from .vision import screenshot as shot

    task_dir = Path(task_dir)
    (task_dir / "screenshots").mkdir(parents=True, exist_ok=True)
    skill_dir = task_dir / "skill"
    skill_dir.mkdir(parents=True, exist_ok=True)

    video = VideoRecorder(task_dir) if record_video else None
    if video:
        video.start()

    observations: list[str] = []
    try:
        # 1. 背景
        bg = search_background(app)
        if bg:
            observations.append(f"【背景信息】\n{bg}")

        # 2. 打开应用
        try:
            appfinder.open_app(app)
            import time

            time.sleep(3)
        except Exception as exc:
            observations.append(f"【启动失败】{exc}")

        # 3. 初始界面
        img = shot.capture_screen()
        first = shot.save_screenshot(img, task_dir / "screenshots" / "home.png")
        desc = _describe(client, vision_model, first, f"这是 {app} 的主界面，请描述可见的功能区、菜单、按钮。")
        observations.append(f"【主界面】\n{desc}")

        # 4. 探索菜单栏：按 Alt 唤出
        try:
            from .automation import input as inp

            inp.press_hotkey("alt")
            import time

            time.sleep(0.8)
            img2 = shot.capture_screen()
            menu = shot.save_screenshot(img2, task_dir / "screenshots" / "menu.png")
            mdesc = _describe(client, vision_model, menu, "描述当前显示的菜单项。")
            observations.append(f"【菜单栏】\n{mdesc}")
            inp.press_key("escape")
        except Exception as exc:
            observations.append(f"【菜单探索异常】{exc}")
    finally:
        if video:
            try:
                video.stop()
            except Exception:
                pass

    # 5. 生成使用说明
    manual = _build_manual(app, bg, observations)
    (task_dir / "使用说明.md").write_text(manual, encoding="utf-8")

    # 6. 编译 Skill
    _write_skill(skill_dir, app, manual)
    return task_dir


def _describe(client: VisionClient, model: str, image: str, prompt: str) -> str:
    try:
        return client.chat(model, [{"role": "user", "content": prompt}], images=[image])
    except Exception as exc:
        return f"(视觉描述失败: {exc})"


def _build_manual(app: str, bg: str, observations: list[str]) -> str:
    lines = [f"# {app} 使用说明", "", "## 1. 介绍", "", bg or f"{app} 是一款桌面应用。", ""]
    lines += ["## 2. 快速入门", "", "打开应用后即可看到主界面，常用功能位于菜单栏与工具栏。", ""]
    lines += ["## 3. 功能详解", ""]
    for obs in observations:
        lines.append(obs)
        lines.append("")
    return "\n".join(lines)


def _write_skill(skill_dir: Path, app: str, manual: str) -> None:
    content = f"""---
name: {re.sub(r'[^a-z0-9]+', '-', app.lower()).strip('-') or 'app'}
description: 自动探索生成的 {app} 操作 Skill
metadata:
  emoji: 🤖
  category: automation
  source: region-cua explore
---

# {app} 操作 Skill

> 由 RegionCUA 自由探索模式自动生成，可被任务模式引用以提升执行成功率。

{manual}
"""
    (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")


# --------------------------------------------------------- UIA 全量元素遍历
# 「自由探索」时枚举/点击验证界面上所有可交互元素（Windows UIA 无障碍树）。
# 经验沉淀：uia 中心点=物理像素可直接喂 pyautogui.click（须 DPI-aware）；
# 页面状态用 Text 控件 Name 集合做指纹；NAV(右缘<win.left+100)/TITLE(top<win.top+45) 跳过。

INTERACTIVE_ROLES = {"Button", "Edit", "TabItem", "Hyperlink", "MenuItem", "ComboBox",
                     "CheckBox", "RadioButton", "SplitButton", "Link"}
DANGEROUS_KEYWORDS = ["删除", "清空", "退出", "登出", "注销", "重置", "移除",
                      "Delete", "Logout"]


def enumerate_ui_elements(
    hwnd: int,
    roles: set[str] | None = None,
    exclude_dangerous: bool = True,
    nav_band: int = 100,
    title_band: int = 45,
    min_area: int = 60,
) -> list[dict]:
    """枚举窗口 UIA 无障碍树中所有可交互元素（Windows）。

    Args:
        hwnd: 目标窗口句柄（可见窗口，非进程 ID）。
        roles: 要收集的角色集合，默认 INTERACTIVE_ROLES。
        exclude_dangerous: 跳过名称含危险词的元素（删除/退出/清空等），
            破坏性按钮只应出现在可执行的自造测试数据清理里。
        nav_band: 左侧导航栏判定宽度（rect.right - win.left < nav_band）。
        title_band: 顶部标题栏判定高度（rect.top - win.top < title_band）。
        min_area: 忽略小于该面积(px²)的元素（噪音）。

    Returns:
        [{"role","name","tag","rect","cx","cy","area"}, ...]，
        tag ∈ {"NAV","TITLE","PAGE"}。
        注意：uiautomation 的 BoundingRectangle 是 DPI 物理像素，
        调用方须先 `ctypes.windll.shcore.SetProcessDpiAwareness(2)`，
        中心点 (cx,cy) 才能直接用于 pyautogui.click。
        未暴露为可交互角色的元素（Electron div 组件）枚举不到 → 需辅以视觉定位。
    """
    import ctypes

    import uiautomation as ua  # 延迟导入，无桌面环境不报错

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass
    win_rect = None
    try:
        r = ua.ControlFromHandle(hwnd).BoundingRectangle
        win_rect = (r.left, r.top)
    except Exception:
        win_rect = (0, 0)

    roles = roles or INTERACTIVE_ROLES
    out: list[dict] = []

    def walk(ctrl, depth: int = 0, max_depth: int = 60) -> None:
        try:
            role = ctrl.ControlTypeName.replace("Control", "")
            if role in roles and not ctrl.IsOffscreen:
                r = ctrl.BoundingRectangle
                name = (ctrl.Name or "")[:90]
                if r.right - win_rect[0] < nav_band:
                    tag = "NAV"
                elif r.top - win_rect[1] < title_band:
                    tag = "TITLE"
                else:
                    tag = "PAGE"
                if exclude_dangerous and any(k in name for k in DANGEROUS_KEYWORDS):
                    return
                area = r.width() * r.height()
                if area >= min_area:
                    out.append({
                        "role": role[:10], "name": name, "tag": tag,
                        "rect": [r.left, r.top, r.right, r.bottom],
                        "cx": (r.left + r.right) // 2,
                        "cy": (r.top + r.bottom) // 2,
                        "area": area,
                    })
            if depth < max_depth:
                for ch in ctrl.GetChildren():
                    walk(ch, depth + 1, max_depth)
        except Exception:
            pass

    walk(ua.ControlFromHandle(hwnd))
    return out


# ----------------------------------------------------------------- compile
def _read_document(path: Path) -> str:
    suf = path.suffix.lower()
    if suf in (".md", ".txt", ".markdown"):
        return path.read_text(encoding="utf-8", errors="ignore")
    if suf in (".html", ".htm"):
        raw = path.read_text(encoding="utf-8", errors="ignore")
        return re.sub(r"<[^>]+>", " ", raw)
    if suf == ".pdf":
        try:
            import fitz  # pymupdf

            doc = fitz.open(str(path))
            return "\n".join(page.get_text() for page in doc)
        except ImportError:
            raise RuntimeError("PDF 解析需要 pymupdf：pip install pymupdf")
    raise RuntimeError(f"不支持的文档格式：{suf}")


def compile_skill(
    client: VisionClient,
    planner_model: str,
    doc_path: str,
    app: str,
    task_dir: Path,
) -> Path:
    """把已有说明文档编译为结构化操作 Skill。"""
    task_dir = Path(task_dir)
    skill_dir = task_dir / "skill"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "sources").mkdir(parents=True, exist_ok=True)

    src = Path(doc_path)
    text = _read_document(src)
    # 保留源文档副本
    (task_dir / "sources" / src.name).write_text(text, encoding="utf-8")

    prompt = (
        f"以下是「{app}」的系统说明文档。请把它结构化为操作 Skill："
        "提炼关键操作步骤、界面元素、注意事项，用 Markdown 输出，"
        "包含「适用场景」「操作步骤」「界面元素」「注意事项」等章节。\n\n"
        f"--- 文档开始 ---\n{text[:6000]}\n--- 文档结束 ---"
    )
    try:
        structured = client.chat(planner_model, [{"role": "user", "content": prompt}])
    except Exception as exc:
        structured = f"（Skill 结构化失败：{exc}）\n\n原文档摘要：\n{text[:2000]}"

    content = f"""---
name: {re.sub(r'[^a-z0-9]+', '-', app.lower()).strip('-') or 'app'}
description: 由说明文档编译的 {app} 操作 Skill
metadata:
  emoji: 📚
  category: automation
  source: region-cua compile
---

# {app} 操作 Skill

{structured}
"""
    (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")
    return skill_dir
