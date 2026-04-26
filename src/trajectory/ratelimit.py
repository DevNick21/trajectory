"""In-memory sliding-window rate limiter.

Keyed on `(user_id, intent_category)` so a user can hit different
generators at their own per-intent limits without cross-contamination.
Gated behind `settings.enforce_rate_limit` — unchanged behaviour when
the flag is off so the demo can stay wide open while the production
default tightens up.

Defaults (see `DEFAULT_LIMITS`) are chosen to let a reasonable single
user exercise the product without ever hitting them, while an abusive
client (or a stuck client-side retry loop) gets throttled within
seconds of misbehaving.

Not persistent across restarts. A restart wipes the buckets — fine
for a single-process demo, and for prod the limiter should be
upgraded to a Redis-backed sliding window before we grow past one
FastAPI worker.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Literal


IntentCategory = Literal["forward_job", "generator", "chitchat"]


@dataclass(frozen=True)
class Limit:
    """`max_calls` within `window_s` seconds before a caller is throttled."""

    max_calls: int
    window_s: float


# Intent → limit. Picking these conservatively:
#   forward_job: the expensive path (Phase 1 fan-out + verdict = ~$1 Opus).
#     5/min is well above any real user's pace and well below a runaway
#     loop's pace.
#   generator: CV, cover letter, draft reply etc. Pack-level generation.
#   chitchat: intent routing, recent list, profile query — cheap.
DEFAULT_LIMITS: dict[str, Limit] = {
    "forward_job": Limit(max_calls=5, window_s=60.0),
    "generator": Limit(max_calls=10, window_s=3600.0),
    "chitchat": Limit(max_calls=30, window_s=60.0),
}


# Per-intent → category mapping. Unknown intents fall through to
# "chitchat" (cheap) by default rather than "generator" (expensive),
# because being wrong toward cheap is safer than being wrong toward
# locking out a benign path.
_INTENT_CATEGORY: dict[str, IntentCategory] = {
    "forward_job": "forward_job",
    "draft_cv": "generator",
    "draft_cover_letter": "generator",
    "predict_questions": "generator",
    "salary_advice": "generator",
    "full_prep": "generator",
    "draft_reply": "generator",
    # PROCESS Entry 43, Workstream F — analyse_offer is generator-class
    # (one Opus xhigh call + Files API upload).
    "analyse_offer": "generator",
    "profile_query": "chitchat",
    "profile_edit": "chitchat",
    "recent": "chitchat",
}


def intent_to_category(intent: str) -> IntentCategory:
    return _INTENT_CATEGORY.get(intent, "chitchat")


@dataclass
class RateLimitResult:
    allowed: bool
    retry_after_s: float = 0.0
    category: IntentCategory = "chitchat"


class RateLimiter:
    """Thread-safe sliding-window limiter.

    Uses a per-bucket deque of hit timestamps. O(window_hit_count) per
    `check` — fine for the bucket sizes above (max ~30 entries). The
    lock is a plain threading.Lock since check() is sync — callers on
    the asyncio path hold it for microseconds.
    """

    def __init__(self, limits: dict[str, Limit] | None = None) -> None:
        self._limits = dict(limits or DEFAULT_LIMITS)
        self._buckets: dict[tuple[str, str], deque[float]] = {}
        self._lock = threading.Lock()

    def check(self, user_id: str, intent: str) -> RateLimitResult:
        category = intent_to_category(intent)
        limit = self._limits.get(category)
        if limit is None:
            return RateLimitResult(allowed=True, category=category)

        key = (user_id, category)
        now = time.monotonic()
        with self._lock:
            bucket = self._buckets.setdefault(key, deque())
            cutoff = now - limit.window_s
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= limit.max_calls:
                # Earliest timestamp + window tells the caller when the
                # oldest call falls out of the window and capacity frees.
                retry_after = max(0.0, bucket[0] + limit.window_s - now)
                return RateLimitResult(
                    allowed=False,
                    retry_after_s=retry_after,
                    category=category,
                )
            bucket.append(now)
            return RateLimitResult(allowed=True, category=category)

    def reset(self, user_id: str | None = None) -> None:
        """Test helper — clear all buckets or just a single user's."""
        with self._lock:
            if user_id is None:
                self._buckets.clear()
                return
            for key in list(self._buckets):
                if key[0] == user_id:
                    self._buckets.pop(key, None)
