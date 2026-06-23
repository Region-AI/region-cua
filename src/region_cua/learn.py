"""学习模式：从录屏视频学习操作并生成语义化 Skill。

核心流程：
  1. record_screen()  — CLI 开启录屏，Ctrl+C 停止
  2. analyze_video()  — 逐帧读取视频，帧间差异检测操作点
  3. identify_variables() — 视觉模型识别可参数化的变量数据
  4. generate_skill()  — 生成不依赖分辨率/窗口/版本的语义 Skill
  5. verify_skill()    — 用生成的 Skill 执行任务验证正确性

生成的 Skill 使用语义元素描述（"点击文件菜单"而非坐标），
不依赖桌面分辨率、窗口位置/大小、应用版本。
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .vision.protocol import VisionClient


# ================================================================ data models
@dataclass
class DetectedAction:
    """从视频中检测到的一次操作。"""

    frame_index: int
    timestamp: float
    action_type: str  # click / type / hotkey / scroll / app_switch
    screenshot_path: str = ""
    description: str = ""  # 语义描述，后续由视觉模型填充
    raw_value: str = ""  # 检测到的原始值（输入文本等）
    is_variable: bool = False  # 是否为可参数化变量
    variable_name: str = ""  # 变量名，如 {{filename}}


@dataclass
class LearnResult:
    """学习模式的完整产出。"""

    actions: list[DetectedAction] = field(default_factory=list)
    apps_detected: list[str] = field(default_factory=list)
    variables: list[dict[str, str]] = field(default_factory=list)
    skill_path: str = ""
    replay_path: str = ""
    verify_result: str = ""


# ================================================================ recording
def record_screen(output_path: Path, fps: int = 5) -> Path:
    """开启实时录屏，按 Ctrl+C 停止后返回视频路径。

    使用 VideoRecorder 后台抓帧，主线程等待用户中断。
    """
    from .recorder.video import VideoRecorder

    output_path.parent.mkdir(parents=True, exist_ok=True)
    recorder = VideoRecorder(output_path.parent, fps=fps)
    # 覆盖默认路径
    recorder.path = output_path
    recorder.start()
    print(f"  录屏中... 按 Ctrl+C 停止（输出: {output_path}）")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n  停止录屏，正在编码...")
    video_path = recorder.stop()
    if video_path is None:
        raise RuntimeError("录屏失败：未捕获到任何帧")
    return Path(video_path)


# ================================================================ video reading
def _read_video_frames(video_path: Path, sample_fps: int = 2) -> list[tuple[int, float, Any]]:
    """读取视频帧，返回 [(frame_index, timestamp, PIL.Image), ...]。

    sample_fps 控制采样率：分析时不需要逐帧，2fps 足够检测操作。
    """
    import imageio.v2 as imageio
    from PIL import Image

    reader = imageio.get_reader(str(video_path))
    meta = reader.get_meta_data()
    video_fps = meta.get("fps", 30)
    step = max(1, int(video_fps / sample_fps))

    frames: list[tuple[int, float, Any]] = []
    idx = 0
    try:
        for frame_array in reader:
            if idx % step == 0:
                ts = idx / video_fps
                img = Image.fromarray(frame_array)
                frames.append((idx, ts, img))
            idx += 1
    except Exception:
        pass
    finally:
        reader.close()
    return frames


# ================================================================ frame diff
def _frame_diff(img_a, img_b) -> float:
    """计算两帧之间的差异比例 (0.0 ~ 1.0)。"""
    import numpy as np

    a = np.array(img_a.resize((160, 90)))
    b = np.array(img_b.resize((160, 90)))
    diff = np.abs(a.astype(int) - b.astype(int))
    changed_ratio = float((diff.sum(axis=2) > 30).mean())
    return changed_ratio


def _detect_action_type(
    prev_img, curr_img, diff_ratio: float
) -> Optional[str]:
    """根据帧间差异粗略判断操作类型。

    - diff < 0.01: 无变化
    - 0.01 ~ 0.15: 可能是文本输入或小范围 UI 变化
    - 0.15 ~ 0.50: 可能是点击（区域跳转/弹窗）
    - > 0.50: 可能是应用切换或页面跳转
    """
    if diff_ratio < 0.01:
        return None
    if diff_ratio > 0.50:
        return "app_switch"
    if diff_ratio > 0.15:
        return "click"
    return "type"


# ================================================================ analysis
def analyze_video(
    video_path: Path,
    frames_dir: Path,
    sample_fps: int = 2,
) -> list[DetectedAction]:
    """分析视频，检测操作点并保存关键帧截图。

    返回检测到的操作列表（未填充语义描述，需后续调用视觉模型）。
    """
    frames_dir.mkdir(parents=True, exist_ok=True)
    frames = _read_video_frames(video_path, sample_fps=sample_fps)
    if len(frames) < 2:
        return []

    actions: list[DetectedAction] = []
    prev_idx, prev_ts, prev_img = frames[0]

    for i in range(1, len(frames)):
        curr_idx, curr_ts, curr_img = frames[i]
        diff = _frame_diff(prev_img, curr_img)
        action_type = _detect_action_type(prev_img, curr_img, diff)
        if action_type is None:
            continue

        # 保存关键帧
        shot_name = f"frame_{curr_idx:06d}.png"
        shot_path = frames_dir / shot_name
        curr_img.save(str(shot_path), format="PNG")

        actions.append(
            DetectedAction(
                frame_index=curr_idx,
                timestamp=curr_ts,
                action_type=action_type,
                screenshot_path=str(shot_path),
            )
        )
        prev_idx, prev_ts, prev_img = curr_idx, curr_ts, curr_img

    return actions


# ================================================================ vision annotation
def annotate_actions(
    client: VisionClient,
    model: str,
    actions: list[DetectedAction],
    apps_hint: list[str] | None = None,
) -> tuple[list[DetectedAction], list[str]]:
    """用视觉模型为每个操作填充语义描述，并识别涉及的应用。

    返回 (更新后的 actions, 检测到的应用列表)。
    """
    apps_set: set[str] = set()
    apps_hint = apps_hint or []

    for i, action in enumerate(actions):
        prompt = _build_annotation_prompt(action, apps_hint, i, len(actions))
        try:
            text = client.chat(
                model,
                [{"role": "user", "content": prompt}],
                images=[action.screenshot_path],
            )
            parsed = _parse_annotation(text)
            action.description = parsed.get("description", "")
            action.action_type = parsed.get("action_type", action.action_type)
            detected_apps = parsed.get("apps", [])
            for app in detected_apps:
                apps_set.add(app)
            if parsed.get("input_text"):
                action.raw_value = parsed["input_text"]
        except Exception as exc:
            action.description = f"(视觉分析失败: {exc})"

    return actions, sorted(apps_set)


def _build_annotation_prompt(
    action: DetectedAction, apps_hint: list[str], index: int, total: int
) -> str:
    apps_str = "、".join(apps_hint) if apps_hint else "未知"
    return (
        f"这是录屏第 {index + 1}/{total} 步操作的关键帧截图（操作类型初判: {action.action_type}）。\n"
        f"已知可能涉及的应用: {apps_str}。\n"
        "请分析截图，返回严格 JSON：\n"
        "{\n"
        '  "description": "用语义化语言描述这一步操作，如「点击文件菜单」「在搜索框输入关键词」",\n'
        '  "action_type": "click|type|hotkey|scroll|app_switch",\n'
        '  "apps": ["当前可见的应用名列表"],\n'
        '  "input_text": "如果检测到文本输入，填写输入的内容；否则为空字符串"\n'
        "}\n只输出 JSON。"
    )


def _parse_annotation(text: str) -> dict[str, Any]:
    if not text:
        return {}
    m = re.search(r"\{[^{}]*\}", text, re.DOTALL)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}


# ================================================================ variable detection
def identify_variables(actions: list[DetectedAction]) -> list[dict[str, str]]:
    """从操作序列中识别可参数化的变量数据。

    规则：
    - type 操作中输入的文本 → 候选变量
    - 文件名、路径、URL、数字、日期等模式 → 自动标记为变量
    - 变量名根据上下文语义生成
    """
    variables: list[dict[str, str]] = []
    var_patterns = {
        "filename": re.compile(r"^[\w\-\.]+\.(txt|docx?|xlsx?|pdf|csv|md|json|xml|html?)$", re.I),
        "url": re.compile(r"^https?://", re.I),
        "number": re.compile(r"^\d+(\.\d+)?$"),
        "date": re.compile(r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}$"),
        "email": re.compile(r"^[\w.]+@[\w.]+\.\w+$"),
    }

    for action in actions:
        if action.action_type != "type" or not action.raw_value:
            continue
        value = action.raw_value.strip()
        if not value:
            continue

        var_type = "text"
        for vtype, pattern in var_patterns.items():
            if pattern.match(value):
                var_type = vtype
                break

        var_name = _generate_var_name(action.description, var_type, len(variables))
        action.is_variable = True
        action.variable_name = var_name
        variables.append(
            {
                "name": var_name,
                "type": var_type,
                "default_value": value,
                "description": action.description,
            }
        )

    return variables


def _generate_var_name(description: str, var_type: str, index: int) -> str:
    """根据操作描述和变量类型生成语义化变量名。"""
    type_defaults = {
        "filename": "filename",
        "url": "url",
        "number": "value",
        "date": "date",
        "email": "email",
        "text": "text",
    }
    base = type_defaults.get(var_type, "input")
    # 尝试从描述中提取关键词
    if description:
        keywords = re.findall(r"[\u4e00-\u9fa5a-zA-Z_]+", description)
        if keywords:
            # 取第一个关键词的拼音首字母或英文作为变量名
            kw = keywords[0]
            if kw.isascii():
                base = re.sub(r"[^a-zA-Z_]", "", kw).lower() or base
    return f"{{{base}_{index + 1}}}"


# ================================================================ skill generation
def generate_skill(
    actions: list[DetectedAction],
    apps: list[str],
    variables: list[dict[str, str]],
    skill_dir: Path,
    task_summary: str = "",
) -> Path:
    """生成语义化 Skill 文件（SKILL.md + steps.json）。

    Skill 使用语义元素描述，不包含坐标、分辨率等环境相关信息。
    """
    skill_dir.mkdir(parents=True, exist_ok=True)

    # steps.json — 结构化操作步骤
    steps_data = []
    for i, action in enumerate(actions):
        step = {
            "order": i + 1,
            "action": action.action_type,
            "description": action.description,
            "is_variable": action.is_variable,
        }
        if action.is_variable:
            step["variable_name"] = action.variable_name
        else:
            step["value"] = action.raw_value
        steps_data.append(step)

    steps_json = {
        "version": "1.0",
        "apps": apps,
        "variables": variables,
        "steps": steps_data,
    }
    (skill_dir / "steps.json").write_text(
        json.dumps(steps_json, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # SKILL.md — 人类可读的 Skill 定义
    apps_list = "、".join(apps) if apps else "未知应用"
    var_section = ""
    if variables:
        var_lines = ["| 变量名 | 类型 | 默认值 | 说明 |", "|-------|------|--------|------|"]
        for v in variables:
            var_lines.append(f"| {v['name']} | {v['type']} | {v['default_value']} | {v['description']} |")
        var_section = "\n## 变量\n\n" + "\n".join(var_lines) + "\n"
    else:
        var_section = "\n## 变量\n\n本 Skill 无可参数化变量。\n"

    steps_lines = ["## 操作步骤", ""]
    for i, action in enumerate(actions):
        prefix = f"{i + 1}. "
        if action.is_variable:
            steps_lines.append(f"{prefix}[{action.action_type}] {action.description} → 输入变量 {action.variable_name}")
        else:
            val = f"（输入: {action.raw_value}）" if action.raw_value else ""
            steps_lines.append(f"{prefix}[{action.action_type}] {action.description}{val}")
    steps_lines.append("")

    content = f"""---
name: learned-skill-{int(time.time())}
description: 通过学习模式从录屏生成的操作 Skill（涉及: {apps_list}）
metadata:
  emoji: 🎓
  category: automation
  source: region-cua learn
  apps: {json.dumps(apps, ensure_ascii=False)}
  variable_count: {len(variables)}
---

# 操作 Skill（学习模式生成）

> 由 RegionCUA 学习模式自动生成。使用语义元素描述，不依赖桌面分辨率、窗口位置/大小和应用版本。

{var_section}

{chr(10).join(steps_lines)}

## 注意事项

- 执行时通过视觉模型定位界面元素，自动适配不同分辨率和窗口大小
- 变量值在执行时可通过 CLI 参数或对话动态指定
- 如应用版本变化导致 UI 差异，视觉模型会尝试自适应定位
"""
    (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")
    return skill_dir


# ================================================================ replay doc
def generate_replay_doc(
    actions: list[DetectedAction],
    apps: list[str],
    variables: list[dict[str, str]],
    replay_path: Path,
    frames_dir: Path,
) -> Path:
    """生成操作回放文档（含关键帧截图）。"""
    lines = [
        "# 操作回放文档",
        "",
        f"**涉及应用:** {', '.join(apps) if apps else '未知'}",
        "",
    ]
    if variables:
        lines.append("## 变量")
        lines.append("")
        for v in variables:
            lines.append(f"- **{v['name']}** ({v['type']}): {v['description']} (默认: {v['default_value']})")
        lines.append("")

    lines += ["## 操作步骤（含关键帧）", ""]
    for i, action in enumerate(actions):
        lines.append(f"### 步骤 {i + 1}: [{action.action_type}] {action.description}")
        lines.append(f"- 时间戳: {action.timestamp:.1f}s")
        if action.is_variable:
            lines.append(f"- 变量: {action.variable_name} (默认值: {action.raw_value})")
        elif action.raw_value:
            lines.append(f"- 输入内容: {action.raw_value}")
        if action.screenshot_path:
            rel = Path(action.screenshot_path).name
            lines.append(f"- 截图: frames/{rel}")
        lines.append("")

    replay_path.write_text("\n".join(lines), encoding="utf-8")
    return replay_path


# ================================================================ verification
def verify_skill(
    client: VisionClient,
    model: str,
    skill_dir: Path,
    variables: list[dict[str, str]],
    task_dir: Path,
) -> str:
    """通过生成的 Skill 执行任务来验证 Skill 是否正确。

    使用变量的默认值执行，返回验证结果描述。
    """
    from .agent.executor import TaskExecutor
    from .agent.models import Step, TaskPlan
    from .agent.monitor import Monitor

    steps_json_path = skill_dir / "steps.json"
    if not steps_json_path.exists():
        return "验证失败: steps.json 不存在"

    data = json.loads(steps_json_path.read_text(encoding="utf-8"))
    raw_steps = data.get("steps", [])

    # 将 Skill 步骤转换为 TaskPlan
    plan_steps: list[Step] = []
    for i, s in enumerate(raw_steps):
        action = s.get("action", "screenshot")
        desc = s.get("description", "")
        target = ""
        value = ""
        if s.get("is_variable"):
            # 用默认值执行
            value = s.get("variable_name", "")
            target = value  # 变量占位符
        else:
            value = s.get("value", "")
        requires_vision = action in ("click", "app_switch")
        plan_steps.append(
            Step(
                order=i + 1,
                action=action,
                target=target,
                value=value,
                description=desc,
                requires_vision=requires_vision,
            )
        )

    if not plan_steps:
        return "验证失败: Skill 中无有效步骤"

    plan = TaskPlan(task=f"验证学习模式生成的 Skill（{data.get('apps', [])}）", steps=plan_steps)

    # 执行验证
    verify_dir = task_dir / "verify"
    verify_dir.mkdir(parents=True, exist_ok=True)
    monitor = Monitor(max_failures=3)
    executor = TaskExecutor(
        client, model, verify_dir, monitor,
        record_video=False,
        record_log=True,
        verify=True,
    )
    try:
        records = executor.execute(plan)
    except Exception as exc:
        return f"验证执行异常: {exc}"

    ok = sum(1 for r in records if r.success)
    total = len(records)
    result_lines = [
        f"验证完成: {ok}/{total} 步成功",
        "",
    ]
    for r in records:
        status = "✓" if r.success else "✗"
        result_lines.append(f"  {status} 步骤 {r.order}: {r.description}")
        if r.error:
            result_lines.append(f"      错误: {r.error}")

    return "\n".join(result_lines)


# ================================================================ orchestrator
def learn_from_video(
    client: VisionClient,
    model: str,
    video_path: Path,
    task_dir: Path,
    apps_hint: list[str] | None = None,
    do_verify: bool = True,
) -> LearnResult:
    """完整学习流程：分析视频 → 标注操作 → 识别变量 → 生成 Skill → 验证。

    Args:
        client: 视觉模型客户端
        model: 模型名
        video_path: 录屏视频路径
        task_dir: 输出目录
        apps_hint: 用户指定的应用名提示
        do_verify: 是否执行验证
    """
    task_dir = Path(task_dir)
    frames_dir = task_dir / "frames"
    skill_dir = task_dir / "skill"

    # 1. 分析视频
    print("  [1/5] 分析视频帧...")
    actions = analyze_video(video_path, frames_dir)
    if not actions:
        return LearnResult(actions=[])
    print(f"        检测到 {len(actions)} 个操作点")

    # 2. 视觉标注
    print("  [2/5] 视觉模型标注操作语义...")
    actions, apps = annotate_actions(client, model, actions, apps_hint)
    print(f"        识别到应用: {', '.join(apps) if apps else '未知'}")

    # 3. 识别变量
    print("  [3/5] 识别可参数化变量...")
    variables = identify_variables(actions)
    print(f"        发现 {len(variables)} 个变量")

    # 4. 生成 Skill
    print("  [4/5] 生成语义化 Skill...")
    generate_skill(actions, apps, variables, skill_dir)
    replay_path = task_dir / "replay.md"
    generate_replay_doc(actions, apps, variables, replay_path, frames_dir)
    print(f"        Skill: {skill_dir / 'SKILL.md'}")

    # 5. 验证
    verify_result = ""
    if do_verify:
        print("  [5/5] 验证 Skill（使用默认变量值执行）...")
        verify_result = verify_skill(client, model, skill_dir, variables, task_dir)
        print(f"        {verify_result.splitlines()[0] if verify_result else '验证跳过'}")

    return LearnResult(
        actions=actions,
        apps_detected=apps,
        variables=variables,
        skill_path=str(skill_dir / "SKILL.md"),
        replay_path=str(replay_path),
        verify_result=verify_result,
    )
