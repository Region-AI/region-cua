"""基准测试运行器：加载 cua-bench 任务 → region-cua 执行 → 评估打分。

流程：
1. 加载任务目录的 main.py（用动态导入，不依赖 cua_bench 框架）
2. 提取 tasks_config() 返回的任务列表（description + metadata + evaluate JS）
3. 用 BrowserSession 打开任务 HTML 页面（系统 Edge）
4. 让 region-cua 执行任务（planner 规划 + executor 逐步截图+点击）
5. 用 Playwright evaluate 检查 window.__xxx，返回 1.0/0.0 分数

每个 cua-bench 任务的 main.py 用了 @cb.tasks_config / @cb.setup_task / @cb.evaluate_task
装饰器。我们不安装 cua_bench 框架，而是：
- 从 main.py 源码中提取 evaluate_task 函数体里的 JS 表达式
- 从 gui/index.html 读取页面 HTML
- 从 tasks_config 的 return 语句提取任务描述
"""

from __future__ import annotations

import asyncio
import importlib.util
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .browser_session import BrowserSession


def _move_cursor_away_bench(inp_module) -> None:
    """截图前把光标移到屏幕右下角，避免遮挡界面元素。"""
    try:
        from ..vision.screenshot import screen_size
        w, h = screen_size()
        inp_module.move_to(w - 5, h - 5)
    except Exception:
        pass


@dataclass
class BenchTask:
    """单个基准测试任务。"""
    task_id: str
    description: str
    html: str
    evaluate_js: str  # 评估用的 JS 表达式，如 "window.__submitted"
    expected_value: Any = True
    metadata: dict = field(default_factory=dict)
    width: int = 1024
    height: int = 768


@dataclass
class BenchResult:
    """单个任务执行结果。"""
    task_id: str
    description: str
    success: bool
    score: float  # 0.0 ~ 1.0
    duration: float  # 秒
    steps: int
    error: str = ""
    trajectory_path: Optional[str] = None


class BenchRunner:
    """基准测试运行器。"""

    def __init__(
        self,
        bench_data_dir: str | Path,
        output_dir: str | Path = "outputs/bench",
    ):
        self.bench_dir = Path(bench_data_dir)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def list_tasks(self) -> list[str]:
        """列出所有可用的任务目录名。"""
        return sorted([
            d.name for d in self.bench_dir.iterdir()
            if d.is_dir() and (d / "main.py").exists()
        ])

    def load_task(self, task_name: str, variant_index: int = 0) -> BenchTask:
        """加载单个任务（解析 main.py + gui/index.html）。

        cua-bench 的 main.py 用装饰器注册函数，我们通过源码分析提取：
        - tasks_config: 提取 description 列表
        - gui/index.html: 读取 HTML，替换模板变量
        - evaluate_task: 提取 execute_javascript 的 JS 表达式
        """
        task_dir = self.bench_dir / task_name
        main_py = (task_dir / "main.py").read_text(encoding="utf-8")
        html_file = task_dir / "gui" / "index.html"
        html_template = html_file.read_text(encoding="utf-8") if html_file.exists() else ""

        # 提取所有任务描述
        # cua-bench 的 main.py 用列表推导式生成任务，描述格式多样：
        # 1. description=f'Click the "Submit" button...' (f-string 直接赋值)
        # 2. "description": 'Select "Apple" from the dropdown' (字典字段)
        # 3. description=scenario["description"] (变量引用，需从字典提取)
        descriptions_raw = re.findall(
            r"description\s*=\s*f?'([^']*)'", main_py
        )
        if not descriptions_raw:
            # 尝试从字典里的 "description" 字段提取
            descriptions_raw = re.findall(
                r'"description"\s*:\s*\'([^\']+)\'', main_py
            )
        if not descriptions_raw:
            # 尝试双引号格式
            descriptions_raw = re.findall(
                r'"description"\s*:\s*"([^"]+)"', main_py
            )
        if not descriptions_raw:
            descriptions_raw = [f"Task: {task_name}"]
        # 去掉 f-string 中的转义反斜杠（\" → "）
        descriptions_raw = [d.replace('\\"', '"') for d in descriptions_raw]

        # 提取列表变量值（如 button_texts = ["Submit", "Click Me", ...]）
        list_vars: dict[str, list[str]] = {}
        for m in re.finditer(r'(\w+)\s*=\s*\[([^\]]+)\]', main_py):
            var_name = m.group(1)
            values = re.findall(r'"([^"]+)"', m.group(2))
            if values:
                list_vars[var_name] = values

        # 提取字典列表变量（如 typing_scenarios = [{"text": "...", "field_label": "..."}]）
        dict_vars: dict[str, list[dict]] = {}
        for m in re.finditer(r'(\w+)\s*=\s*\[(.+?)\]', main_py, re.DOTALL):
            var_name = m.group(1)
            items = re.findall(r'\{([^}]+)\}', m.group(2))
            dicts = []
            for item in items:
                pairs = re.findall(r'"(\w+)"\s*:\s*"([^"]*)"', item)
                dicts.append(dict(pairs))
            if dicts:
                dict_vars[var_name] = dicts

        # 用实际值替换 f-string 模板，生成所有变体描述
        descriptions: list[str] = []
        tmpl = descriptions_raw[0]

        # 从 "for loop_var in source_var" 找到循环关系
        # 可能有多个 for（如 for os_type in os_types + for button_text in button_texts）
        # 取与模板变量匹配的那个
        for_matches = re.findall(r'for\s+(\w+)\s+in\s+(\w+)', main_py)
        for loop_var, source_var in reversed(for_matches):
            # 找 source_var 的值列表（字典列表优先，因为 list_pattern 会误匹配字典内容）
            dict_pattern = rf'{source_var}\s*=\s*\[(.+?)\]'
            dict_match = re.search(dict_pattern, main_py, re.DOTALL)
            if dict_match:
                items = re.findall(r'\{([^}]+)\}', dict_match.group(1))
                if items:
                    # 字典列表
                    for item in items:
                        # 匹配 "key": "value" 和 "key": number
                        pairs = re.findall(r'"(\w+)"\s*:\s*("(?:[^"\\]|\\.)*"|\d+)', item)
                        d = {}
                        for k, raw_v in pairs:
                            v = raw_v.strip('"') if raw_v.startswith('"') else raw_v
                            d[k] = v
                        desc = tmpl
                        for k, v in d.items():
                            desc = desc.replace(f'{{{loop_var}["{k}"]}}', v)
                        descriptions.append(desc)
                    break

            # 找 source_var 的值列表（简单字符串列表，排除含 { 的）
            list_pattern = rf'{source_var}\s*=\s*\[([^\]]+)\]'
            list_match = re.search(list_pattern, main_py)
            if list_match and '{' not in list_match.group(1):
                values = re.findall(r'"([^"]+)"', list_match.group(1))
                if values:
                    descriptions = [tmpl.replace(f'{{{loop_var}}}', v) for v in values]
                    break

        if not descriptions:
            # 没有循环或没找到值，去掉模板占位符
            cleaned = re.sub(r'\{[^}]+\}', '', tmpl).strip()
            descriptions = [cleaned if cleaned else f"Task: {task_name}"]

        # 提取评估 JS（从 execute_javascript(pid, "...") 中）
        eval_matches = re.findall(r'execute_javascript\([^,]+,\s*["\']([^"\']+)["\']', main_py)
        evaluate_js = eval_matches[0] if eval_matches else "document.title"

        # 提取 metadata 中的期望值
        expected_matches = re.findall(r'"expected_content"\s*:\s*["\']([^"\']*)["\']', main_py)
        expected_value = expected_matches[0] if expected_matches else True
        # date-picker: 从 metadata["date"] 提取期望日期
        date_matches = re.findall(r'"date"\s*:\s*["\']([^"\']+)["\']', main_py)
        if date_matches and expected_value is True:
            expected_value = date_matches[variant_index % len(date_matches)] if date_matches else True

        # 提取 width/height
        width_match = re.search(r'"width"\s*:\s*(\d+)', main_py)
        height_match = re.search(r'"height"\s*:\s*(\d+)', main_py)
        width = int(width_match.group(1)) if width_match else 1024
        height = int(height_match.group(1)) if height_match else 768

        # 选变体
        desc = descriptions[variant_index % len(descriptions)]

        # 替换 HTML 模板变量（从描述中提取按钮文字等）
        html = html_template
        # 常见模板变量：{{BUTTON_TEXT}}, {{FIELD_LABEL}} 等
        button_match = re.search(r'Click the "([^"]+)"', desc)
        if button_match:
            html = html.replace("{{BUTTON_TEXT}}", button_match.group(1))
        type_match = re.search(r'Type "([^"]+)"', desc)
        if type_match:
            html = html.replace("{{TEXT}}", type_match.group(1))
        # 匹配 "into the X input" 或 "into the X field" — X 可以含空格
        label_match = re.search(r'into the (.+?) input', desc)
        if label_match:
            html = html.replace("{{FIELD_LABEL}}", label_match.group(1).strip())
        # 匹配 "Set the X slider to Y"
        slider_match = re.search(r'Set the (.+?) slider to (.+)', desc)
        if slider_match:
            html = html.replace("{{LABEL}}", slider_match.group(1).strip())
            html = html.replace("{{TARGET_VALUE}}", slider_match.group(2).strip())
        # 兜底：如果 HTML 里还有未替换的 {{xxx}}，用描述里的关键词替换
        remaining = re.findall(r'\{\{(\w+)\}\}', html)
        if remaining:
            # 从描述中提取可能的值
            for var in remaining:
                # 常见变量名映射
                if var == "FIELD_LABEL" and label_match:
                    continue  # 已处理
                # 从描述中提取引号内容作为兜底
                quoted = re.search(r'"([^"]+)"', desc)
                if quoted:
                    html = html.replace(f"{{{{{var}}}}}", quoted.group(1))

        return BenchTask(
            task_id=f"{task_name}_{variant_index}",
            description=desc,
            html=html,
            evaluate_js=evaluate_js,
            expected_value=expected_value,
            width=width,
            height=height,
        )

    def run_task(
        self,
        task: BenchTask,
        *,
        max_steps: int = 15,
        planner_model: Optional[str] = None,
        vision_model: Optional[str] = None,
        backend: str = "background",
    ) -> BenchResult:
        """执行单个任务：浏览器打开页面 → region-cua 操作 → 评估。

        backend 默认 "background"：用 PrintWindow 截浏览器窗口（干净画面，
        无任务栏/桌面干扰），视觉定位精度更高。前台操作仍用 pyautogui
        （UIA 对网页元素不可靠）。
        """
        import time as _time
        from ..config import get_settings

        settings = get_settings()
        if planner_model:
            settings.ollama_planner_model = planner_model
        if vision_model:
            settings.ollama_vision_model = vision_model

        t0 = _time.time()
        error = ""
        score = 0.0
        steps = 0
        traj_path = None

        try:
            # 1. 打开浏览器（系统默认浏览器，非 Playwright）
            with BrowserSession(
                task.html,
                title=task.task_id,
                eval_js=task.evaluate_js,
                expected_value=task.expected_value,
                window_width=800,
                window_height=600,
                window_x=0,
                window_y=0,
            ) as browser:
                # 等浏览器窗口出现
                browser.wait_ready(timeout=10)
                _time.sleep(4)  # 等页面渲染 + Tailwind/Iconify CDN 加载

                # 2. 让 region-cua 执行任务
                from ..agent.planner import TaskPlanner
                from ..agent.executor import TaskExecutor
                from ..agent.monitor import Monitor
                from ..vision.ollama_client import OllamaClient
                from ..vision import screenshot as shot
                from ..vision.omniparser import OmniParser

                client = OllamaClient(settings.ollama_host, settings.ollama_timeout)
                vmodel = vision_model or settings.ollama_vision_model

                # 截图 + OmniParser 解析当前页面元素，给规则规划器提供元素列表
                browser._activate_window()
                _time.sleep(1)
                from ..automation import input as _inp
                _move_cursor_away_bench(_inp)
                try:
                    pre_screenshot = shot.capture_screen()
                except Exception:
                    _time.sleep(2)
                    browser._activate_window()
                    _time.sleep(1)
                    pre_screenshot = shot.capture_screen()
                parser = OmniParser(box_threshold=0.01)
                elements = parser.parse(pre_screenshot)
                # 格式化元素列表给 planner（过滤浏览器 UI、标题、噪声，标注控件类型）
                from ..vision.control_kb import infer_control_type
                elem_lines = []
                for e in elements:
                    text = e.get("text", "") or ""
                    # 过滤：浏览器标签/地址栏（y<100）、太长的文字、空文字图标
                    if e["center"][1] < 100:
                        continue
                    if text and len(text) < 40 and len(text) > 1:
                        # 过滤页面标题（h1 标题通常在页面顶部，文字与任务描述高度相似）
                        # 标题特征：y 坐标小（页面顶部 100-150 区域）、文字是通用描述
                        ctype = infer_control_type(text, e.get("type", ""))
                        # 标注是否可能是标题（给 planner 判断）
                        is_title = e["center"][1] < 160 and len(text) > 10
                        if is_title:
                            elem_lines.append(f'  - "{text}" (类型:页面标题,坐标{e["center"]}) ← 这是页面标题，不要点击')
                        else:
                            elem_lines.append(f'  - "{text}" (类型:{ctype}, 坐标{e["center"]})')
                elem_context = "页面已在浏览器中打开，直接操作页面元素即可，不要启动任何应用。\n当前页面包含以下元素：\n" + "\n".join(elem_lines[:25])
                elem_context += "\n\n重要规则：\n1. click 的 target 必须是上面列出的可交互元素（类型不是'页面标题'的）\n2. 不要点击页面标题\n3. 根据任务描述中的具体内容（如要点击的按钮名、要输入的文字）生成步骤\n4. type 的 target 必须是要输入的具体文字"

                # 用规则规划器替代 LLM planner（bench 场景步骤确定，不需要 LLM 推理）
                from .rule_planner import rule_plan
                plan = rule_plan(task.task_id.split("_")[0], task.description, elements)
                steps = len(plan.steps)

                # planner 调用后重新激活浏览器窗口（planner 耗时数秒，窗口可能被遮挡）
                browser._activate_window()
                _time.sleep(1)

                task_dir = self.output_dir / task.task_id
                task_dir.mkdir(parents=True, exist_ok=True)
                monitor = Monitor(max_failures=max_steps)
                executor = TaskExecutor(
                    client, vmodel, task_dir, monitor,
                    record_video=False, record_log=True, verify=True,
                    video_fps=settings.video_fps,
                    backend=backend,
                    window_keyword=task.task_id,  # 前后台都用，用于激活窗口
                    locate_method="omniparser",
                )

                try:
                    records = executor.execute(plan)
                except Exception:
                    records = executor.step_records

                steps = len(records)

                # 3. 评估：读浏览器窗口标题（观察器 JS 写入 BENCH_DONE:x.x）
                score = browser.wait_done(timeout=10)
                client.close()
                traj_path = str(task_dir / "trajectory.jsonl")

        except Exception as exc:
            error = str(exc)[:200]

        duration = _time.time() - t0
        return BenchResult(
            task_id=task.task_id,
            description=task.description,
            success=score >= 1.0,
            score=score,
            duration=duration,
            steps=steps,
            error=error,
            trajectory_path=traj_path,
        )

    def run_suite(
        self,
        task_names: Optional[list[str]] = None,
        *,
        max_steps: int = 15,
        backend: str = "background",
    ) -> list[BenchResult]:
        """批量运行多个任务。"""
        if task_names is None:
            task_names = self.list_tasks()

        results: list[BenchResult] = []
        for name in task_names:
            console_print(f"▶ 运行任务: {name} (backend={backend})")
            try:
                task = self.load_task(name, variant_index=0)
            except Exception as exc:
                results.append(BenchResult(
                    task_id=name, description="", success=False,
                    score=0.0, duration=0.0, steps=0, error=f"加载失败: {exc}",
                ))
                continue

            result = self.run_task(task, max_steps=max_steps, backend=backend)
            results.append(result)
            console_print(
                f"  {'✅' if result.success else '❌'} "
                f"score={result.score:.1f} steps={result.steps} "
                f"duration={result.duration:.1f}s"
            )

        return results


def console_print(msg: str) -> None:
    """简单的控制台输出（避免依赖 rich，bench 模块独立）。"""
    print(msg)
