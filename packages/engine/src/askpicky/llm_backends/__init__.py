"""Provider-agnostic LLM backends. No vendor SDKs — pure httpx.

Each backend implements the `Backend` protocol for structured-output calls.
All providers use the unified OpenAI-compatible chat completions path.
"""

from .base import Backend, BackendError, LLMUsage
from .registry import get_backend

__all__ = ["Backend", "BackendError", "LLMUsage", "get_backend"]
