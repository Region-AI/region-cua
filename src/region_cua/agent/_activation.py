# -*- coding: utf-8 -*-
"""Centralized window activation helper — shared by executor and workflows."""

import ctypes
import ctypes.wintypes as _wt


def _user32():
    """Cache user32 DLL handle."""
    if not hasattr(_user32, "_dll"):
        _user32._dll = ctypes.windll.user32
    return _user32._dll


_WINDOW_CLASSES = ("CuaBrowser", "WebView2")


def _find_window(keyword: str) -> int | None:
    """Find a Cua browser window by title keyword.

    Strategy (in order):
      1. Exact substring match on window title (keyword → case-insensitive)
      2. Keyword normalized (strip _N suffix, hyphen→space, underscore→space)
      3. Class-name fallback: look for any CuaBrowser / WebView2-class window,
         filter out windows whose title looks like a normal app (e.g. Edge, Explorer).
    """
