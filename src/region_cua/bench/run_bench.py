"""基准测试 CLI：列出任务 / 跑单个任务 / 批量跑。

用法：
  region-cua bench --list                    # 列出所有任务
  region-cua bench --task click-button       # 跑单个任务
  region-cua bench --all                     # 跑全部任务
  region-cua bench --task click-button --variant 1  # 跑指定变体
"""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from .bench_runner import BenchRunner, BenchResult

console = Console()


def find_bench_data_dir() -> Path:
    """查找 cua-bench-basic 数据集目录。"""
    candidates = [
        Path("bench/cua-bench-basic"),
        Path(__file__).resolve().parents[4] / "bench" / "cua-bench-basic",
        Path(__file__).resolve().parents[3] / "bench" / "cua-bench-basic",
    ]
    for c in candidates:
        if c.exists():
            return c
    return candidates[0]  # 返回第一个让错误信息有意义


def bench_command(
    list_tasks: bool = typer.Option(False, "--list", help="列出所有可用任务"),
    task_name: str = typer.Option(None, "--task", help="运行指定任务"),
    variant: int = typer.Option(0, "--variant", help="任务变体索引（从0开始）"),
    all_tasks: bool = typer.Option(False, "--all", help="运行全部任务"),
    output: str = typer.Option(None, "--output", help="结果输出 JSON 路径"),
    backend: str = typer.Option("background", "--backend", help="截图后端：background（PrintWindow截窗口）或 foreground（截全屏）"),
) -> None:
    """运行 cua-bench 基准测试。"""
    data_dir = find_bench_data_dir()
    if not data_dir.exists():
        console.print(f"[red]数据集目录不存在：{data_dir}[/red]")
        console.print("[dim]请确保 bench/cua-bench-basic/ 已下载[/dim]")
        raise typer.Exit(1)

    runner = BenchRunner(data_dir)

    if list_tasks:
        tasks = runner.list_tasks()
        table = Table(title="cua-bench 基准测试任务", show_header=True, header_style="bold magenta")
        table.add_column("#", width=4)
        table.add_column("任务名")
        for i, name in enumerate(tasks):
            table.add_row(str(i), name)
        console.print(table)
        return

    if not task_name and not all_tasks:
        console.print("[yellow]请指定 --task <名称> 或 --all[/yellow]")
        raise typer.Exit(1)

    if all_tasks:
        results = runner.run_suite(backend=backend)
    else:
        task = runner.load_task(task_name, variant_index=variant)
        console.print(f"[cyan]任务：[/cyan]{task.description}")
        console.print(f"[dim]评估：{task.evaluate_js} == {task.expected_value} | 后端：{backend}[/dim]")
        result = runner.run_task(task, backend=backend)
        results = [result]

    # 打印结果表
    table = Table(title="基准测试结果", show_header=True, header_style="bold magenta")
    table.add_column("任务", width=20)
    table.add_column("分数", justify="center")
    table.add_column("步骤", justify="right")
    table.add_column("耗时", justify="right")
    table.add_column("状态")
    for r in results:
        icon = "✅" if r.success else "❌"
        table.add_row(
            r.task_id,
            f"{r.score:.1f}",
            str(r.steps),
            f"{r.duration:.1f}s",
            icon,
        )
    console.print(table)

    # 汇总
    total = len(results)
    passed = sum(1 for r in results if r.success)
    avg_score = sum(r.score for r in results) / total if total else 0
    console.print(f"\n[bold]汇总：[/bold] {passed}/{total} 通过，平均分 {avg_score:.2f}")

    if output:
        data = [
            {
                "task_id": r.task_id,
                "description": r.description,
                "success": r.success,
                "score": r.score,
                "duration": r.duration,
                "steps": r.steps,
                "error": r.error,
            }
            for r in results
        ]
        Path(output).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        console.print(f"[dim]结果已保存：{output}[/dim]")
