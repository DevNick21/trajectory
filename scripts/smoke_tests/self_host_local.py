"""Self-hosted local-mode smoke test.

Exercises the public/open-core path without hosted auth, billing, email,
managed AI, or external provider calls.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from ._common import SmokeResult, prepare_environment, run_smoke


async def run() -> SmokeResult:
    async def _body():
        tmp = prepare_environment()

        from askpicky.evaluators import evaluate_answer_claim_support
        from askpicky.applications import (
            create_local_application_from_jd,
            list_applications,
            update_application_status,
        )
        from askpicky.parsers import analyse_job_description
        from askpicky.privacy import export_user_data, hard_delete_user_data
        from askpicky.schemas import AnswerAttempt, CareerEntry, MemorySuggestion, UserProfile
        import askpicky.storage as storage_module
        from askpicky.storage import Storage

        user_id = "self_host_user"
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        storage_module._initialised = False
        storage = Storage()
        await storage.initialise()

        await storage.save_user_profile(
            UserProfile(
                user_id=user_id,
                name="Self Host User",
                user_type="uk_resident",
                base_location="UK",
                salary_floor=0,
                salary_target=None,
                motivations=[],
                deal_breakers=[],
                good_role_signals=[],
                life_constraints=[],
                search_started_date=date.today(),
                current_employment="EMPLOYED",
                created_at=now,
                updated_at=now,
            )
        )
        await storage.insert_career_entry(
            CareerEntry(
                entry_id="cv-python-fastapi",
                user_id=user_id,
                kind="cv_bullet",
                raw_text="Built Python and FastAPI services with PostgreSQL in production.",
                structured={"source": "sample_cv"},
                embedding=[0.0] * 384,
                created_at=now,
            )
        )

        jd_text = """
            Backend Engineer

            Build Python services with FastAPI and PostgreSQL. Candidates must
            have the right to work in the UK and should be comfortable with SQL.
            """
        analysis = analyse_job_description(jd_text)
        evidence = [
            MemorySuggestion(
                memory_id="cv-python-fastapi",
                memory_kind="career_entry",
                title="Python services",
                text="Built Python and FastAPI services with PostgreSQL in production.",
                score=1.0,
                rationale="Matches the pasted job description.",
            )
        ]
        final_answer = "I have built Python and FastAPI services with PostgreSQL in production."
        claim_support = evaluate_answer_claim_support(
            final_answer=final_answer,
            memory_suggestions=evidence,
        )
        await storage.save_answer_attempt(
            AnswerAttempt(
                attempt_id="self-host-answer",
                user_id=user_id,
                question_text="Describe your backend experience.",
                question_type="technical",
                final_answer=final_answer,
                selected_memory_ids=["cv-python-fastapi"],
                save_status="approved",
                raw_retention_until=now + timedelta(days=7),
                created_at=now,
                updated_at=now,
            )
        )
        local_application = await create_local_application_from_jd(
            user_id=user_id,
            jd_text=jd_text,
            company_name="Local Company",
        )
        updated_application = await update_application_status(
            session_id=local_application.session_id,
            new_status="applied",
            notes="Submitted manually from the local tracker.",
        )
        applications = await list_applications(user_id=user_id)

        exported = await export_user_data(user_id=user_id)
        deleted = await hard_delete_user_data(user_id=user_id)
        await storage.close()

        failures = []
        if analysis.application_priority != "maybe_apply_after_checking_filters":
            failures.append("JD analysis did not surface hard-filter review priority.")
        if not claim_support or claim_support[0].status != "supported":
            failures.append("Claim support did not classify the evidence-backed answer as supported.")
        if not exported["career_entries"] or not exported["answer_attempts"]:
            failures.append("Privacy export did not include local CV and answer records.")
        if not exported["application_tracker"]:
            failures.append("Privacy export did not include the local application tracker row.")
        if not applications or updated_application is None or updated_application.status != "applied":
            failures.append("Manual tracker did not create and update the local application row.")
        if (
            not applications
            or applications[0].evidence_snapshot is None
            or not any(
                item.status == "matched"
                for item in applications[0].evidence_snapshot.evidence_checkpoints
            )
        ):
            failures.append("Local tracker did not refresh saved CV evidence against the pasted JD.")
        if deleted.get("career_entries", 0) < 1 or deleted.get("answer_attempts", 0) < 1:
            failures.append("Privacy hard-delete did not remove local CV and answer records.")
        if deleted.get("application_tracker", 0) < 1:
            failures.append("Privacy hard-delete did not remove the local application tracker row.")

        messages = [f"local SQLite path: {tmp / 'smoke.db'}"]
        return messages, failures, 0.0

    return await run_smoke("self_host_local", _body)


if __name__ == "__main__":
    import asyncio

    print(asyncio.run(run()).summary())
