"""自由探索模式与 Skill 编译。

- explore_app: 联网收集背景 → 打开应用 → 视觉探索界面 → 生成使用说明.md + skill/SKILL.md
- compile_skill: 把已有说明文档（md/txt/html/pdf）结构化为操作 Skill
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .vision.ollama_client import OllamaClient


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
    client: OllamaClient,
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


def _describe(client: OllamaClient, model: str, image: str, prompt: str) -> str:
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
    client: OllamaClient,
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
