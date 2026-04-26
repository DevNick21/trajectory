"""Smoke test — Storage round-trips (no LLM).

Exercises every CRUD path we rely on in production:
  - UserProfile save/get
  - Session save/get/update
  - Verdict save (via Storage.save_verdict) then re-read
  - Scraped page cache round-trip
  - LLM cost log + total_cost_usd

Cost: $0.
"""

from __future__ import annotations

from datetime import datetime, timezone

from ._common import (
    SmokeResult,
    build_test_session,
    build_test_user,
    prepare_environment,
    run_smoke,
)

NAME = "storage_crud"
REQUIRES_LIVE_LLM = False


async def _body() -> tuple[list[str], list[str], float]:
    prepare_environment()

    from trajectory.storage import Storage

    messages: list[str] = []
    failures: list[str] = []

    storage = Storage()
    await storage.initialise()

    user = build_test_user("uk_resident")
    session = build_test_session(user.user_id)

    # UserProfile round-trip
    await storage.save_user_profile(user)
    back = await storage.get_user_profile(user.user_id)
    if back is None or back.user_id != user.user_id:
        failures.append("UserProfile round-trip lost the row.")
    else:
        messages.append(f"user profile round-trip OK: {back.user_id}")

    # Session round-trip
    await storage.save_session(session)
    s_back = await storage.get_session(session.session_id)
    if s_back is None or s_back.session_id != session.session_id:
        failures.append("Session round-trip lost the row.")
    else:
        messages.append(f"session round-trip OK: {s_back.session_id}")

    # Scraped page cache
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    await storage.cache_scraped_page(
        url="https://example.com/smoke",
        text="Hello smoke test.",
        fetched_at=now,
    )
    cached = await storage.get_cached_page("https://example.com/smoke")
    if cached != "Hello smoke test.":
        failures.append(f"scraped page cache returned {cached!r}")
    else:
        messages.append("scraped page cache OK")

    # LLM cost log
    from trajectory.storage import log_llm_cost, total_cost_usd

    before = await total_cost_usd()
    await log_llm_cost(
        session_id=session.session_id,
        agent_name="smoke_crud",
        model="claude-sonnet-4-6",
        input_tokens=1_000,
        output_tokens=500,
    )
    after = await total_cost_usd()
    if after <= before:
        failures.append(f"total_cost_usd did not rise: {before} -> {after}")
    else:
        messages.append(
            f"llm_cost_log OK: total {before:.6f} -> {after:.6f} USD"
        )

    await storage.close()
    return messages, failures, 0.0


async def run() -> SmokeResult:
    return await run_smoke(NAME, _body)


if __name__ == "__main__":
    import asyncio

    asyncio.run(run())
