"""后台线程录屏：任务运行期间按帧率抓屏，结束后编码为 MP4。

- 全程异常隔离：抓帧/编码失败不影响任务本身
- 帧缓存为 PIL.Image，编码时转 numpy 数组交给 imageio
- stop() 在任务成功 / 失败 / 异常路径下都会被调用，确保已抓取的帧不会丢失
- _frames 限长保护，防止极长任务把内存吃光
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Optional


class VideoRecorder:
    # 帧数上限：3fps 下 7200 帧约 40 分钟，足够单次任务，超过则丢最早的帧
    MAX_FRAMES = 7200

    def __init__(self, task_dir: Path, fps: int = 3):
        self.path = task_dir / "recordings" / "recording.mp4"
        self.fps = max(1, fps)
        self._frames: list = []
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stopped = False  # stop() 幂等

    # ----------------------------------------------------------- lifecycle
    def start(self) -> None:
        if self._running:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._running = True
        self._stopped = False
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> Optional[Path]:
        """停止录制并编码。返回已落盘的视频路径或 None。stop() 幂等。"""
        if self._stopped:
            return self.path if self.path.exists() else None
        self._stopped = True
        self._running = False
        if self._thread:
            try:
                self._thread.join(timeout=5)
            except Exception:
                pass
        return self._encode()

    # ----------------------------------------------------------- internals
    def _loop(self) -> None:
        from ..vision import screenshot as shot

        interval = 1.0 / self.fps
        while self._running:
            try:
                self._frames.append(shot.capture_screen())
                # 防止内存膨胀
                if len(self._frames) > self.MAX_FRAMES:
                    self._frames = self._frames[-self.MAX_FRAMES :]
            except Exception:
                pass
            time.sleep(interval)

    def _encode(self) -> Optional[Path]:
        if not self._frames:
            return None
        result: Optional[Path] = None
        try:
            import numpy as np
            import imageio.v2 as imageio

            writer = imageio.get_writer(str(self.path), fps=self.fps, codec="libx264")
            try:
                for f in self._frames:
                    try:
                        writer.append_data(np.array(f))
                    except Exception:
                        # 单帧失败跳过，继续编码后续帧
                        continue
            finally:
                try:
                    writer.close()
                except Exception:
                    pass
            if self.path.exists() and self.path.stat().st_size > 0:
                result = self.path
        except Exception as exc:
            # 编码失败：记录原因到说明文件，便于排查；截图仍在 screenshots/ 目录
            try:
                self.path.with_suffix(".txt").write_text(
                    f"录屏编码失败: {type(exc).__name__}: {exc}\n"
                    f"已抓取 {len(self._frames)} 帧，截图见同任务的 screenshots/ 目录。",
                    encoding="utf-8",
                )
            except Exception:
                pass
        finally:
            self._frames = []
        return result
