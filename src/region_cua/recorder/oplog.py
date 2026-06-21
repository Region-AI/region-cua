"""操作日志：把任务执行过程实时写入文本日志，便于事后排查。

设计要点：
- 每行立即 flush，进程被中断也能保留已写入部分
- 异常安全：写入失败不影响主流程
- 同时支持 enabled=False 退化为 no-op，避免 CLI 关闭时还要在调用点判空
"""

from __future__ import annotations

import io
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


class OperationLogger:
    def __init__(self, log_path: Optional[Path], enabled: bool = True):
        self.path = Path(log_path) if log_path else None
        self.enabled = bool(enabled and log_path)
        self._fp: Optional[io.TextIOBase] = None
        if self.enabled:
            assert self.path is not None
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self._fp = open(self.path, "w", encoding="utf-8", buffering=1)
            except Exception:
                self.enabled = False
                self._fp = None

    # -------------------------------------------------------- write helpers
    def _write(self, line: str) -> None:
        if not self.enabled or self._fp is None:
            return
        try:
            self._fp.write(line + "\n")
            self._fp.flush()
        except Exception:
            pass

    @staticmethod
    def _ts() -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

    # ---------------------------------------------------------- public log
    def header(self, task: str, planner_model: str, vision_model: str) -> None:
        self._write("=" * 70)
        self._write(f"[{self._ts()}] RegionCUA 任务日志")
        self._write(f"任务: {task}")
        self._write(f"规划模型: {planner_model}")
        self._write(f"视觉模型: {vision_model}")
        self._write("=" * 70)

    def plan(self, steps: list[Any]) -> None:
        self._write(f"\n[{self._ts()}] 规划完成（{len(steps)} 步）：")
        for i, s in enumerate(steps, 1):
            try:
                action = getattr(s, "action", "?")
                target = getattr(s, "target", "")
                desc = getattr(s, "description", "")
                self._write(f"  {i}. {action} | target={target!r} | {desc}")
            except Exception:
                self._write(f"  {i}. {s!r}")

    def step_start(self, order: int, step: Any) -> None:
        action = getattr(step, "action", "?")
        target = getattr(step, "target", "")
        desc = getattr(step, "description", "")
        self._write(f"\n[{self._ts()}] ▶ 步骤 {order}: action={action} target={target!r}")
        if desc:
            self._write(f"    说明: {desc}")

    def info(self, message: str) -> None:
        self._write(f"[{self._ts()}]   · {message}")

    def step_end(self, record: Any) -> None:
        order = getattr(record, "order", "?")
        ok = getattr(record, "success", False)
        err = getattr(record, "error", "") or ""
        analysis = getattr(record, "vision_analysis", "") or ""
        check = getattr(record, "vision_check", "") or ""
        before = getattr(record, "screenshot_before", "") or ""
        after = getattr(record, "screenshot_after", "") or ""

        status = "✓ 成功" if ok else "✗ 失败"
        self._write(f"[{self._ts()}] ◀ 步骤 {order} {status}")
        if before:
            self._write(f"    截图(前): {before}")
        if after:
            self._write(f"    截图(后): {after}")
        if analysis:
            self._write(f"    视觉定位: {self._oneline(analysis)}")
        if check:
            self._write(f"    操作验证: {self._oneline(check)}")
        if err:
            self._write(f"    错误: {err}")

    def aborted(self, reason: str) -> None:
        self._write(f"\n[{self._ts()}] ⚠ 任务被中止: {reason}")

    def fatal(self, exc: BaseException) -> None:
        self._write(f"\n[{self._ts()}] ✖ 致命异常: {type(exc).__name__}: {exc}")
        try:
            import traceback

            self._write(traceback.format_exc())
        except Exception:
            pass

    def summary(self, total: int, ok: int, video_path: Optional[Path] = None) -> None:
        self._write("\n" + "=" * 70)
        self._write(f"[{self._ts()}] 执行结束")
        self._write(f"步骤总数: {total} | 成功: {ok} | 失败: {total - ok}")
        if video_path:
            self._write(f"录屏: {video_path}")
        self._write("=" * 70)

    def close(self) -> None:
        if self._fp is not None:
            try:
                self._fp.flush()
                self._fp.close()
            except Exception:
                pass
            self._fp = None

    # ---------------------------------------------------------- helpers
    @staticmethod
    def _oneline(text: str, max_len: int = 200) -> str:
        if not isinstance(text, str):
            try:
                text = json.dumps(text, ensure_ascii=False)
            except Exception:
                text = str(text)
        text = " ".join(text.split())
        return text if len(text) <= max_len else text[: max_len - 3] + "..."

    # 上下文管理器
    def __enter__(self) -> "OperationLogger":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc is not None:
            try:
                self.fatal(exc)
            except Exception:
                pass
        self.close()
