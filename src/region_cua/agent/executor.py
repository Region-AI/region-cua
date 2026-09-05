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
from ..vision.protocol import VisionClient
from .models import Step, StepRecord, TaskPlan
from .monitor import Monitor


class TaskExecutor:
    def __init__(
        self,
        client: VisionClient,
        vision_model: str,
        task_dir: Path,
        monitor: Monitor,
        record_video: bool = True,
        record_log: bool = True,
        verify: bool = True,
        video_fps: int = 3,
        allow_lock: bool = False,
        backend: str = "foreground",
        window_keyword: Optional[str] = None,
        locate_method: str = "vlm",  # "vlm" 或 "omniparser"
        cua_backend: Optional[object] = None,  # CuaBackend 实例（trycua/qwen-ui）
    ):
        self.client = client
        self.vision_model = vision_model
        self.task_dir = task_dir
        self.shot_dir = task_dir / "screenshots"
        self.monitor = monitor
        self.verify = verify
        self.allow_lock = allow_lock
        self.backend = backend  # "foreground" 或 "background"
        self.window_keyword = window_keyword  # 后台模式截取的窗口关键词
        self.locate_method = locate_method  # "vlm" 或 "omniparser"
        self.cua_backend = cua_backend  # trycua / qwen-ui CuaBackend 实例
        self._omniparser = None  # OmniParser 延迟加载
        self.step_records: list[StepRecord] = []

        from ..recorder.video import VideoRecorder
        from ..recorder.oplog import OperationLogger

        self.video = VideoRecorder(task_dir, fps=video_fps) if record_video else None
        log_path = task_dir / "operation.log" if record_log else None
        self.logger = OperationLogger(log_path, enabled=record_log)

    # ------------------------------------------------------------- public
    def click(self, x: int, y: int, button: str = "left", clicks: int = 1) -> None:
        """统一点击：CUA backend 模式走 backend（scope:desktop，自带前台激活），否则 pyautogui。

        workflow 层必须用这个而不是直接 inp.click_at，保证 CUA backend 模式坐标/窗口一致。
        """
        if self.cua_backend is not None:
            try:
                self.cua_backend.ensure_target(self.window_keyword)
            except Exception:
                pass
            self.cua_backend.click(int(x), int(y), button=button, clicks=clicks)
        else:
            from ..automation import input as _inp
            _inp.click_at(int(x), int(y), button=button, clicks=clicks)

    def type(self, text: str) -> None:
        """统一输入：CUA backend 模式走 backend（type_text_safe 规避 IME + foreground 重试）。"""
        if self.cua_backend is not None:
            try:
                self.cua_backend.ensure_target(self.window_keyword)
            except Exception:
                pass
            self.cua_backend.type_text(text)
        else:
            from ..automation import input as _inp
            _inp.type_text(text)

    def hotkey(self, *keys: str) -> None:
        if self.cua_backend is not None:
            try:
                self.cua_backend.ensure_target(self.window_keyword)
            except Exception:
                pass
            self.cua_backend.hotkey(*keys)
        else:
            from ..automation import input as _inp
            _inp.press_hotkey(*keys)

    def scroll(self, amount: int) -> None:
        if self.cua_backend is not None:
            try:
                self.cua_backend.ensure_target(self.window_keyword)
            except Exception:
                pass
            self.cua_backend.scroll(int(amount))
        else:
            from ..automation import input as _inp
            _inp.scroll(int(amount))

    def execute(self, plan: TaskPlan) -> list[StepRecord]:
        from ..automation.awake import keep_awake

        self.logger.header(plan.task, "(planner)", self.vision_model)
        self.logger.plan(plan.steps)

        from datetime import datetime

        task_started = datetime.now()
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
                # 导出结构化轨迹
                from ..recorder.trajectory import export_trajectory

                task_ended = datetime.now()
                try:
                    export_trajectory(plan, self.step_records, self.task_dir, task_started, task_ended)
                except Exception as exc:
                    self.logger.info(f"轨迹导出失败: {exc}")
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
            # 窗口激活：在截图前先激活（确保拍到任务页面而非桌面壁纸）
            if step.normalized_action() == "workflow" or (step.requires_vision and step.normalized_action() == "click"):
                if self.window_keyword:
                    self._activate_target_window()
                    time.sleep(0.5)
            before = self._capture(f"step{order}_{ts}_before")
            record.screenshot_before = before

            # 视觉定位（仅 click 且 requires_vision）
            if step.requires_vision and step.normalized_action() == "click":
                # 截图前激活目标窗口到前台（确保截图能看到页面内容）
                if self.window_keyword:
                    self._activate_target_window()
                    time.sleep(0.5)
                    before = self._capture(f"step{order}_{ts}_before")
                    record.screenshot_before = before
                coords, analysis = self._locate(before, step.target)
                record.vision_analysis = analysis
                if coords:
                    step = step.model_copy(update={"target": f"{coords[0]},{coords[1]}"})
                else:
                    # 第一次没找到 → 重新截图+解析再试一次（可能页面刚加载完）
                    self.logger.info(f"首次定位失败，重新截图重试…")
                    time.sleep(1.5)
                    if self.window_keyword:
                        self._activate_target_window()
                        time.sleep(0.3)
                    before = self._capture(f"step{order}_{ts}_before_retry")
                    record.screenshot_before = before
                    coords, analysis = self._locate(before, step.target)
                    record.vision_analysis = analysis + " (重试)"
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
            if self.backend == "background":
                # 后台模式：不抢前台，记录窗口关键词供后续后台截图
                kw = step.target.replace(".exe", "").replace(".lnk", "").strip()
                self.window_keyword = kw.split()[0] if " " in kw else kw
                self.logger.info(f"后台模式：窗口关键词设为 {self.window_keyword!r}")
            else:
                # 前台模式：把窗口拉到前台
                from ..automation.windows import activate_after_open

                activate_after_open(step.target, wait=3.0)
        elif action == "click":
            self._do_click(step)
        elif action == "type":
            if self.cua_backend is not None:
                self.cua_backend.ensure_target(self.window_keyword)
                self.cua_backend.type_text(step.target)
            elif self.backend == "background" and self.window_keyword:
                self._type_bg(step)
            else:
                inp.type_text(step.target)
        elif action == "hotkey":
            if self.cua_backend is not None:
                try:
                    self.cua_backend.ensure_target(self.window_keyword)
                    self.cua_backend.hotkey(step.target)
                except Exception:
                    pass
            else:
                try:
                    inp.press_hotkey(step.target)
                except Exception:
                    pass  # 非法组合键跳过
        elif action == "scroll":
            if self.cua_backend is not None:
                try:
                    self.cua_backend.ensure_target(self.window_keyword)
                    self.cua_backend.scroll(int(step.target))
                except (TypeError, ValueError):
                    self.cua_backend.scroll(-3)
            else:
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
        elif action == "workflow":
            # Activate window before workflow (same as click requires_vision)
            if self.window_keyword:
                self._activate_target_window()
                time.sleep(0.5)
            try:
                import importlib as _im
                wf_mod = _im.import_module("region_cua.bench.workflows")
                result = wf_mod.run_workflow(step.value or step.target, self, step)
                self.logger.info(f"工作流: {result}")
            except Exception as exc:
                self.logger.error(f"工作流执行失败: {exc}")
        else:
            raise ValueError(f"未知 action: {action}")

    def _type_bg(self, step: Step) -> None:
        """后台输入文本：优先 UIA ValuePattern，退回 PostMessage WM_CHAR。"""
        from ..automation import bg_ops
        from ..automation.windows import find_window_by_title

        hwnd = find_window_by_title(self.window_keyword or "")
        if not hwnd:
            self.logger.info(f"后台输入退回前台（未找到窗口 {self.window_keyword!r}）")
            inp.type_text(step.target)
            return
        # 尝试 UIA 按名称设值（适合已知控件名的文本框）
        ok = False
        try:
            ok = bg_ops.set_value_by_uia(step.target, step.target)
        except Exception:
            pass
        if not ok:
            try:
                bg_ops.type_text_bg(hwnd, step.target)
            except Exception as exc:
                self.logger.info(f"后台输入失败，退回前台: {exc}")
                inp.type_text(step.target)

    def _do_click(self, step: Step) -> None:
        x, y = self._parse_coords(step.target)
        if x is None:
            # 无法定位坐标 → 点击屏幕中心，避免 (0,0) failsafe
            from ..vision.screenshot import screen_size

            w, h = screen_size()
            x, y = w // 2, h // 2
        else:
            # 后台模式：截图坐标是窗口相对坐标，需转换为屏幕绝对坐标
            # （CUA backend 例外：backend 截图即窗口截图，cua-driver click 期望窗口内坐标，
            #  故不加偏移；只有非 CUA 的 background 模式才加偏移给前台输入）
            if self.backend == "background" and self.window_keyword and self.cua_backend is None:
                offset = self._get_window_offset()
                if offset:
                    x += offset[0]
                    y += offset[1]
                    self.logger.info(f"后台坐标转换: 截图({x-offset[0]},{y-offset[1]}) → 屏幕({x},{y})")

        # 查控件交互策略：决定单击/双击/右键
        button = "left"
        clicks = 1
        v = (step.value or "").lower()
        if "double" in v:
            clicks = 2
        elif "right" in v:
            button = "right"
        elif "middle" in v:
            button = "middle"
        else:
            # 查知识库：根据 target 文字推断控件类型
            try:
                from ..vision.control_kb import get_strategy
                strategy = get_strategy(step.target)
                if strategy.get("button"):
                    button = strategy["button"]
                if strategy.get("clicks"):
                    clicks = strategy["clicks"]
                if strategy.get("notes"):
                    self.logger.info(f"控件策略({strategy['control_type']}): {strategy['notes']}")
            except Exception:
                pass

        # CUA backend 模式：坐标已是窗口内坐标（截图即窗口截图），直接走 backend 点击
        if self.cua_backend is not None:
            self.cua_backend.ensure_target(self.window_keyword)
            self.cua_backend.click(int(x), int(y), button=button, clicks=clicks)
        else:
            inp.click_at(int(x), int(y), button=button, clicks=clicks)

    def _get_window_offset(self) -> Optional[tuple[int, int]]:
        """获取目标窗口在屏幕上的左上角偏移（用于后台坐标转换）。"""
        if not self.window_keyword:
            return None
        try:
            import ctypes
            import ctypes.wintypes
            user32 = ctypes.windll.user32
            result = [None]

            @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)
            def _enum(hwnd, _lparam):
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buf = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buf, length + 1)
                    if self.window_keyword.lower() in buf.value.lower():
                        rect = ctypes.wintypes.RECT()
                        user32.GetWindowRect(hwnd, ctypes.byref(rect))
                        result[0] = (rect.left, rect.top)
                        return False  # 找到就停
                return True

            user32.EnumWindows(_enum, 0)
            return result[0]
        except Exception:
            return None

    def _activate_target_window(self) -> None:
        """激活目标窗口到前台（确保截图能看到页面内容）。

        Windows 不允许后台进程直接抢前台，需要用 Alt 键技巧绕过限制。
        CUA backend 模式用 cua-driver bring_to_front（AttachThreadInput，更可靠）。
        """
        if not self.window_keyword:
            return
        if self.cua_backend is not None:
            try:
                self.cua_backend.activate_window(self.window_keyword)
            except Exception:
                pass
            return
        try:
            import ctypes
            user32 = ctypes.windll.user32
            hwnd = None

            @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)
            def _enum(h, lctx):
                nonlocal hwnd
                if hwnd is not None:
                    return True
                length = user32.GetWindowTextLengthW(h)
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(h, buf, length + 1)
                title_lower = buf.value.lower()
                # Exact substring match (e.g. keyword="Select Dropdown Task" matches window title)
                if self.window_keyword.lower() in title_lower:
                    hwnd = h
                    return False
                # Broader fallback: any CuaBrowser / WebView2 class, short task-like title
                wc = ctypes.create_unicode_buffer(512)
                user32.GetClassNameW(h, wc, 512)
                if "CuaBrowser" in wc.value or "WebView2" in wc.value:
                    # Exclude standard apps/Edge tabs/explorer windows
                    excluded = ("microsoft edge", "explorer", "程序管理器", "chrome")
                    if len(buf.value) < 60 and not any(e in title_lower for e in excluded):
                        hwnd = h
                        return False
                return True

            user32.EnumWindows(_enum, 0)
            if hwnd:
                # Alt key trick to bypass Windows foreground restrictions
                user32.keybd_event(0x12, 0, 0, 0)       # Alt down
                user32.keybd_event(0x12, 0, 0x0002, 0)  # Alt up
                import time as _t
                _t.sleep(0.1)
                try:
                    user32.SetForegroundWindow(hwnd)
                except Exception:
                    pass
        except Exception:
            pass

    # ------------------------------------------------------------- vision
    def _locate(self, screenshot_path: str, target_desc: str) -> tuple[Optional[tuple[int, int]], str]:
        """在截图中定位 target_desc 描述的元素，返回 (坐标, 分析文本)。

        支持三种定位方式：
        - cua_backend (trycua/qwen-ui): 统一 CUA backend 定位（优先）
        - omniparser: YOLO+OCR 解析元素列表 + 文字匹配（不需要 VLM，快且准）
        - vlm: 视觉模型直接输出坐标（需要 Ollama VLM，慢且不准）
        """
        # 定位策略：OmniParser（YOLO+OCR 文字匹配）实测最准最稳，作主路径。
        # CUA backend（trycua UIA / qwen-ui VLM）仅当 OmniParser 未命中时兜底。
        if self.locate_method == "omniparser":
            res = self._locate_omniparser(screenshot_path, target_desc)
            if res[0] is not None:
                return res
            # OmniParser 未命中 → 尝试 CUA backend 定位
            if self.cua_backend is not None:
                loc = self.cua_backend.locate(screenshot_path, target_desc)
                if loc.found:
                    return (loc.to_tuple(), loc.analysis)
            return res
        # 非 omniparser（vlm）模式
        if self.cua_backend is not None:
            loc = self.cua_backend.locate(screenshot_path, target_desc)
            if loc.found:
                return (loc.to_tuple(), loc.analysis)
            return self._locate_omniparser(screenshot_path, target_desc)
        return self._locate_vlm(screenshot_path, target_desc)

    def _locate_omniparser(self, screenshot_path: str, target_desc: str) -> tuple[Optional[tuple[int, int]], str]:
        """用 OmniParser（YOLO+OCR+VLM）定位元素。

        匹配：OCR 文字 + VLM 图标描述（parse 阶段已合并）→ 统一文字匹配
        """
        try:
            from ..vision.omniparser import OmniParser
            if not hasattr(self, "_omniparser") or self._omniparser is None:
                self._omniparser = OmniParser(enable_vlm_icons=False)
            elements = self._omniparser.parse(screenshot_path)
            elem = self._omniparser.find_element(elements, target_desc, screenshot_path)
            if elem:
                cx, cy = elem["center"]
                if elem.get("bbox"):
                    bx1, by1, bx2, by2 = elem["bbox"]
                    h = by2 - by1
                    if h < 35:  # label/小文字区域高度小 → 向下偏移到输入框
                        cy += 25
                        self.logger.info(f"Label 偏移: ({cx},{cy-25}) → ({cx},{cy})")
                    elif h > 60:
                        # OCR 把相邻多行元素合并成大框（如右键菜单 Copy+Paste+Cut 合并）：
                        # 目标文字通常在最顶部，点击框的上 1/4 处而非中心
                        cy = by1 + h // 4
                        self.logger.info(f"高元素修正: 高度{h}px, center({cx},{cy}) → 上1/4({cx},{cy})")
                return (cx, cy), f'OmniParser: 找到「{elem.get("text", target_desc)}」at ({cx},{cy})'
            return None, f"OmniParser: 未找到「{target_desc}」，检测到 {len(elements)} 个元素"
        except Exception as exc:
            return None, f"OmniParser 定位失败: {exc}"

    def _locate_vlm(self, screenshot_path: str, target_desc: str) -> tuple[Optional[tuple[int, int]], str]:
        """用视觉模型在截图中定位 target_desc 描述的元素，返回 (坐标, 分析文本)。"""
        prompt = (
            f"这是一张电脑屏幕截图（可能是浏览器网页或桌面应用）。"
            f"请仔细查找「{target_desc}」这个界面元素的位置。"
            f"如果找到了，返回该元素中心点的像素坐标。\n"
            f"返回严格 JSON：\n"
            '{"found": true, "x": 整数, "y": 整数, "description": "简短描述"}\n'
            '如果找不到则返回：{"found": false, "x": 0, "y": 0, "description": "未找到"}\n'
            "坐标基于截图左上角原点(0,0)，x 向右增 y 向下增。只输出 JSON，不要其他文字。"
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
        # CUA backend 模式：用 capture_screen()（mss 全屏）。
        # 关键：PrintWindow 截窗口对浏览器页面是空白的（页面内容不渲染，
        # 见 skill troubleshooting），必须全屏截图。前提是目标窗口在前台
        # （bench_runner 已 _activate_window）。坐标=屏幕绝对坐标。
        if self.cua_backend is not None:
            # CUA backend：截目标窗口（get_window_state，不依赖前台），坐标=窗口内
            try:
                return self.cua_backend.capture(str(path), self.window_keyword)
            except Exception:
                # 回退全屏
                img = shot.capture_screen()
                return shot.save_screenshot(img, path)
        kw = self.window_keyword if self.backend == "background" else None
        img = shot.capture(window_keyword=kw)
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
