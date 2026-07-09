"""后台截图：用 Win32 PrintWindow API 截取特定窗口，即使被遮挡或不在前台。

对比 pyautogui.screenshot()（截整个屏幕的当前可见画面）：
- 前台模式：截屏幕 → 被遮挡的窗口内容看不到 → 锁屏时只截到锁屏画面
- 后台模式：PrintWindow 直接读窗口离屏渲染缓冲 → 不依赖窗口在前台可见

实现用 GetDC + CreateCompatibleBitmap + GetDIBits 组合，
比单纯 PrintWindow 到 DC 更可靠地拿到像素数据。
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Optional


def _user32():
    return ctypes.windll.user32  # type: ignore[attr-defined]


def _gdi32():
    return ctypes.windll.gdi32  # type: ignore[attr-defined]


# BITMAPINFOHEADER 结构体
class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", ctypes.c_uint32),
        ("biWidth", ctypes.c_int32),
        ("biHeight", ctypes.c_int32),
        ("biPlanes", ctypes.c_uint16),
        ("biBitCount", ctypes.c_uint16),
        ("biCompression", ctypes.c_uint32),
        ("biSizeImage", ctypes.c_uint32),
        ("biXPelsPerMeter", ctypes.c_int32),
        ("biYPelsPerMeter", ctypes.c_int32),
        ("biClrUsed", ctypes.c_uint32),
        ("biClrImportant", ctypes.c_uint32),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", ctypes.c_uint32 * 3)]


def _get_window_rect(hwnd: int) -> Optional[tuple[int, int, int, int]]:
    """返回窗口的 (left, top, right, bottom)，失败返回 None。"""
    rect = wintypes.RECT()
    if _user32().GetWindowRect(hwnd, ctypes.byref(rect)):
        return rect.left, rect.top, rect.right, rect.bottom
    return None


def capture_window(hwnd: int):
    """用 PrintWindow 截取指定窗口，返回 PIL.Image.Image。

    使用 PW_RENDERFULLCONTENT (0x00000002) 标志，能截到更多窗口类型的内容。
    """
    from PIL import Image

    rect = _get_window_rect(hwnd)
    if not rect:
        raise ValueError(f"无法获取窗口 {hwnd} 的矩形区域")

    left, top, right, bottom = rect
    width = right - left
    height = bottom - top
    if width <= 0 or height <= 0:
        raise ValueError(f"窗口 {hwnd} 尺寸异常: {width}x{height}")

    user32 = _user32()
    gdi32 = _gdi32()

    # 创建兼容 DC 和位图
    hwnd_dc = user32.GetWindowDC(hwnd)
    mfc_dc = gdi32.CreateCompatibleDC(hwnd_dc)
    bmp = gdi32.CreateCompatibleBitmap(hwnd_dc, width, height)
    gdi32.SelectObject(mfc_dc, bmp)

    # PrintWindow: flag=2 (PW_RENDERFULLCONTENT) 比 flag=0 兼容性更好
    result = user32.PrintWindow(hwnd, mfc_dc, 0x00000002)

    # 用 GetDIBits 从位图读像素
    bi = BITMAPINFOHEADER()
    bi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bi.biWidth = width
    bi.biHeight = -height  # 负值 = top-down（省去翻转）
    bi.biPlanes = 1
    bi.biBitCount = 32
    bi.biCompression = 0  # BI_RGB

    bmi = BITMAPINFO()
    bmi.bmiHeader = bi

    pixel_data = ctypes.create_string_buffer(width * height * 4)
    gdi32.GetDIBits(
        mfc_dc, bmp, 0, height,
        pixel_data, ctypes.byref(bmi), 0  # DIB_RGB_COLORS
    )

    # 清理 GDI 资源
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mfc_dc)
    user32.ReleaseDC(hwnd, hwnd_dc)

    # BGRA → RGBA for PIL
    img = Image.frombytes("RGBA", (width, height), pixel_data.raw)
    return img.convert("RGB")


def capture_window_by_title(keyword: str):
    """按窗口标题关键词截取窗口，返回 PIL.Image.Image。找不到返回 None。"""
    from .windows import find_window_by_title

    hwnd = find_window_by_title(keyword)
    if not hwnd:
        return None
    return capture_window(hwnd)


def save_window_screenshot(hwnd: int, path: str) -> str:
    """截取窗口并保存为 PNG，返回路径字符串。"""
    from pathlib import Path

    img = capture_window(hwnd)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(p), format="PNG")
    return str(p)
