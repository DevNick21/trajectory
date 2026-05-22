"""Gov data freshness tracking (D3).

scripts/fetch_gov_data.py writes a sidecar `<parquet>.fetched_at.json`
next to every processed parquet after a successful download. Runtime
consumers (salary_data, sponsor_register, soc_check) read the sidecar
to surface a `source_status="STALE"` when data is older than the
freshness window for that source.

Default window: 14 days. Sponsor Register is updated daily by the Home
Office and is the most time-sensitive input; 14 days is a conservative
ceiling that doesn't thrash on a weekly refresh cadence.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Conservative default. Override per-source in code if a specific
# parquet has a different update cadence (e.g. ASHE is annual, so its
# window is much larger — we just don't flag STALE on ASHE at all).
DEFAULT_STALE_WINDOW_DAYS = 14


def _sidecar_path(parquet_path: Path) -> Path:
    return parquet_path.with_suffix(parquet_path.suffix + ".fetched_at.json")


def write_fetched_at(parquet_path: Path) -> None:
    """Write a sidecar with the current UTC timestamp. Idempotent."""
    sidecar = _sidecar_path(parquet_path)
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    sidecar.write_text(
        json.dumps(
            {
                "parquet": parquet_path.name,
                "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
            },
            indent=2,
        )
    )


def read_fetched_at(parquet_path: Path) -> Optional[datetime]:
    """Return the sidecar timestamp, or None when missing / unreadable."""
    sidecar = _sidecar_path(parquet_path)
    if not sidecar.exists():
        return None
    try:
        payload = json.loads(sidecar.read_text())
        raw = payload.get("fetched_at_utc")
        if not isinstance(raw, str):
            return None
        return datetime.fromisoformat(raw)
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning("Could not read freshness sidecar %s: %s", sidecar, exc)
        return None


def is_stale(
    parquet_path: Path,
    window_days: int = DEFAULT_STALE_WINDOW_DAYS,
) -> bool:
    """True when the sidecar is missing OR older than window_days.

    Missing sidecar → stale (conservative default). If callers want a
    different semantics for new installs, they can pre-check existence.
    """
    fetched = read_fetched_at(parquet_path)
    if fetched is None:
        return True
    if fetched.tzinfo is None:
        fetched = fetched.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - fetched > timedelta(days=window_days)
