"""Abstract backend + shared types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, Optional

from pydantic import BaseModel


@dataclass
class LLMUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0


@dataclass
class LLMCallResult:
    raw: dict
    usage: LLMUsage


class Backend(Protocol):
    """Every provider backend implements this protocol.

    `call()` produces a raw dict matching the Pydantic `output_schema`.
    The caller (llm.py's retry loop) validates and retries.
    """

    async def call(
        self,
        *,
        system_prompt: str | list[dict],
        messages: list[dict],
        output_schema: type[BaseModel],
        model: str,
        effort: str = "xhigh",
    ) -> LLMCallResult:
        ...


class BackendError(Exception):
    """Shared provider error for retriable/non-retriable failures."""

    def __init__(
        self,
        message: str,
        *,
        status_code: Optional[int] = None,
        retriable: bool = False,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.retriable = retriable
