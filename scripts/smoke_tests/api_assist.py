"""Smoke test — application-assist API contract (FastAPI TestClient, no LLM).

Exercises start -> classify -> suggest -> critique -> approve -> Memory Inbox
review. The live LLM polish endpoint is intentionally out of scope here and
covered by the application_answer_shaper smoke test.

Cost: $0.
"""

from __future__ import annotations

import asyncio

from ._common import (
    SmokeResult,
    build_test_user,
    prepare_environment,
    run_smoke,
)

NAME = "api_assist"
REQUIRES_LIVE_LLM = False


async def _body() -> tuple[list[str], list[str], float]:
    prepare_environment()

    from fastapi.testclient import TestClient

    from askpicky.api.app import create_app
    from askpicky.config import settings

    settings.demo_user_id = "smoke_api_assist_user"

    messages: list[str] = []
    failures: list[str] = []
    app = create_app()

    with TestClient(app) as client:
        user = build_test_user("uk_resident")
        user.user_id = settings.demo_user_id
        await app.state.storage.save_user_profile(user)

        start_resp = client.post(
            "/api/assist/start",
            json={
                "company_name": "Betfred",
                "role_title": "Senior Data Analyst",
                "jd_text": "SQL dashboards and stakeholder communication.",
            },
        )
        if start_resp.status_code != 200:
            failures.append(f"assist/start returned {start_resp.status_code}: {start_resp.text[:200]!r}")
            return messages, failures, 0.0
        assist_id = start_resp.json()["assist_session"]["assist_session_id"]
        if start_resp.json()["assist_session"]["private_mode"] is not True:
            failures.append("assist/start did not default to private_mode=true.")
        messages.append(f"assist_session_id={assist_id[:8]}")

        classify_resp = client.post(
            "/api/assist/classify-question",
            json={"question_text": "Tell us about a time you handled conflict."},
        )
        if classify_resp.status_code != 200:
            failures.append(
                f"classify-question returned {classify_resp.status_code}: "
                f"{classify_resp.text[:200]!r}"
            )
        else:
            qtype = classify_resp.json()["pattern"]["question_type"]
            messages.append(f"classified question_type={qtype}")

        suggest_resp = client.post(
            "/api/assist/suggest-memory",
            json={
                "assist_session_id": assist_id,
                "question_text": "Describe a stakeholder dashboard project.",
                "jd_text": "SQL dashboard delivery for trading teams.",
                "include_private": False,
            },
        )
        if suggest_resp.status_code != 200:
            failures.append(f"suggest-memory returned {suggest_resp.status_code}: {suggest_resp.text[:200]!r}")
        else:
            messages.append(
                f"advice snippets={len(suggest_resp.json().get('advice_snippets', []))}"
            )

        critique_resp = client.post(
            "/api/assist/critique-draft",
            json={
                "assist_session_id": assist_id,
                "question_text": "Describe a stakeholder dashboard project.",
                "raw_draft": (
                    "I built a dashboard for trading stakeholders at Betfred, "
                    "using SQL and Python to make weekly reporting clearer."
                ),
                "word_limit": 200,
            },
        )
        if critique_resp.status_code != 200:
            failures.append(f"critique-draft returned {critique_resp.status_code}: {critique_resp.text[:200]!r}")
            return messages, failures, 0.0
        attempt_id = critique_resp.json()["attempt_id"]
        if critique_resp.json().get("save_indicator") != "Saved privately":
            failures.append("critique-draft did not return private save indicator.")
        messages.append(f"attempt_id={attempt_id[:8]}")

        approve_resp = client.post(
            "/api/assist/approve",
            json={
                "attempt_id": attempt_id,
                "final_answer": (
                    "At Betfred I built a SQL and Python dashboard for trading "
                    "stakeholders, turning unclear weekly reporting into a "
                    "usable view they could discuss in planning meetings."
                ),
            },
        )
        if approve_resp.status_code != 200:
            failures.append(f"approve returned {approve_resp.status_code}: {approve_resp.text[:200]!r}")
            return messages, failures, 0.0
        if approve_resp.json().get("save_indicator") != "Saved privately":
            failures.append("approve did not preserve private save indicator.")

        inbox_resp = client.get("/api/memory/inbox?status_filter=pending")
        if inbox_resp.status_code != 200:
            failures.append(f"memory inbox returned {inbox_resp.status_code}: {inbox_resp.text[:200]!r}")
            return messages, failures, 0.0
        inbox = inbox_resp.json()
        item_count = len(inbox["experience_atoms"]) + len(inbox["story_frames"])
        messages.append(f"inbox pending={item_count}")
        if item_count == 0:
            failures.append("approve did not create reviewable memory items.")
            return messages, failures, 0.0

        atom = inbox["experience_atoms"][0]
        patch_resp = client.patch(
            f"/api/memory/inbox/experience_atom/{atom['atom_id']}",
            json={
                "review_status": "approved",
                "visibility": "private",
                "text": "SQL and Python dashboard for trading stakeholders",
            },
        )
        if patch_resp.status_code != 200:
            failures.append(f"memory inbox PATCH returned {patch_resp.status_code}: {patch_resp.text[:200]!r}")
        elif patch_resp.json().get("ok") is not True:
            failures.append("memory inbox PATCH did not return ok=true.")

        public_recall_resp = client.post(
            "/api/assist/suggest-memory",
            json={
                "assist_session_id": assist_id,
                "question_text": "Describe a SQL stakeholder dashboard project.",
                "include_private": False,
            },
        )
        if public_recall_resp.status_code != 200:
            failures.append(
                f"public recall returned {public_recall_resp.status_code}: "
                f"{public_recall_resp.text[:200]!r}"
            )
        elif public_recall_resp.json()["suggestions"]:
            failures.append("private approved memory appeared in public recall.")

        private_recall_resp = client.post(
            "/api/assist/suggest-memory",
            json={
                "assist_session_id": assist_id,
                "question_text": "Describe a SQL stakeholder dashboard project.",
                "include_private": True,
            },
        )
        if private_recall_resp.status_code != 200:
            failures.append(
                f"private recall returned {private_recall_resp.status_code}: "
                f"{private_recall_resp.text[:200]!r}"
            )
        elif not private_recall_resp.json()["suggestions"]:
            failures.append("private approved memory did not appear with explicit opt-in.")

        export_resp = client.get("/api/memory/export?include_raw=false")
        if export_resp.status_code != 200:
            failures.append(f"memory export returned {export_resp.status_code}: {export_resp.text[:200]!r}")
        else:
            attempts = export_resp.json().get("answer_attempts", [])
            if attempts and attempts[0].get("raw_draft"):
                failures.append("memory export include_raw=false returned raw draft.")

        delete_resp = client.delete(f"/api/memory/inbox/experience_atom/{atom['atom_id']}")
        if delete_resp.status_code != 200:
            failures.append(f"memory hard delete returned {delete_resp.status_code}: {delete_resp.text[:200]!r}")

    return messages, failures, 0.0


async def run() -> SmokeResult:
    return await run_smoke(NAME, _body)


if __name__ == "__main__":
    asyncio.run(run())
