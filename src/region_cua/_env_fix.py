"""清理 Hermes 环境路径污染。

Hermes 运行 terminal 时会把自身的 venv site-packages 加入 sys.path，
其 Pillow 的 _imaging C 扩展与 RegionCUA venv 不兼容，导致
pyautogui.screenshot() 报 "screen grab failed"。

本模块在 import 时自动移除 Hermes 路径，确保 RegionCUA venv 的包优先。
"""
import sys as _sys

# 移除所有含 "hermes" 的路径
_sys.path = [p for p in _sys.path if "hermes" not in p.lower()]
