"""Smoke test — gov data freshness sidecars (no LLM).

Exercises:
  - write_fetched_at creates a sidecar JSON
  - read_fetched_at returns the stored timestamp
  - is_stale: fresh sidecar reads as non-stale; artificially backdated
    sidecar reads as stale; missing sidecar reads as stale

Cost: $0.
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ._common import SmokeResult, prepare_environment, run_smoke

NAME = "data_freshness"
REQUIRES_LIVE_LLM = False


async def _body() -> tuple[list[str], list[str], float]:
    prepare_environment()

    from trajectory.data_freshness import (
        is_stale,
        read_fetched_at,
        write_fetched_at,
    )

    messages: list[str] = []
    failures: list[str] = []

    tmp = Path(tempfile.mkdtemp(prefix="smoke-freshness-"))
    parquet = tmp / "example.parquet"
    parquet.write_bytes(b"not a real parquet")

    # Write + read round trip.
    write_fetched_at(parquet)
    fetched = read_fetched_at(parquet)
    if fetched is None:
        failures.append("read_fetched_at returned None right after write.")
    else:
        messages.append(f"sidecar round-trip OK: {fetched.isoformat()}")

    # Fresh sidecar is not stale.
    if is_stale(parquet, window_days=14):
        failures.append("fresh sidecar incorrectly reported stale.")

    # Backdate the sidecar and confirm is_stale flips to True.
    sidecar = parquet.with_suffix(parquet.suffix + ".fetched_at.json")
    old = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat()
    sidecar.write_text(json.dumps({
        "parquet": parquet.name,
        "fetched_at_utc": old,
    }))
    if not is_stale(parquet, window_days=14):
        failures.append("backdated sidecar (400 days) not flagged stale.")
    else:
        messages.append("backdated sidecar correctly flagged stale")

    # Missing sidecar is stale.
    no_sidecar = tmp / "missing.parquet"
    no_sidecar.write_bytes(b"")
    if not is_stale(no_sidecar):
        failures.append("missing sidecar not flagged stale.")
    else:
        messages.append("missing sidecar correctly flagged stale")

    return messages, failures, 0.0


async def run() -> SmokeResult:
    return await run_smoke(NAME, _body)


if __name__ == "__main__":
    import asyncio

    asyncio.run(run())
