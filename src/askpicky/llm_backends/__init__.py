"""Provider-agnostic LLM backends. No vendor SDKs — pure httpx.

Each backend implements the `Backend` protocol for structured-output calls.
Anthropic-specific features (Citations, server-side tools, Files API,
multi-turn agentic loops) live in `anthropic_backend.py` as module-level
functions because they need the native Messages API format that
OpenAI-compatible backends don't implement.
"""

from .base import Backend, BackendError, LLMUsage
from .registry import get_backend

__all__ = ["Backend", "BackendError", "LLMUsage", "get_backend"]
