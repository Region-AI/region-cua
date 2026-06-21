"""配置测试：默认值与环境变量覆盖。"""

from __future__ import annotations

from region_cua.config import Settings


def test_defaults(monkeypatch):
    for k in ("OLLAMA_HOST", "OLLAMA_PLANNER_MODEL", "OLLAMA_VISION_MODEL",
              "OUTPUT_DIR", "MAX_CONSECUTIVE_FAILURES", "OLLAMA_TIMEOUT", "VIDEO_FPS"):
        monkeypatch.delenv(k, raising=False)
    s = Settings(_env_file=None)
    assert s.ollama_host == "http://localhost:11434"
    assert s.ollama_planner_model == "qwen3.6:latest"
    assert s.ollama_vision_model == "qwen3.6:latest"
    assert s.max_consecutive_failures == 3
    assert s.ollama_timeout == 600
    assert s.video_fps == 5


def test_env_override(monkeypatch):
    monkeypatch.setenv("OLLAMA_VISION_MODEL", "my-vision")
    monkeypatch.setenv("OLLAMA_TIMEOUT", "999")
    s = Settings(_env_file=None)
    assert s.ollama_vision_model == "my-vision"
    assert s.ollama_timeout == 999


def test_output_path_creates_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "out"))
    s = Settings(_env_file=None)
    assert s.output_path.exists()
    assert s.output_path == tmp_path / "out"
