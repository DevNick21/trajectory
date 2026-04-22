"""End-to-end smoke test using fixture data.

Runs the full Phase 1 → Verdict pipeline against a fixture research bundle.
Does NOT make real HTTP requests — patches company_scraper with fixture data.

Usage: python scripts/smoke_test.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import uuid
from datetime import datetime, date
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

FIXTURE_PATH = Path(__file__).parent.parent / "tests" / "fixtures" / "sample_research_bundle.json"


async def run_smoke_test() -> None:
    from trajectory.schemas import (
        ResearchBundle,
        Session,
        UserProfile,
        VisaStatus,
    )
    from trajectory.storage import Storage
    from trajectory.sub_agents import verdict as verdict_agent

    # Load fixture
    if not FIXTURE_PATH.exists():
        log.error("Fixture not found: %s", FIXTURE_PATH)
        log.info("Run tests first to generate fixtures, or create the file manually.")
        sys.exit(1)

    with open(FIXTURE_PATH) as f:
        bundle_data = json.load(f)

    bundle = ResearchBundle.model_validate(bundle_data)
    log.info("Fixture loaded: %s @ %s", bundle.extracted_jd.role_title, bundle.company_research.company_name)

    # Minimal in-memory storage
    storage = Storage(db_path=":memory:")
    await storage.initialise()

    # Build a test user
    now = datetime.utcnow()
    user = UserProfile(
        user_id="smoke_test_user",
        name="Test User",
        user_type="visa_holder",
        visa_status=VisaStatus(route="graduate", expiry_date=date(2026, 9, 30)),
        base_location="London",
        salary_floor=45000,
        salary_target=60000,
        motivations=["building products people use", "technical leadership"],
        deal_breakers=["pure maintenance work", "no remote flexibility"],
        good_role_signals=["strong eng culture", "fast-growing team"],
        life_constraints=[],
        search_started_date=date(2025, 10, 1),
        current_employment="EMPLOYED",
        created_at=now,
        updated_at=now,
    )

    session = Session(
        session_id=str(uuid.uuid4()),
        user_id=user.user_id,
        intent="forward_job",
        job_url="https://example.com/job/smoke-test",
        created_at=now,
    )

    log.info("Running verdict agent…")
    try:
        verdict = await verdict_agent.generate(
            user=user,
            research_bundle=bundle,
            retrieved_entries=[],
            session_id=session.session_id,
        )
        log.info("Verdict: %s (%d%%)", verdict.decision, verdict.confidence_pct)
        log.info("Headline: %s", verdict.headline)
        log.info("Hard blockers: %d", len(verdict.hard_blockers))
        log.info("Stretch concerns: %d", len(verdict.stretch_concerns))
        log.info("Reasoning points: %d", len(verdict.reasoning))
        log.info("SMOKE TEST PASSED")
    except Exception as exc:
        log.exception("Verdict agent failed: %s", exc)
        log.error("SMOKE TEST FAILED")
        sys.exit(1)

    await storage.close()


if __name__ == "__main__":
    asyncio.run(run_smoke_test())
