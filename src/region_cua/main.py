"""RegionCUA CLI 入口。

命令：
  region-cua run "任务" [--dry-run] [--model X] [--no-video]
  region-cua explore "应用名" [--no-video]
  region-cua compile "文档路径" --app "应用名"
  region-cua list-models
  region-cua info
"""

from __future__ import annotations

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
from .output.docs import generate_doc
from .output.scripts import generate_script
from .vision.ollama_client import OllamaClient

app = typer.Typer(
    name="region-cua",
    help="本地 Ollama 视觉模型驱动的桌面自动化 Agent",
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


# ----------------------------------------------------------- core run logic
def run_task(
    task: str,
    settings: Optional[Settings] = None,
    dry_run: bool = False,
    model: Optional[str] = None,
    no_video: bool = True,
    no_log: bool = False,
    allow_lock: bool = False,
    ask_user: Optional[Callable[[str], str]] = None,
) -> tuple[TaskPlan, list[StepRecord], Optional[Path]]:
    """执行一个桌面自动化任务的核心逻辑，CLI 与测试共用。

    返回 (plan, records, task_dir)。dry_run 时 task_dir 为 None。
    allow_lock=False（默认）任务期间阻止系统锁屏/睡眠。
    no_video=False（默认）会录制 MP4，no_log=False（默认）会写 operation.log，
    成功失败异常路径下都尽力落盘。
    """
    settings = settings or get_settings()
    client = OllamaClient(settings.ollama_host, settings.ollama_timeout)
    vision_model = model or settings.ollama_vision_model

    planner = TaskPlanner(client, settings.ollama_planner_model)
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
    no_video: bool = typer.Option(False, "--no-video", help="不录屏（默认录制 MP4，成功失败都保存）"),
    no_log: bool = typer.Option(False, "--no-log", help="不写操作日志（默认实时写 operation.log）"),
    allow_lock: bool = typer.Option(
        False, "--allow-lock",
        help="允许任务期间系统锁屏/睡眠（默认会阻止，避免截图失败）",
    ),
):
    """执行一个桌面自动化任务。"""
    settings = get_settings()
    vision_model = model or settings.ollama_vision_model
    console.print(f"[dim]规划模型：{settings.ollama_planner_model} | 视觉模型：{vision_model}[/dim]")

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
):
    """自由探索模式：全面摸索应用并生成说明书 + Skill。"""
    settings = get_settings()
    client = OllamaClient(settings.ollama_host, settings.ollama_timeout)
    task_dir = _new_task_dir(settings, "探索", app_name)
    console.print(f"[dim]输出目录：{task_dir}[/dim]")
    with console.status("[bold green]正在探索应用…[/bold green]"):
        explore_app(client, settings.ollama_vision_model, app_name, task_dir, record_video=not no_video)
    client.close()
    console.print("\n[bold green]探索完成。[/bold green]")
    console.print(f"  说明文档：{task_dir / '使用说明.md'}")
    console.print(f"  Skill：{task_dir / 'skill' / 'SKILL.md'}")


@app.command()
def compile(
    doc: str = typer.Argument(..., help="说明文档路径 (md/txt/html/pdf)"),
    app_name: str = typer.Option(..., "--app", help="应用名"),
):
    """Skill 编译：把已有说明文档编译为操作 Skill。"""
    settings = get_settings()
    client = OllamaClient(settings.ollama_host, settings.ollama_timeout)
    task_dir = _new_task_dir(settings, "编译", app_name)
    with console.status("[bold green]正在编译 Skill…[/bold green]"):
        skill_dir = compile_skill(client, settings.ollama_planner_model, doc, app_name, task_dir)
    client.close()
    console.print(f"\n[bold green]编译完成：[/bold green]{skill_dir / 'SKILL.md'}")


@app.command(name="list-models")
def list_models():
    """列出 Ollama 可用模型。"""
    settings = get_settings()
    client = OllamaClient(settings.ollama_host, settings.ollama_timeout)
    try:
        models = client.list_models()
    except Exception as exc:
        console.print(f"[red]获取模型失败：{exc}[/red]")
        raise typer.Exit(1)
    table = Table(title="Ollama 模型", show_header=True, header_style="bold magenta")
    table.add_column("名称")
    table.add_column("大小", justify="right")
    table.add_column("修改时间")
    for m in models:
        table.add_row(m.get("name", ""), _fmt_size(m.get("size")), m.get("modified", ""))
    console.print(table)
    loaded = client.loaded_models()
    if loaded:
        console.print("[dim]已驻留 VRAM：[/dim]" + ", ".join(m.get("name", "") for m in loaded))
    client.close()


@app.command()
def info():
    """查看当前配置。"""
    s = get_settings()
    table = Table(title="RegionCUA 配置", show_header=False)
    table.add_column("项", style="bold cyan")
    table.add_column("值")
    table.add_row("ollama_host", s.ollama_host)
    table.add_row("ollama_planner_model", s.ollama_planner_model)
    table.add_row("ollama_vision_model", s.ollama_vision_model)
    table.add_row("output_dir", s.output_dir)
    table.add_row("max_consecutive_failures", str(s.max_consecutive_failures))
    table.add_row("ollama_timeout", f"{s.ollama_timeout}s")
    table.add_row("video_fps", str(s.video_fps))
    console.print(table)


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
