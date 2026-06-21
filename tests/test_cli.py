"""CLI 测试：info / help（不需 Ollama）。"""

from __future__ import annotations

from typer.testing import CliRunner

from region_cua.main import app

runner = CliRunner()


def test_info_command():
    result = runner.invoke(app, ["info"])
    assert result.exit_code == 0
    assert "ollama_planner_model" in result.output
    assert "ollama_vision_model" in result.output
    assert "RegionCUA 配置" in result.output


def test_help_command():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "run" in result.output
    assert "explore" in result.output
    assert "compile" in result.output
    assert "list-models" in result.output


def test_no_args_shows_help():
    result = runner.invoke(app, [])
    assert result.exit_code != 0  # no_args_is_help
