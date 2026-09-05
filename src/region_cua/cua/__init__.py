"""CUA Backend 统一接口 + 适配器。

RegionCUA 的「视觉定位 + 操作执行」层抽象。两种开源 backend 实现：

- trycua  : 阿里 cua-driver（Windows UIA 驱动的本地驱动，CLI 子进程调用）
- qwen-ui: 阿里 Qwen-UI-Agent（Qwen3-VL 权重，本地 transformers 推理，输出坐标）

设计要点
--------
- 一个 backend 同时负责「视觉定位」(locate) 和「操作执行」(action)。
  A/B 评测时执行手尽量走同一条路（trycua 的 PostMessage，不抢前台），
  差异主要体现在「视觉定位」策略上：trycua 走 UIA/OCR+坐标映射，
  qwen-ui 走 VLM 直接输出像素坐标。
- 所有 backend 实现 :class:`CuaBackend` 协议，executor 只依赖该接口，
  通过 ``--backend trycua|qwen-ui|foreground|background`` 选择。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import base64
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional


# --------------------------------------------------------------------------- #
# 数据结构
# --------------------------------------------------------------------------- #
@dataclass
class Located:
    """视觉定位结果。"""

    x: int
    y: int
    found: bool = True
    analysis: str = ""

    def to_tuple(self) -> tuple[int, int]:
        return (self.x, self.y)


class CuaBackend(ABC):
    """CUA backend 统一接口。

    executor 调用顺序（每步）::

        backend.capture(name)        # 截图，返回路径
        backend.locate(path, target)  # 视觉定位 → Located
        backend.click(x, y, ...)     # 执行操作
        backend.type(text)
        backend.hotkey(...)
        backend.scroll(amount)
    """

    name: str = "base"

    @abstractmethod
    def capture(self, shot_path: str, window_keyword: Optional[str] = None) -> str:
        """截图到 shot_path，返回该路径。"""

    @abstractmethod
    def locate(self, screenshot_path: str, target_desc: str) -> Located:
        """在截图中定位 target_desc，返回坐标。"""

    @abstractmethod
    def click(self, x: int, y: int, button: str = "left", clicks: int = 1) -> None: ...

    def type_text(self, text: str) -> None:
        """输入文本（默认走 type_text_safe 规避 IME；子类可覆写原生路径）。"""
        self.type_text_safe(text)

    def _type_native(self, text: str) -> None:
        """原生逐字符输入路径（子类覆写）。默认无实现。"""
        raise NotImplementedError

    @abstractmethod
    def hotkey(self, *keys: str) -> None: ...

    @abstractmethod
    def scroll(self, amount: int) -> None: ...

    def activate_window(self, keyword: str) -> None:  # 可选
        pass

    def ensure_target(self, window_keyword: Optional[str] = None) -> None:  # 可选
        """确保已解析目标窗口（操作前调用）。默认 no-op，子类可覆写。"""
        pass

    def close(self) -> None:  # 可选
        pass

    # ------------------------------------------------------------ IME 规避
    _IME_SENSITIVE = set("@.,;:!?/\\()[]{}\"'`~")

    def type_text_safe(self, text: str) -> None:
        """输入文本，规避中文 IME 拦截。

        与前台 input.type_text 同策略：
        - 含非 ASCII（中文等）→ 剪贴板粘贴（跳过 IME）
        - 纯 ASCII 但含 @ . , 等易被 IME 拦截字符 → 剪贴板粘贴
        - 纯字母数字 → 直接 type_text（WM_CHAR 逐字符，IME 一般不拦截纯字母）

        cua-driver 的 WM_CHAR 对 Chromium 内容可能静默丢弃（返回
        background_unavailable），此时回退剪贴板粘贴兜底。
        """
        if not text:
            return
        try:
            text.encode("ascii")
        except UnicodeEncodeError:
            self._paste_clipboard(text)
            return
        if any(c in self._IME_SENSITIVE for c in text):
            self._paste_clipboard(text)
            return
        try:
            self._type_native(text)
        except Exception:
            # WM_CHAR 被 Chromium 丢弃 → 剪贴板粘贴兜底
            self._paste_clipboard(text)

    def _paste_clipboard(self, text: str) -> None:
        """把文本放进剪贴板并 Ctrl+V 粘贴到当前焦点窗口。

        cua-driver 的 hotkey ctrl+v 对带修饰键组合走 SendInput + 短暂前台切换，
        可靠地把 ASCII/中文文本粘贴进浏览器输入框（绕过 IME 与 WM_CHAR 丢弃）。
        """
        try:
            import pyperclip

            pyperclip.copy(text)
        except Exception:
            import subprocess

            subprocess.run(["clip"], input=text.encode("utf-16le"), check=False)
        self.hotkey("ctrl", "v")
