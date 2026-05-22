"""Smoke test: PROCESS.md entry numbering is unique.

Ensures no duplicate entry numbers so decision references stay unambiguous.
"""

import re
from pathlib import Path

NAME = "process_entries"


async def _body() -> tuple[list[str], list[str], float]:
    """Return (messages, failures, estimated_cost_usd)."""
    from ._common import prepare_environment

    prepare_environment()
    messages: list[str] = []
    failures: list[str] = []

    process_md = Path(__file__).resolve().parents[2] / "PROCESS.md"
    text = process_md.read_text(encoding="utf-8")
    pattern = re.compile(r"^## Entry (\d+[a-z]*)", re.MULTILINE)
    numbers = [m.group(1) for m in pattern.finditer(text)]

    # Check for duplicates
    seen: dict[str, int] = {}
    for i, n in enumerate(numbers):
        if n in seen:
            failures.append(
                f"Duplicate Entry {n} at line ~{i} (previous at ~{seen[n]})"
            )
        seen[n] = i

    if not failures:
        messages.append(f"All {len(numbers)} entry numbers unique")

    # Check for no gaps in 1..max
    numeric = []
    for n in numbers:
        try:
            numeric.append(int(n))
        except ValueError:
            pass

    if numeric:
        max_n = max(numeric)
        actual = set(numeric)
        missing = sorted(set(range(1, max_n + 1)) - actual)
        early_missing = [m for m in missing if m <= 50]
        if early_missing:
            failures.append(
                f"PROCESS.md missing early entries: {early_missing}. "
                f"If intentional, note why in PROCESS.md."
            )

    return messages, failures, 0.0


async def run():
    from ._common import run_smoke

    return await run_smoke(NAME, _body)
