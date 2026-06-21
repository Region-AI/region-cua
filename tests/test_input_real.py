"""automation/input.py 真实调用测试：验证 _pa() 返回 pyautogui 模块而非函数对象。

这个测试专门防范 _pa 函数名与缓存变量同名导致返回函数对象的 bug。
"""

from __future__ import annotations

import types

from region_cua.automation import input as inp


def test_pa_returns_module_not_function():
    """_pa() 必须返回 pyautogui 模块，不是函数对象。"""
    pa = inp._pa()
    # pyautogui 模块有 click/moveTo/scroll/press/hotkey/write 等属性
    assert hasattr(pa, "click"), f"_pa() 返回了 {type(pa)}，缺少 click 属性"
    assert hasattr(pa, "moveTo"), f"_pa() 返回了 {type(pa)}，缺少 moveTo 属性"
    assert hasattr(pa, "scroll"), f"_pa() 返回了 {type(pa)}，缺少 scroll 属性"
    # 确认不是函数对象
    assert not isinstance(pa, types.FunctionType), "_pa() 返回了函数对象！缓存变量被函数名覆盖了。"
    # FAILSAFE 应已关闭
    assert pa.FAILSAFE is False


def test_pa_is_singleton():
    """多次调用 _pa() 返回同一对象。"""
    assert inp._pa() is inp._pa()
