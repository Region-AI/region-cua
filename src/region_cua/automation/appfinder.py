"""应用查找与启动（Windows）。

策略：
1. 若 target 像可执行路径 / URL / 文件 → os.startfile 直开。
2. 在 PATH 上能找到的可执行名 → 直接启动。
3. 搜索开始菜单快捷方式（.lnk），匹配到则 os.startfile（Windows 会正确解析快捷方式）。
4. 都失败则回退到 `cmd /c start "" <name>`，交给 Shell 关联。
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

# Windows 开始菜单快捷方式目录
_START_MENU_DIRS = [
    Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
    Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
]


def _looks_like_path_or_url(name: str) -> bool:
    n = name.strip().lower()
    return (
        n.startswith(("http://", "https://", "www."))
        or n.endswith((".exe", ".lnk", ".url", ".bat", ".cmd", ".msi"))
        or (len(n) > 2 and (n[1] == ":" or n.startswith("/")) and ("\\" in n or "/" in n))
    )


def find_shortcuts(name: str) -> list[str]:
    """在开始菜单中查找名称包含关键字的快捷方式（大小写不敏感）。"""
    # 名称里的可选拆分：取较长的有意义片段作为关键字
    keywords = [p for p in name.replace(".exe", "").replace(".lnk", "").split() if p]
    if not keywords:
        keywords = [name]
    results: list[str] = []
    for base in _START_MENU_DIRS:
        if not base.exists():
            continue
        for lnk in base.rglob("*.lnk"):
            low = lnk.stem.lower()
            if any(kw.lower() in low for kw in keywords):
                results.append(str(lnk))
    return results


def open_app(name: str) -> str:
    """启动应用，返回实际使用的方式描述。"""
    name = (name or "").strip()
    if not name:
        raise ValueError("应用名为空")

    # 1. 路径 / URL / 文件
    if _looks_like_path_or_url(name) and Path(name).exists() or name.lower().startswith(("http://", "https://")):
        os.startfile(name)  # type: ignore[attr-defined]
        return f"startfile:{name}"

    # 2. PATH 上的可执行名
    exe = shutil.which(name)
    if exe:
        subprocess.Popen([exe])
        return f"exec:{exe}"

    # 3. 开始菜单快捷方式
    shortcuts = find_shortcuts(name)
    if shortcuts:
        os.startfile(shortcuts[0])  # type: ignore[attr-defined]
        return f"shortcut:{shortcuts[0]}"

    # 4. 回退到 Shell 关联（calc、notepad、winword 等系统名可命中）
    subprocess.Popen(["cmd", "/c", "start", "", name], shell=False)
    return f"shell:{name}"
