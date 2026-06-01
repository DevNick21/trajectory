"""Smoke test — deterministic application-assist memory graph (no LLM).

Seeds one answer attempt, extracts reviewable memory items, approves one
atom, and verifies hybrid recall can surface it. This covers the privacy
gate that pending memory must not influence suggestions until reviewed.

Cost: $0.
"""

from __future__ import annotations

from ._common import SmokeResult, build_test_user, prepare_environment, run_smoke

NAME = "application_memory"
REQUIRES_LIVE_LLM = False


async def _body() -> tuple[list[str], list[str], float]:
    prepare_environment()

    from askpicky.memory.application_assist import (
        build_answer_attempt,
        build_assist_session,
        classify_question,
        critique_draft,
        deterministic_memory_from_attempt,
        now_utc,
    )
    from askpicky.storage import Storage

    messages: list[str] = []
    failures: list[str] = []

    storage = Storage()
    await storage.initialise()

    user = build_test_user("uk_resident")
    user.user_id = "smoke_application_memory_user"
    await storage.save_user_profile(user)

    assist_session = build_assist_session(
        user_id=user.user_id,
        company_name="Betfred",
        role_title="Senior Data Analyst",
        jd_text="Stakeholder communication, dashboard delivery, Python, SQL.",
    )
    await storage.save_application_assist_session(assist_session)
    loaded_session = await storage.get_application_assist_session(
        assist_session.assist_session_id,
    )
    if loaded_session is None:
        failures.append("assist session was not persisted.")

    question = "Describe a time you influenced non-technical stakeholders."
    draft = (
        "At Betfred I built a dashboard for trading stakeholders. I gathered "
        "their reporting pain points, shipped a clearer view in SQL and Python, "
        "and used weekly feedback to make it usable for the trading desk."
    )
    pattern = classify_question(question, assist_session.jd_text or "")
    critique = critique_draft(
        question_text=question,
        draft_text=draft,
        question_pattern=pattern,
        word_limit=200,
        suggestions=[],
        advice_snippets=[],
    )
    attempt = build_answer_attempt(
        user=user,
        assist_session_id=assist_session.assist_session_id,
        session_id=assist_session.session_id,
        question_text=question,
        question_type=pattern.question_type,
        raw_draft=draft,
        final_answer=draft,
        word_limit=200,
        company_name=assist_session.company_name,
        role_title=assist_session.role_title,
        critique=critique,
    )
    attempt.raw_retention_until = now_utc()
    await storage.save_answer_attempt(attempt)

    loaded_attempt = await storage.get_answer_attempt(attempt.attempt_id)
    if loaded_attempt is None:
        failures.append("answer attempt was not persisted.")

    atoms, stories = deterministic_memory_from_attempt(attempt)
    if not atoms:
        failures.append("deterministic extractor produced no atoms.")
    if not stories:
        failures.append("deterministic extractor produced no story frame.")

    for atom in atoms:
        await storage.save_experience_atom(atom)
    for story in stories:
        await storage.save_story_frame(story)

    pending = await storage.list_memory_inbox(user.user_id, status="pending")
    pending_count = len(pending["experience_atoms"]) + len(pending["story_frames"])
    messages.append(f"pending inbox items={pending_count}")
    if pending_count == 0:
        failures.append("Memory Inbox did not show pending extracted items.")

    before_review = await storage.retrieve_application_memory_suggestions(
        user_id=user.user_id,
        query_text="stakeholder dashboard communication",
        question_type=pattern.question_type,
    )
    if before_review:
        failures.append("pending memory influenced suggestions before approval.")

    if atoms:
        ok = await storage.update_memory_review_status(
            user_id=user.user_id,
            item_kind="experience_atom",
            item_id=atoms[0].atom_id,
            review_status="approved",
        )
        if not ok:
            failures.append("failed to approve pending atom.")

    after_review = await storage.retrieve_application_memory_suggestions(
        user_id=user.user_id,
        query_text="stakeholder dashboard communication",
        question_type=pattern.question_type,
    )
    if after_review:
        failures.append("private approved memory was retrieved without opt-in.")

    after_private_opt_in = await storage.retrieve_application_memory_suggestions(
        user_id=user.user_id,
        query_text="stakeholder dashboard communication",
        question_type=pattern.question_type,
        include_private=True,
    )
    messages.append(f"approved private recall suggestions={len(after_private_opt_in)}")
    if not after_private_opt_in:
        failures.append("approved private memory was not retrieved with opt-in.")

    other_user_recall = await storage.retrieve_application_memory_suggestions(
        user_id="smoke_application_memory_other_user",
        query_text="stakeholder dashboard communication",
        question_type=pattern.question_type,
        include_private=True,
    )
    if other_user_recall:
        failures.append("memory recall leaked across user ids.")

    purged = await storage.purge_expired_answer_attempt_raw(user_id=user.user_id)
    messages.append(f"expired raw attempts purged={purged}")
    purged_attempt = await storage.get_answer_attempt(attempt.attempt_id)
    if purged_attempt is None:
        failures.append("purged attempt disappeared instead of retaining metadata.")
    elif purged_attempt.raw_draft or purged_attempt.transcript is not None:
        failures.append("raw draft/transcript were not cleared by retention purge.")

    exported = await storage.export_user_memory(user_id=user.user_id, include_raw=False)
    if exported["answer_attempts"] and exported["answer_attempts"][0].raw_draft:
        failures.append("memory export include_raw=false leaked raw draft text.")

    if atoms:
        deleted = await storage.hard_delete_memory_item(
            user_id=user.user_id,
            item_kind="experience_atom",
            item_id=atoms[0].atom_id,
        )
        if not deleted:
            failures.append("hard delete did not remove owned atom.")

    await storage.close()
    return messages, failures, 0.0


async def run() -> SmokeResult:
    return await run_smoke(NAME, _body)


if __name__ == "__main__":
    import asyncio

    asyncio.run(run())
