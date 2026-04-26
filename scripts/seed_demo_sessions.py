"""Insert 5 fake sessions into the local SQLite DB to populate the
SessionList for demo recording.

The frontend's `_summarise` (api/routes/sessions.py) only reads:
- session_id, user_id, intent, created_at
- verdict.decision  (string)
- phase1_output.extracted_jd.role_title
- phase1_output.company_research.company_name

So we write minimal JSON payloads directly — no need to satisfy the full
`Verdict` schema (which requires reasoning/hard_blockers/motivation_fit).
The `_summarise` function explicitly tolerates raw-dict verdicts.

Usage:
    DEMO_USER_ID=<your-id> python scripts/seed_demo_sessions.py

The Capital on Tap session is intentionally NOT included — that one runs
live as your hero take, lands at the top of the list, and the 5 fakes
sit underneath as the populated history.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

DB_PATH = Path("./data/trajectory.db")

# 5 plausible UK roles, mixed verdicts. Ordered newest-first; created_at
# offsets are days back from "now" so the list reads as recent activity.
FIXTURES = [
    {
        "days_ago": 1,
        "intent": "forward_job",
        "job_url": "https://job-boards.greenhouse.io/monzo/jobs/6543210",
        "role_title": "Senior Backend Engineer",
        "company_name": "Monzo Bank",
        "decision": "GO",
    },
    {
        "days_ago": 2,
        "intent": "forward_job",
        "job_url": "https://apply.workable.com/cleo/j/D2A4B7C8E1/",
        "role_title": "Data Scientist, Customer Insights",
        "company_name": "Cleo AI",
        "decision": "NO_GO",
    },
    {
        "days_ago": 4,
        "intent": "forward_job",
        "job_url": "https://octopus.energy/careers/ml-engineer-london",
        "role_title": "ML Engineer — Forecasting",
        "company_name": "Octopus Energy",
        "decision": "GO",
    },
    {
        "days_ago": 6,
        "intent": "forward_job",
        "job_url": "https://wise.com/jobs/4567890-software-engineer",
        "role_title": "Software Engineer (Platform)",
        "company_name": "Wise",
        "decision": "NO_GO",
    },
    {
        "days_ago": 9,
        "intent": "forward_job",
        "job_url": "https://boards.greenhouse.io/stripe/jobs/8123456",
        "role_title": "AI Engineer, Applied",
        "company_name": "Stripe",
        "decision": "GO",
    },
]


def build_payload(user_id: str, fixture: dict, created_at: datetime) -> dict:
    """Produce a Session-shaped JSON payload that satisfies _summarise()."""
    return {
        "session_id": str(uuid.uuid4()),
        "user_id": user_id,
        "intent": fixture["intent"],
        "job_url": fixture["job_url"],
        "job_id": None,
        "phase1_output": {
            "extracted_jd": {"role_title": fixture["role_title"]},
            "company_research": {"company_name": fixture["company_name"]},
        },
        "verdict": {"decision": fixture["decision"]},
        "generated_components": {},
        "telegram_messages": [],
        "created_at": created_at.isoformat(),
    }


def main() -> int:
    user_id = os.environ.get("DEMO_USER_ID", "").strip()
    if not user_id:
        print("ERROR: set DEMO_USER_ID in your environment first.", file=sys.stderr)
        return 1
    if not DB_PATH.exists():
        print(f"ERROR: {DB_PATH} not found. Run the app once to create it.", file=sys.stderr)
        return 1

    now = datetime.now(timezone.utc)
    inserted = 0

    with sqlite3.connect(DB_PATH) as conn:
        for f in FIXTURES:
            created = now - timedelta(days=f["days_ago"], hours=2 * f["days_ago"])
            payload = build_payload(user_id, f, created)
            conn.execute(
                "INSERT INTO sessions (session_id, user_id, intent, payload, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    payload["session_id"],
                    user_id,
                    payload["intent"],
                    json.dumps(payload),
                    created.isoformat(),
                ),
            )
            inserted += 1
        conn.commit()

    print(f"Inserted {inserted} fake sessions for user_id={user_id}.")
    print("Refresh the dashboard — they should appear under the latest live session.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
