"""Agent system prompts, one Markdown file per prompt.

Keeping prompts as plain Markdown alongside the code gives us:
  - git-based versioning (`git log src/trajectory/prompts/verdict.md`)
  - readable diffs across prompt iterations
  - ability to view prompts without opening a Python file
  - a stable surface for the Prompt Auditor (AGENTS.md §17) to ingest

Every file is loaded lazily via `load_prompt("<name>")`. Nested prompts
(onboarding per-stage descriptions + shared rules) live under
subfolders and are loaded with `load_prompt("<name>", subdir="<folder>")`.

Files are read at module import time in the corresponding sub_agent
(e.g. `verdict.py` does `SYSTEM_PROMPT = load_prompt("verdict")` at the
top). That keeps the sub_agent's public surface identical to before
— callers still reference `SYSTEM_PROMPT` — while making the text
editable without touching Python.

Storage layout:

    src/trajectory/prompts/
    ├── __init__.py                 (this file)
    ├── verdict.md
    ├── intent_router.md
    ├── content_shield_tier2.md
    ├── ... (one per agent) ...
    └── onboarding/
        ├── common_rules.md
        ├── career.md
        ├── motivations.md
        └── ...

Prompts are shipped with the package via pyproject.toml's
`[tool.setuptools.package-data]` so `pip install trajectory` on a fresh
host still resolves them.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional


_PROMPTS_ROOT = Path(__file__).resolve().parent


class PromptNotFound(FileNotFoundError):
    """Raised when a named prompt file isn't on disk."""


@lru_cache(maxsize=None)
def load_prompt(name: str, *, subdir: Optional[str] = None) -> str:
    """Return the text of a prompt file.

    Args:
        name: Filename without extension. `"verdict"` → `verdict.md`.
        subdir: Optional subfolder inside `prompts/`. Use for nested
            prompts like onboarding stage descriptions.

    Returns:
        The file contents with trailing whitespace stripped. Leading
        whitespace is preserved so indented code blocks inside prompts
        survive verbatim.

    Raises:
        PromptNotFound: if the file doesn't exist. We fail loud rather
            than returning an empty prompt, because a missing prompt
            would silently ship an undefined agent to production.

    Results are cached — prompt files are read once per process. Call
    `load_prompt.cache_clear()` if you edit a file and want the new
    text without restarting (mostly useful in a notebook / REPL).
    """
    parts: list[str] = []
    if subdir:
        parts.append(subdir)
    parts.append(f"{name}.md")
    path = _PROMPTS_ROOT.joinpath(*parts)

    if not path.exists():
        raise PromptNotFound(
            f"Prompt file not found: {path} "
            f"(resolved from name={name!r}, subdir={subdir!r})"
        )

    return path.read_text(encoding="utf-8").rstrip()


def prompt_path(name: str, *, subdir: Optional[str] = None) -> Path:
    """Return the absolute Path to a prompt file without reading it.

    Useful for tooling (the Prompt Auditor CLI, test fixtures) that
    wants to watch or checksum a specific prompt.
    """
    parts: list[str] = []
    if subdir:
        parts.append(subdir)
    parts.append(f"{name}.md")
    return _PROMPTS_ROOT.joinpath(*parts)


__all__ = ["load_prompt", "prompt_path", "PromptNotFound"]
