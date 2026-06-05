"""Small provider protocol shared by hosted and self-hosted adapters."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from pydantic import BaseModel, Field


class AIProviderRequest(BaseModel):
    model: str
    messages: Sequence[Mapping[str, Any]]
    system_prompt: str = ""
    max_tokens: int | None = None
    response_format: str | None = None


class AIProviderResponse(BaseModel):
    content: str
    input_tokens: int = 0
    output_tokens: int = 0
    provider_metadata: dict[str, Any] = Field(default_factory=dict)


class ProviderAdapter(Protocol):
    provider_name: str

    async def complete(self, request: AIProviderRequest) -> AIProviderResponse:
        """Return one completion from the configured model provider."""
