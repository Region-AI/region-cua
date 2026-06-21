"""Monitor：异常检测与人类介入。

- 连续失败次数达阈值 → 询问用户 continue/abort
- 视觉文本出现登录/验证码关键词 → 标记需人工
"""

from __future__ import annotations

from typing import Callable, Optional

# 需要人工介入的界面线索
_ANOMALY_KEYWORDS = (
    "登录", "登陆", "密码", "password", "验证码", "captcha", "请输入账号",
    "sign in", "log in", "二维码", "扫码",
)

AskUserFn = Callable[[str], str]


def _default_ask(prompt: str) -> str:
    try:
        return input(prompt).strip().lower()
    except EOFError:
        return "abort"


class Monitor:
    def __init__(self, max_failures: int = 3, ask_user: Optional[AskUserFn] = None):
        self.max_failures = max(1, max_failures)
        self.consecutive_failures = 0
        self.ask_user: AskUserFn = ask_user or _default_ask

    def on_step(self, order: int, success: bool, error: str = "") -> str:
        """步骤结束后调用，返回 'continue' 或 'abort'。"""
        if success:
            self.consecutive_failures = 0
            return "continue"
        self.consecutive_failures += 1
        if self.consecutive_failures >= self.max_failures:
            self.consecutive_failures = 0  # 询问后重置
            decision = self.ask_user(
                f"\n[Monitor] 步骤 {order} 已连续失败 {self.max_failures} 次"
                f"（最近错误：{error[:120]}）。\n"
                "请选择：continue(继续下一步) / abort(中止任务) [continue]: "
            )
            return decision if decision in ("continue", "abort") else "continue"
        return "continue"

    @staticmethod
    def detect_anomaly(vision_text: str) -> Optional[str]:
        """检测登录/验证码等需人工界面，返回提示或 None。"""
        low = (vision_text or "").lower()
        for kw in _ANOMALY_KEYWORDS:
            if kw.lower() in low:
                return f"检测到可能需要人工的界面（关键词：{kw}）"
        return None
