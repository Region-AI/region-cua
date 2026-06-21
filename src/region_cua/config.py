"""配置管理：从环境变量 / .env 文件加载，所有字段均有默认值。"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """RegionCUA 全局配置。

    优先级：环境变量 > 项目根 .env 文件 > 代码默认值。
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    ollama_host: str = "http://localhost:11434"
    # 规划与视觉默认使用同一个模型，避免 Ollama 在两个模型之间反复
    # 切换（每次切换需要重新加载到 VRAM，开销 30+ 秒）。
    # qwen3.6:latest 是 36B MoE，原生支持 vision + tools + thinking。
    ollama_planner_model: str = "qwen3.6:latest"
    ollama_vision_model: str = "qwen3.6:latest"
    output_dir: str = "outputs"
    max_consecutive_failures: int = 3
    ollama_timeout: int = 600
    video_fps: int = 5

    @property
    def output_path(self) -> Path:
        p = Path(self.output_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p


def get_settings() -> Settings:
    """获取配置单例（每次读取最新环境变量，开销极小）。"""
    return Settings()
