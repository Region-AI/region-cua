"""RegionCUA CLI 入口。

命令：
  region-cua run "任务" [--dry-run] [--model X] [--provider ollama|vllm] [--no-video]
  region-cua explore "应用名" [--no-video]
  region-cua compile "文档路径" --app "应用名"
  region-cua list-models
  region-cua info
"""

from __future__ import annotations

# 必须在任何其他 import 之前：清理 Hermes 环境路径污染
from ._env_fix import *  # noqa: F401,F403

import re
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import typer
from rich.console import Console
from rich.table import Table

from .agent.executor import TaskExecutor
from .agent.models import StepRecord, TaskPlan
from .agent.monitor import Monitor
from .agent.planner import TaskPlanner
from .config import Settings, get_settings
from .explore import compile_skill, explore_app
from .learn import learn_from_video, record_screen, LearnResult
from .output.docs import generate_doc
from .output.scripts import generate_script
from .vision import create_vision_client

app = typer.Typer(
    name="region-cua",
    help="本地视觉模型驱动的桌面自动化 Agent（支持 Ollama / vLLM）",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()


def _slug(text: str, maxlen: int = 30) -> str:
    s = re.sub(r"[^\w\u4e00-\u9fa5]+", "_", text).strip("_")
    return (s or "task")[:maxlen]


def _new_task_dir(settings: Settings, prefix: str, name: str) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    label = f"{ts}_{prefix}_{_slug(name)}" if prefix else f"{ts}_{_slug(name)}"
    d = settings.output_path / label
    d.mkdir(parents=True, exist_ok=True)
    return d


def _print_plan(plan: TaskPlan) -> None:
    console.print(f"\n[bold cyan]任务：[/bold cyan]{plan.task}")
    console.print(f"[bold]规划步骤（{len(plan.steps)} 步）[/bold]")
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("#", width=4)
    table.add_column("动作", width=12)
    table.add_column("目标", width=30)
    table.add_column("说明")
    for s in plan.steps:
        table.add_row(str(s.order), s.action, (s.target or "")[:30], s.description)
    console.print(table)


def _resolve_settings(provider: Optional[str]) -> Settings:
    s = get_settings()
    if provider:
        s.provider = provider
    return s


# ----------------------------------------------------------- core run logic
def run_task(
    task: str,
    settings: Optional[Settings] = None,
    dry_run: bool = False,
    model: Optional[str] = None,
    no_video: bool = True,
    no_log: bool = False,
    allow_lock: bool = False,
    backend: str = "foreground",
    ask_user: Optional[Callable[[str], str]] = None,
) -> tuple[TaskPlan, list[StepRecord], Optional[Path]]:
    """执行一个桌面自动化任务的核心逻辑，CLI 与测试共用。

    返回 (plan, records, task_dir)。dry_run 时 task_dir 为 None。
    allow_lock=False（默认）任务期间阻止系统锁屏/睡眠。
    no_video=False（默认）会录制 MP4，no_log=False（默认）会写 operation.log，
    成功失败异常路径下都尽力落盘。
    backend: "foreground"（前台，抢光标）或 "background"（后台，不抢光标）。
    """
    settings = settings or get_settings()
    client = create_vision_client(settings)
    vision_model = model or (
        settings.ollama_vision_model if settings.provider == "ollama" else settings.vllm_model
    )
    planner_model = settings.ollama_planner_model if settings.provider == "ollama" else settings.vllm_model

    planner = TaskPlanner(client, planner_model)
    plan = planner.plan(task)

    if dry_run:
        client.close()
        return plan, [], None

    task_dir = _new_task_dir(settings, "", task)
    monitor = Monitor(settings.max_consecutive_failures, ask_user=ask_user)
    executor = TaskExecutor(
        client, vision_model, task_dir, monitor,
        record_video=not no_video,
        record_log=not no_log,
        verify=True,
        video_fps=settings.video_fps,
        allow_lock=allow_lock,
        backend=backend,
    )
    try:
        records = executor.execute(plan)
    except Exception:
        records = executor.step_records

    generate_doc(plan, records, task_dir)
    generate_script(plan, records, task_dir)
    client.close()
    return plan, records, task_dir


@app.command()
def run(
    task: str = typer.Argument(..., help="自然语言任务描述"),
    dry_run: bool = typer.Option(False, "--dry-run", help="仅生成计划，不执行"),
    model: str = typer.Option(None, "--model", help="覆盖视觉模型"),
    provider: str = typer.Option(
        None, "--provider",
        help="后端提供者：ollama（默认）或 vllm",
    ),
    no_video: bool = typer.Option(False, "--no-video", help="不录屏（默认录制 MP4，成功失败都保存）"),
    no_log: bool = typer.Option(False, "--no-log", help="不写操作日志（默认实时写 operation.log）"),
    allow_lock: bool = typer.Option(
        False, "--allow-lock",
        help="允许任务期间系统锁屏/睡眠（默认会阻止，避免截图失败）",
    ),
    backend: str = typer.Option(
        "foreground", "--backend",
        help="操作后端：foreground（前台，抢光标）或 background（后台，不抢光标）",
    ),
):
    """执行一个桌面自动化任务。"""
    settings = _resolve_settings(provider)
    vision_model = model or (
        settings.ollama_vision_model if settings.provider == "ollama" else settings.vllm_model
    )
    console.print(f"[dim]提供者：{settings.provider} | 视觉模型：{vision_model} | 后端：{backend}[/dim]")

    with console.status("[bold green]正在规划任务…[/bold green]"):
        plan, _records, _ = run_task(task, settings, dry_run=True, model=model)
    _print_plan(plan)

    if dry_run:
        console.print("\n[yellow]--dry-run 模式：仅生成计划，未执行。[/yellow]")
        return

    with console.status("[bold green]正在执行任务…[/bold green]"):
        plan, records, task_dir = run_task(
            task, settings, dry_run=False, model=model,
            no_video=no_video, no_log=no_log, allow_lock=allow_lock,
            backend=backend,
        )

    ok = sum(1 for r in records if r.success)
    console.print("\n[bold green]任务完成。[/bold green]")
    console.print(f"  步骤：{ok}/{len(records)} 成功")
    console.print(f"  文档：{task_dir / '任务说明.md'}")
    console.print(f"  脚本：{task_dir / 'scripts' / 'replay.py'}")
    if not no_log:
        console.print(f"  日志：{task_dir / 'operation.log'}")
    if not no_video:
        console.print(f"  录屏：{task_dir / 'recordings' / 'recording.mp4'}")


@app.command()
def explore(
    app_name: str = typer.Argument(..., help="要探索的应用名"),
    no_video: bool = typer.Option(False, "--no-video", help="不录屏"),
    provider: str = typer.Option(
        None, "--provider",
        help="后端提供者：ollama（默认）或 vllm",
    ),
):
    """自由探索模式：全面摸索应用并生成说明书 + Skill。"""
    settings = _resolve_settings(provider)
    client = create_vision_client(settings)
    vision_model = (
        settings.ollama_vision_model if settings.provider == "ollama" else settings.vllm_model
    )
    task_dir = _new_task_dir(settings, "探索", app_name)
    console.print(f"[dim]输出目录：{task_dir}[/dim]")
    with console.status("[bold green]正在探索应用…[/bold green]"):
        explore_app(client, vision_model, app_name, task_dir, record_video=not no_video)
    client.close()
    console.print("\n[bold green]探索完成。[/bold green]")
    console.print(f"  说明文档：{task_dir / '使用说明.md'}")
    console.print(f"  Skill：{task_dir / 'skill' / 'SKILL.md'}")


@app.command()
def compile(
    doc: str = typer.Argument(..., help="说明文档路径 (md/txt/html/pdf)"),
    app_name: str = typer.Option(..., "--app", help="应用名"),
    provider: str = typer.Option(
        None, "--provider",
        help="后端提供者：ollama（默认）或 vllm",
    ),
):
    """Skill 编译：把已有说明文档编译为操作 Skill。"""
    settings = _resolve_settings(provider)
    client = create_vision_client(settings)
    planner_model = (
        settings.ollama_planner_model if settings.provider == "ollama" else settings.vllm_model
    )
    task_dir = _new_task_dir(settings, "编译", app_name)
    with console.status("[bold green]正在编译 Skill…[/bold green]"):
        skill_dir = compile_skill(client, planner_model, doc, app_name, task_dir)
    client.close()
    console.print(f"\n[bold green]编译完成：[/bold green]{skill_dir / 'SKILL.md'}")


@app.command()
def learn(
    video: str = typer.Argument(
        None, help="录屏视频文件路径（不提供则用 --record 实时录屏）",
    ),
    record: bool = typer.Option(
        False, "--record",
        help="实时录屏模式：按 Ctrl+C 结束录屏后自动分析",
    ),
    replay_doc: bool = typer.Option(
        False, "--replay-doc",
        help="同时生成操作回放文档",
    ),
    verify: bool = typer.Option(
        True, "--verify/--no-verify",
        help="生成 Skill 后自动执行验证任务",
    ),
    provider: str = typer.Option(
        None, "--provider",
        help="后端提供者：ollama（默认）或 vllm",
    ),
):
    """学习模式：从录屏视频学习操作并生成语义化 Skill。"""
    settings = _resolve_settings(provider)
    client = create_vision_client(settings)
    vision_model = (
        settings.ollama_vision_model if settings.provider == "ollama" else settings.vllm_model
    )

    # 确定视频来源
    video_path: Optional[Path] = None
    if record:
        task_dir = _new_task_dir(settings, "学习", "实时录屏")
        console.print(f"[dim]输出目录：{task_dir}[/dim]")
        console.print("[bold yellow]录屏中…按 Ctrl+C 结束录屏[/bold yellow]")
        video_file = task_dir / "recordings" / "recording.mp4"
        try:
            video_path = record_screen(video_file, fps=settings.video_fps)
        except RuntimeError as exc:
            console.print(f"[red]录屏失败：{exc}[/red]")
            client.close()
            raise typer.Exit(1)
        console.print(f"[green]录屏已保存：{video_path}[/green]")
    elif video:
        video_path = Path(video)
        if not video_path.exists():
            console.print(f"[red]视频文件不存在：{video_path}[/red]")
            client.close()
            raise typer.Exit(1)
        label = video_path.stem
        task_dir = _new_task_dir(settings, "学习", label)
        console.print(f"[dim]输出目录：{task_dir}[/dim]")
    else:
        console.print("[red]请提供视频文件路径或使用 --record 实时录屏[/red]")
        client.close()
        raise typer.Exit(1)

    # 学习：分析视频 → 标注 → 识别变量 → 生成 Skill → 验证
    with console.status("[bold green]正在分析视频并生成 Skill…[/bold green]"):
        result: LearnResult = learn_from_video(
            client, vision_model, video_path, task_dir,
            do_verify=verify,
        )

    console.print(f"\n[bold green]学习完成。[/bold green]")
    console.print(f"  Skill：{result.skill_path}")
    console.print(f"  步骤数：{len(result.actions)}")
    if result.variables:
        console.print(f"  变量：{', '.join(v.get('name', '') for v in result.variables)}")
    if result.apps_detected:
        console.print(f"  涉及应用：{', '.join(result.apps_detected)}")
    if result.verify_result:
        console.print(f"  验证：{result.verify_result.splitlines()[0] if result.verify_result else '跳过'}")

    client.close()


@app.command(name="list-models")
def list_models(
    provider: str = typer.Option(
        None, "--provider",
        help="后端提供者：ollama（默认）或 vllm",
    ),
):
    """列出后端可用模型。"""
    settings = _resolve_settings(provider)
    client = create_vision_client(settings)
    try:
        models = client.list_models()
    except Exception as exc:
        console.print(f"[red]获取模型列表失败：{exc}[/red]")
        raise typer.Exit(1)

    if hasattr(client, "loaded_models") and callable(client.loaded_models):
        label = f"{settings.provider} 模型"
        table = Table(title=label, show_header=True, header_style="bold magenta")
        table.add_column("名称")
        table.add_column("大小", justify="right")
        table.add_column("修改时间")
        for m in models:
            table.add_row(m.get("name", ""), _fmt_size(m.get("size")), m.get("modified", ""))
        console.print(table)
        loaded = client.loaded_models()
        if loaded:
            console.print("[dim]已驻留 VRAM：[/dim]" + ", ".join(m.get("name", "") for m in loaded))
    else:
        # vLLM 的 /v1/models 返回格式不同
        label = f"{settings.provider} 模型"
        table = Table(title=label, show_header=True, header_style="bold magenta")
        table.add_column("ID")
        table.add_column("对象")
        for m in models:
            table.add_row(m.get("id", ""), m.get("object", ""))
        console.print(table)
    client.close()


@app.command()
def info():
    """查看当前配置。"""
    s = get_settings()
    table = Table(title="RegionCUA 配置", show_header=False)
    table.add_column("项", style="bold cyan")
    table.add_column("值")
    table.add_row("provider", s.provider)
    table.add_row("ollama_host", s.ollama_host)
    table.add_row("ollama_planner_model", s.ollama_planner_model)
    table.add_row("ollama_vision_model", s.ollama_vision_model)
    table.add_row("ollama_timeout", f"{s.ollama_timeout}s")
    table.add_row("vllm_host", s.vllm_host)
    table.add_row("vllm_model", s.vllm_model)
    table.add_row("output_dir", s.output_dir)
    table.add_row("max_consecutive_failures", str(s.max_consecutive_failures))
    table.add_row("video_fps", str(s.video_fps))
    console.print(table)


@app.command()
def mcp(
    transport: str = typer.Option("stdio", "--transport", help="传输方式: stdio / sse"),
):
    """启动 MCP 服务器，让其他 Agent（Claude Code / Hermes / OpenClaw）通过 MCP 协议调用桌面自动化。"""
    from .mcp_server import main as mcp_main

    console.print(f"[dim]启动 RegionCUA MCP 服务器（transport={transport}）…[/dim]")
    mcp_main(transport=transport)


@app.command()
def bench(
    list_tasks: bool = typer.Option(False, "--list", help="列出所有可用基准测试任务"),
    task_name: str = typer.Option(None, "--task", help="运行指定任务"),
    variant: int = typer.Option(0, "--variant", help="任务变体索引（从0开始）"),
    all_tasks: bool = typer.Option(False, "--all", help="运行全部任务"),
    output: str = typer.Option(None, "--output", help="结果输出 JSON 路径"),
    backend: str = typer.Option("background", "--backend", help="截图后端：background（PrintWindow截窗口）或 foreground（截全屏）"),
    cua_backend: str = typer.Option("", "--cua-backend", help="CUA 后端：trycua / qwen-ui（留空走默认路径）"),
):
    """运行 cua-bench 基准测试，评估 region-cua 的桌面操作能力。"""
    from .bench.run_bench import bench_command

    bench_command(
        list_tasks=list_tasks,
        task_name=task_name,
        variant=variant,
        all_tasks=all_tasks,
        output=output,
        backend=backend,
        cua_backend=cua_backend,
    )


def _fmt_size(n) -> str:
    try:
        n = float(n)
    except (TypeError, ValueError):
        return ""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}PB"


if __name__ == "__main__":
    app()
