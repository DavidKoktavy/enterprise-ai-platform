from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class Completion:
    content: str
    prompt_tokens: int
    completion_tokens: int
    finish_reason: str = "stop"


class ProviderError(Exception):
    """Raised for provider failures. `retryable` drives fallback routing."""

    def __init__(self, message: str, status: int = 502, retryable: bool = True):
        super().__init__(message)
        self.status = status
        self.retryable = retryable


class Provider(Protocol):
    name: str

    async def chat(
        self,
        deployment: str,
        messages: list[dict],
        *,
        temperature: float,
        max_tokens: int,
        response_format: dict | None,
    ) -> Completion: ...
