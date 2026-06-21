from __future__ import annotations

from typing import Any, Iterable, Protocol


class VisionClient(Protocol):
    """视觉模型客户端接口，OllamaClient 与 VLLMClient 均实现此协议。"""

    def chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        images: Iterable[Any] | None = None,
        think: bool = False,
    ) -> str:
        ...

    def close(self) -> None:
        ...
