"""TaskExecutor：逐步骤执行任务。

每步流程：
  1. 截图（before）
  2. 若需要视觉且为 click → 调视觉模型定位坐标，覆盖 target
  3. 执行动作（open_app/click/type/hotkey/scroll/wait/screenshot/done）
  4. 截图（after）
  5. vision_check 验证操作是否成功
  6. 记录 StepRecord；失败计入 Monitor 连续计数

避坑（来自调试记录，均已落实）：
- 直接遍历 plan.steps，用循环索引而非 step.order 取列表元素，杜绝越界
- 每个 action 分支与每次 vision 调用都 try-except，单步失败不中断整体
- 不点击 (0,0)；坐标非法时回退屏幕中心
- scroll/hotkey/wait 的 target 非法时用安全默认值
"""

from __future__ import annotations

import re
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..automation import appfinder, input as inp
from ..vision import screenshot as shot
from ..vision.ollama_client import OllamaClient
from .models import Step, StepRecord, TaskPlan
from .monitor import Monitor


class TaskExecutor:
    def __init__(
        self,
        client: OllamaClient,
        vision_model: str,
        task_dir: Path,
        monitor: Monitor,
        record_video: bool = True,
        record_log: bool = True,
        verify: bool = True,
        video_fps: int = 3,
        allow_lock: bool = False,
    ):
        self.client = client
        self.vision_model = vision_model
        self.task_dir = task_dir
        self.shot_dir = task_dir / "screenshots"
        self.monitor = monitor
        self.verify = verify
        self.allow_lock = allow_lock
        self.step_records: list[StepRecord] = []

        from ..recorder.video import VideoRecorder
        from ..recorder.oplog import OperationLogger

        self.video = VideoRecorder(task_dir, fps=video_fps) if record_video else None
        log_path = task_dir / "operation.log" if record_log else None
        self.logger = OperationLogger(log_path, enabled=record_log)

    # ------------------------------------------------------------- public
    def execute(self, plan: TaskPlan) -> list[StepRecord]:
        from ..automation.awake import keep_awake

        self.logger.header(plan.task, "(planner)", self.vision_model)
        self.logger.plan(plan.steps)

        with keep_awake(enabled=not self.allow_lock):
            if self.video:
                self.video.start()
                self.logger.info(f"录屏已启动: {self.video.path}")
            try:
                for i, step in enumerate(plan.steps):
                    self.logger.step_start(i + 1, step)
                    record = self._run_step(step, i)
                    self.step_records.append(record)
                    self.logger.step_end(record)
                    decision = self.monitor.on_step(i + 1, record.success, record.error)
                    if decision == "abort":
                        self.logger.aborted(f"Monitor 决定中止（连续失败达阈值）")
                        break
                    if step.normalized_action() == "done":
                        self.logger.info("收到 done 动作，提前结束")
                        break
            except BaseException as exc:
                # 异常也要落盘日志和录屏
                self.logger.fatal(exc)
                raise
            finally:
                video_path = None
                if self.video:
                    try:
                        video_path = self.video.stop()
                        if video_path:
                            self.logger.info(f"录屏已保存: {video_path}")
                        else:
                            self.logger.info("录屏未生成（无帧或编码失败）")
                    except Exception as exc:
                        self.logger.info(f"录屏停止异常: {exc}")
                ok = sum(1 for r in self.step_records if r.success)
                self.logger.summary(len(self.step_records), ok, video_path)
                self.logger.close()
            return self.step_records

    # ------------------------------------------------------------- per step
    def _run_step(self, step: Step, index: int) -> StepRecord:
        order = index + 1
        ts = datetime.now().strftime("%H%M%S")
        record = StepRecord(
            order=order,
            action=step.normalized_action(),
            description=step.description,
            target=step.target,
            value=step.value,
            timestamp=ts,
        )
        try:
            before = self._capture(f"step{order}_{ts}_before")
            record.screenshot_before = before

            # 视觉定位（仅 click 且 requires_vision）
            if step.requires_vision and step.normalized_action() == "click":
                coords, analysis = self._locate(before, step.target)
                record.vision_analysis = analysis
                if coords:
                    step = step.model_copy(update={"target": f"{coords[0]},{coords[1]}"})

            self._do_action(step)
            time.sleep(1.0)

            after = self._capture(f"step{order}_{ts}_after")
            record.screenshot_after = after

            if self.verify:
                record.vision_check = self._vision_check(after, step)
            record.success = True
        except Exception as exc:  # 单步失败隔离
            record.success = False
            record.error = str(exc)
        return record

    # ------------------------------------------------------------- actions
    def _do_action(self, step: Step) -> None:
        action = step.normalized_action()
        if action == "open_app":
            appfinder.open_app(step.target)
            # 启动后把窗口拉到前台，否则截图会截到其他窗口
            from ..automation.windows import activate_after_open

            activate_after_open(step.target, wait=3.0)
        elif action == "click":
            self._do_click(step)
        elif action == "type":
            inp.type_text(step.target)
        elif action == "hotkey":
            try:
                inp.press_hotkey(step.target)
            except Exception:
                pass  # 非法组合键跳过
        elif action == "scroll":
            try:
                inp.scroll(int(step.target))
            except (TypeError, ValueError):
                inp.scroll(-3)
        elif action == "wait":
            inp.wait(step.target)
        elif action == "screenshot":
            pass  # 已截图
        elif action == "done":
            pass
        else:
            raise ValueError(f"未知 action: {action}")

    def _do_click(self, step: Step) -> None:
        x, y = self._parse_coords(step.target)
        if x is None:
            # 无法定位坐标 → 点击屏幕中心，避免 (0,0) failsafe
            from ..vision.screenshot import screen_size

            w, h = screen_size()
            x, y = w // 2, h // 2
        button = "left"
        clicks = 1
        v = (step.value or "").lower()
        if "double" in v:
            clicks = 2
        elif "right" in v:
            button = "right"
        elif "middle" in v:
            button = "middle"
        inp.click_at(int(x), int(y), button=button, clicks=clicks)

    # ------------------------------------------------------------- vision
    def _locate(self, screenshot_path: str, target_desc: str) -> tuple[Optional[tuple[int, int]], str]:
        """让视觉模型在截图中定位 target_desc 描述的元素，返回 (坐标, 分析文本)。"""
        prompt = (
            f"请在截图中找到「{target_desc}」这个界面元素，返回严格 JSON：\n"
            '{"found": true/false, "x": 整数, "y": 整数, "description": "简短中文描述"}\n'
            "坐标基于截图左上角原点。只输出 JSON。"
        )
        try:
            text = self.client.chat(
                self.vision_model,
                [{"role": "user", "content": prompt}],
                images=[screenshot_path],
            )
        except Exception as exc:
            return None, f"视觉定位失败: {exc}"
        coords = self._extract_coords(text)
        return coords, text

    def _vision_check(self, screenshot_path: str, step: Step) -> str:
        prompt = (
            f"刚执行了操作「{step.action}」（目标：{step.target or step.description}）。"
            "请根据截图判断该操作是否成功达成预期。返回严格 JSON：\n"
            '{"success": true/false, "reason": "简短中文说明"}\n只输出 JSON。'
        )
        try:
            return self.client.chat(
                self.vision_model,
                [{"role": "user", "content": prompt}],
                images=[screenshot_path],
            )
        except Exception as exc:
            return f"验证失败: {exc}"

    # ------------------------------------------------------------- utils
    def _capture(self, name: str) -> str:
        path = self.shot_dir / f"{name}.png"
        img = shot.capture_screen()
        return shot.save_screenshot(img, path)

    @staticmethod
    def _parse_coords(target: str) -> tuple[Optional[int], Optional[int]]:
        """从 'x,y' 字符串解析坐标。"""
        if not target:
            return None, None
        m = re.match(r"\s*(\d+)\s*[,，]\s*(\d+)\s*$", target)
        if not m:
            return None, None
        return int(m.group(1)), int(m.group(2))

    @staticmethod
    def _extract_coords(text: str) -> Optional[tuple[int, int]]:
        """从视觉模型 JSON 文本中提取 x,y。"""
        if not text:
            return None
        # 尝试整体或片段解析
        for candidate in (text,):
            m = re.search(r"\{[^{}]*\}", candidate, re.DOTALL)
            if not m:
                continue
            try:
                import json as _json

                obj = _json.loads(m.group(0))
                if obj.get("found") is False:
                    return None
                x, y = obj.get("x"), obj.get("y")
                if isinstance(x, int) and isinstance(y, int):
                    return x, y
            except Exception:
                continue
        return None
