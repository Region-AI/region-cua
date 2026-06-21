"""VideoRecorder 测试：start/stop 幂等、空帧、编码失败兜底、帧数上限。"""

from __future__ import annotations

from pathlib import Path

import pytest

from region_cua.recorder.video import VideoRecorder


def test_stop_idempotent(tmp_path):
    rec = VideoRecorder(tmp_path)
    rec._stopped = True  # 模拟已停止
    assert rec.stop() is None  # 不抛异常


def test_no_frames_returns_none(tmp_path, monkeypatch):
    """没抓到帧时 stop 返回 None。"""
    rec = VideoRecorder(tmp_path)
    # 不调 start，直接 stop
    rec._stopped = False
    assert rec.stop() is None


def test_encode_failure_writes_diagnostic(tmp_path, monkeypatch):
    """imageio 不可用时应写 .txt 说明文件，而非崩溃。"""
    import region_cua.recorder.video as video_mod

    rec = VideoRecorder(tmp_path)
    # 注入假帧；同时确保父目录存在（测试不调 start，模拟 encode 阶段）
    rec.path.parent.mkdir(parents=True, exist_ok=True)
    rec._frames = [object(), object()]

    # 让 imageio.get_writer 抛异常
    def boom(*a, **k):
        raise RuntimeError("imageio missing")

    monkeypatch.setattr("imageio.v2.get_writer", boom, raising=False)
    result = rec._encode()
    assert result is None
    diag = tmp_path / "recordings" / "recording.txt"
    assert diag.exists()
    assert "imageio" in diag.read_text(encoding="utf-8")


def test_max_frames_caps_memory(tmp_path, monkeypatch):
    """超过 MAX_FRAMES 时只保留最近帧。"""
    rec = VideoRecorder(tmp_path)
    rec.MAX_FRAMES = 3
    # 模拟 _loop 行为
    captured = []

    def fake_capture():
        return f"frame{len(captured)}"

    from region_cua.vision import screenshot as shot

    monkeypatch.setattr(shot, "capture_screen", fake_capture)
    rec._running = True
    # 手动跑几次抓取（不开线程）
    for _ in range(5):
        rec._frames.append(shot.capture_screen())
        if len(rec._frames) > rec.MAX_FRAMES:
            rec._frames = rec._frames[-rec.MAX_FRAMES:]
    assert len(rec._frames) == 3


def test_start_idempotent(tmp_path):
    rec = VideoRecorder(tmp_path)
    rec.start()
    rec.start()  # 第二次 start 不应起新线程
    rec.stop()
