"""浏览器会话：用系统默认浏览器打开 cua-bench 任务 HTML。

零第三方依赖——只用 Python 标准库 + Win32 API：
- webbrowser.open() 启动系统默认浏览器
- 临时 HTML 文件承载任务页面
- HTML 内注入观察器 JS：任务完成时把结果写入 document.title
- Python 侧用 Win32 EnumWindows + GetWindowText 读窗口标题获取结果

不使用 Playwright/Selenium。region-cua 的截图+pyautogui 负责全部交互。
"""

from __future__ import annotations

import ctypes
import re
import tempfile
import time
import webbrowser
from pathlib import Path
from typing import Optional
from ctypes import wintypes


def _user32():
    return ctypes.windll.user32  # type: ignore[attr-defined]


# 注入到任务 HTML 中的观察器脚本
# 原理：cua-bench 任务的评估 JS 检查 window.__xxx 全局变量
# 我们每 500ms 轮询一次，变量变为期望值时写入 document.title
# 注意：不能用 .format()，JS 里的 {} 会被误解析
_OBSERVER_JS_TEMPLATE = """
<script>
(function() {{
    const evalExpr = {eval_expr};
    const expected = {expected};
    const checkInterval = setInterval(function() {{
        try {{
            const val = eval(evalExpr);
            if (val === expected) {{
                document.title = 'BENCH_DONE:1.0';
                clearInterval(checkInterval);
            }} else if (val !== null && val !== undefined && val !== false && val !== 0) {{
                document.title = 'BENCH_DONE:0.5';
            }}
        }} catch(e) {{}}
    }}, 500);
    setTimeout(function() {{
        document.title = 'BENCH_DONE:0.0';
        clearInterval(checkInterval);
    }}, 300000);
}})();
</script>
"""


def _build_observer(eval_js: str, expected_value: object) -> str:
    """构建观察器脚本，用字符串替换避免 .format() 的 {} 冲突。"""
    # Python True/False/None → JS true/false/null
    if expected_value is True:
        # expected_value=True 时，检查"非空非false"而非精确匹配 true
        # 因为很多 cua-bench 任务的 JS 变量返回字符串/对象而非布尔值
        expected_js = "__ANY_NON_EMPTY__"
    elif expected_value is False:
        expected_js = "false"
    elif expected_value is None:
        expected_js = "null"
    else:
        expected_js = repr(expected_value)

    if expected_js == "__ANY_NON_EMPTY__":
        # 非空匹配模式：val 不是 null/false/0/undefined/"" 即为成功
        result = _OBSERVER_JS_TEMPLATE.replace(
            "{eval_expr}", repr(eval_js)
        ).replace(
            "{expected}", "true"
        ).replace(
            "val === expected", "(val !== null && val !== undefined && val !== false && val !== 0 && val !== '')"
        )
        # 修复 JS 花括号转义（模板用 {{ }} 转义，需要还原）
        result = result.replace("{{", "{").replace("}}", "}")
        return result
    else:
        result = _OBSERVER_JS_TEMPLATE.replace(
            "{eval_expr}", repr(eval_js)
        ).replace(
            "{expected}", expected_js
        )
        result = result.replace("{{", "{").replace("}}", "}")
        return result


class BrowserSession:
    """系统浏览器会话：打开任务页面 + 轮询窗口标题获取评估结果。

    用法：
        with BrowserSession(html, title="click-button") as session:
            session.wait_ready()        # 等浏览器打开
            ...                          # region-cua 截图+操作
            score = session.wait_done()  # 等待任务完成，返回 0.0/0.5/1.0
    """

    def __init__(
        self,
        html: str,
        *,
        title: str = "CUA Bench",
        eval_js: str = "window.__submitted",
        expected_value: object = True,
        timeout: float = 120,
        window_width: int = 800,
        window_height: int = 600,
        window_x: int = 0,
        window_y: int = 0,
    ):
        self._html = html
        self.title = title
        self.eval_js = eval_js
        self.expected_value = expected_value
        self.timeout = timeout
        self.window_width = window_width
        self.window_height = window_height
        self.window_x = window_x
        self.window_y = window_y
        self._temp_file: Optional[Path] = None
        self._opened = False

    def __enter__(self) -> "BrowserSession":
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def start(self) -> None:
        """打开系统浏览器加载任务 HTML。"""
        # 构建带观察器的完整 HTML
        observer = _build_observer(self.eval_js, self.expected_value)
        full_html = self._inject_observer(self._html, observer)

        # 写入临时文件
        self._temp_file = Path(tempfile.mktemp(suffix=".html"))
        self._temp_file.write_text(full_html, encoding="utf-8")

        # 用系统默认浏览器打开
        url = f"file:///{self._temp_file.as_posix()}"
        webbrowser.open(url)
        self._opened = True

        # 等窗口出现后调整位置和大小（左上角 1/4 屏幕大小，让按钮占比更大）
        import time as _time
        _time.sleep(2)
        self._resize_window()
        # 激活窗口到前台（确保截图能看到页面内容）
        self._activate_window()
        # 等 Tailwind CSS 渲染完成
        _time.sleep(2)

    @property
    def html_raw(self) -> str:
        """子类可覆盖，默认从 __init__ 的 html 参数取。"""
        return getattr(self, "_html", "")

    def _inject_observer(self, html: str, observer_js: str) -> str:
        """把观察器脚本注入 HTML，确保有 <title>、Tailwind CSS、翻译禁用标记。"""
        # 确保 HTML 有完整的 <head>（含 Tailwind CDN）
        needs_head = "<head>" not in html[:500].lower() and "<html" not in html[:200].lower()
        if needs_head:
            html = f'<!doctype html><html lang="en" translate="no"><head><meta charset="UTF-8"><title>{self.title}</title></head><body>{html}</body></html>'

        # 确保 <html> 有 translate="no"（禁止浏览器翻译提示框）
        if "<html" in html.lower() and "translate" not in html[:200].lower():
            html = html.replace("<html", '<html translate="no"', 1)

        # 确保 <head> 存在
        if "<head>" not in html.lower():
            html = html.replace("<html", '<html><head></head>', 1)

        # 确保 <title>
        if "<title>" not in html.lower():
            html = html.replace("<head>", f"<head><title>{self.title}</title>", 1)

        # 注入 notranslate meta（禁止 Google 翻译提示）
        if "notranslate" not in html[:600].lower():
            html = html.replace("<head>", '<head><meta name="google" content="notranslate">', 1)

        # 注入 Tailwind CSS CDN（cua-bench 任务 HTML 依赖 Tailwind 类但自身未引入）
        if "tailwindcss" not in html.lower():
            tailwind_script = '<script src="https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4"></script>'
            html = html.replace("<head>", f"<head>{tailwind_script}", 1)

        # 注入 Iconify 图标库（cua-bench 任务用 <iconify-icon> 自定义元素渲染图标）
        # 检查是否已引入 iconify 脚本（不是检查标签）
        if "iconify-icon@" not in html.lower() and "iconify" not in [s for s in re.findall(r'<script[^>]*src=["\']([^"\']+)["\']', html, re.I)]:
            iconify_script = '<script src="https://cdn.jsdelivr.net/npm/iconify-icon@3.0.2/dist/iconify-icon.min.js"></script>'
            html = html.replace("<head>", f"<head>{iconify_script}", 1)

        # 在 </body> 前注入观察器
        if "</body>" in html.lower():
            idx = html.lower().rfind("</body>")
            html = html[:idx] + observer_js + html[idx:]
        else:
            html = html + observer_js
        return html

    def wait_ready(self, timeout: float = 10) -> bool:
        """等待浏览器窗口出现。"""
        t0 = time.time()
        while time.time() - t0 < timeout:
            if self._find_window():
                return True
            time.sleep(0.5)
        return False

    def _resize_window(self) -> None:
        """把浏览器窗口移到左上角并设为指定大小，让页面元素占比更大。"""
        hwnd = self._find_window()
        if not hwnd:
            return
        user32 = _user32()
        # SW_RESTORE = 9（如果最小化则恢复）
        user32.ShowWindow(hwnd, 9)
        time.sleep(0.3)
        # MoveWindow(hwnd, x, y, width, height, repaint=True)
        # 减去标题栏/边框的额外高度（约 60px），让客户区接近 window_height
        user32.MoveWindow(hwnd, self.window_x, self.window_y,
                          self.window_width, self.window_height + 60, True)

    def _activate_window(self) -> None:
        """激活浏览器窗口到前台。

        Windows 不允许后台进程直接抢前台，需要用 Alt 键技巧绕过限制：
        先模拟按 Alt 键（让系统认为用户在操作），再调 SetForegroundWindow。
        """
        hwnd = self._find_window()
        if not hwnd:
            return
        user32 = _user32()
        # SW_RESTORE = 9
        user32.ShowWindow(hwnd, 9)
        time.sleep(0.2)

        # Alt 键技巧：按一下 Alt 释放前台锁
        import ctypes
        user32.keybd_event(0x12, 0, 0, 0)       # Alt down
        user32.keybd_event(0x12, 0, 0x0002, 0)  # Alt up (KEYEVENTF_KEYUP)
        time.sleep(0.1)

        try:
            user32.SetForegroundWindow(hwnd)
        except Exception:
            pass
        # 确保窗口在最前
        try:
            user32.BringWindowToTop(hwnd)
        except Exception:
            pass

    def get_score(self) -> Optional[float]:
        """读取当前分数（从窗口标题解析 BENCH_DONE:x.x）。无结果返回 None。"""
        title = self._get_window_title()
        if title and "BENCH_DONE:" in title:
            try:
                # 提取 BENCH_DONE: 后面的数字
                part = title.split("BENCH_DONE:")[1].split()[0]
                return float(part)
            except (IndexError, ValueError):
                pass
        return None

    def wait_done(self, timeout: Optional[float] = None) -> float:
        """阻塞等待任务完成，返回分数 0.0~1.0。"""
        timeout = timeout or self.timeout
        t0 = time.time()
        while time.time() - t0 < timeout:
            score = self.get_score()
            if score is not None:
                return score
            time.sleep(1.0)
        return 0.0

    def _find_window(self) -> Optional[int]:
        """找到标题包含 self.title 或 BENCH_DONE 的窗口句柄。"""
        results: list[int] = []
        user32 = _user32()

        @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)
        def _enum(hwnd, _lparam):
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                # 匹配原标题或 BENCH_DONE（观察器改了 document.title 后窗口标题会变）
                if self.title in buf.value or "BENCH_DONE" in buf.value:
                    results.append(hwnd)
            return True

        user32.EnumWindows(_enum, 0)
        return results[0] if results else None

    def _get_window_title(self) -> Optional[str]:
        """获取目标窗口的当前标题。"""
        hwnd = self._find_window()
        if not hwnd:
            return None
        user32 = _user32()
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return ""
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        return buf.value

    def close(self) -> None:
        """关闭浏览器窗口（发 WM_CLOSE）和清理临时文件。"""
        hwnd = self._find_window()
        if hwnd:
            _user32().PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
        if self._temp_file and self._temp_file.exists():
            try:
                self._temp_file.unlink()
            except Exception:
                pass
            self._temp_file = None
        self._opened = False
