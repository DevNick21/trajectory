"""Singleton registry mapping provider name → Backend instance.

Configured from `config.py` settings so adding a new provider is a
config change, not a code change. Supports DeepSeek (primary) and
OpenAI (verdict, benchmarking).
"""

from __future__ import annotations

from typing import Dict

from ..config import settings
from .base import Backend
from .openai_compat_backend import OpenAICompatBackend

_registry: Dict[str, Backend] = {}


def get_backend(provider: str) -> Backend:
    """Return the cached backend singleton for `provider`.

    Backends are created lazily on first access so config validation
    can run before any HTTP client is instantiated.
    """
    if provider not in _registry:
        if provider == "deepseek":
            _registry[provider] = OpenAICompatBackend(
                base_url=settings.deepseek_base_url,
                api_key=settings.deepseek_api_key,
                supports_json_schema=False,
            )
        elif provider == "openai":
            _registry[provider] = OpenAICompatBackend(
                api_key=settings.openai_api_key,
            )
        else:
            raise ValueError(
                f"Unknown provider: {provider!r}. "
                "Expected one of: deepseek, openai."
            )
    return _registry[provider]


def clear_registry() -> None:
    """Reset cached backends (test-only)."""
    _registry.clear()
