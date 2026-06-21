"""截图目录与文件管理工具。"""

from __future__ import annotations

from pathlib import Path


def ensure_screenshot_dir(task_dir: Path) -> Path:
    d = task_dir / "screenshots"
    d.mkdir(parents=True, exist_ok=True)
    return d


def list_screenshots(task_dir: Path) -> list[Path]:
    d = task_dir / "screenshots"
    if not d.exists():
        return []
    return sorted(d.glob("*.png"))


def relpath(path: str | Path, base: str | Path) -> str:
    """计算 path 相对 base 的路径，用于 Markdown 内嵌。"""
    try:
        return str(Path(path).relative_to(base)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")
