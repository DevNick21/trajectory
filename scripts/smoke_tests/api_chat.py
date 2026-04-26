"""Smoke test — /api/chat route wiring (PROCESS Entry 45).

The /api/chat endpoint mirrors the Telegram bot's natural-language
entry point on the web. It runs intent_router + dispatches to the
appropriate handler. This smoke exercises the route shape without
spending Opus credits by monkey-patching intent_router and handle_*
calls.

Asserts:
  - 400 on empty message
  - forward_job intent -> reply_kind="redirect" with /?forward=...
  - draft_cv intent -> reply_kind="redirect" with /sessions/{id}/cv
  - profile_query intent -> reply_kind="card" with profile payload
  - chitchat fallback -> reply_kind="text"

Set SMOKE_API_CHAT_LIVE=1 to exercise real intent_router (~$0.05/msg).

Cost: $0 by default.
"""

from __future__ import annotations

import asyncio
import os

from ._common import (
    SmokeResult,
    build_test_session,
    build_test_user,
    prepare_environment,
    run_smoke,
)

NAME = "api_chat"
REQUIRES_LIVE_LLM = False


def _make_routed(intent: str, *, confidence: str = "HIGH",
                 reasoning_brief: str = "test", **extra):
    """Synthesise the IntentRouterOutput shape the orchestrator expects."""
    from trajectory.schemas import IntentRouterOutput
    base = {
        "intent": intent,
        "confidence": confidence,
        "reasoning_brief": reasoning_brief,
        "blocked_by_verdict": False,
        "job_url_ref": None,
        "extracted_params": {},
        "missing_context": False,
    }
    base.update(extra)
    return IntentRouterOutput(**base)


async def _body() -> tuple[list[str], list[str], float]:
    prepare_environment()

    from fastapi.testclient import TestClient
    from trajectory.config import settings
    from trajectory.api.app import create_app

    settings.demo_user_id = "smoke_chat_user"
    settings.enforce_rate_limit = False

    messages: list[str] = []
    failures: list[str] = []

    live = os.getenv("SMOKE_API_CHAT_LIVE", "").lower() in {"1", "true", "yes"}

    app = create_app()

    # Patch intent_router unless we want to spend on real classification.
    original_route = None
    if not live:
        from trajectory.sub_agents import intent_router

        # The route function is dispatched inside chat.py via lazy import,
        # so we patch the symbol on the module.
        original_route = intent_router.route

        # State for which intent the next call should return.
        next_intent = {"intent": "chitchat", "extra": {}}

        async def _fake_route(*, user_message, recent_messages, last_session):
            return _make_routed(next_intent["intent"], **next_intent["extra"])

        intent_router.route = _fake_route

    try:
        with TestClient(app) as client:
            # Seed a user + session for redirect/recent paths.
            user = build_test_user("uk_resident")
            user.user_id = settings.demo_user_id
            session = build_test_session(user.user_id)
            await app.state.storage.save_user_profile(user)
            await app.state.storage.save_session(session)

            # 1. Empty message -> 400.
            resp = client.post("/api/chat", json={"message": ""})
            if resp.status_code != 400:
                failures.append(
                    f"empty message -> {resp.status_code} (expected 400)"
                )

            if not live:
                # 2. forward_job -> redirect.
                next_intent["intent"] = "forward_job"
                next_intent["extra"] = {
                    "job_url_ref": "https://acme.com/jobs/1",
                }
                resp = client.post("/api/chat", json={
                    "message": "forward https://acme.com/jobs/1",
                })
                body = resp.json()
                if resp.status_code != 200:
                    failures.append(f"forward_job -> {resp.status_code}: {body}")
                elif body.get("reply_kind") != "redirect":
                    failures.append(
                        f"forward_job reply_kind={body.get('reply_kind')!r}"
                    )
                elif "forward=" not in (body.get("redirect_to") or ""):
                    failures.append(
                        f"forward_job redirect_to={body.get('redirect_to')!r}"
                    )
                else:
                    messages.append(
                        f"forward_job: redirect_to={body['redirect_to']!r}"
                    )

                # 3. draft_cv -> redirect to /sessions/{id}/cv.
                next_intent["intent"] = "draft_cv"
                next_intent["extra"] = {}
                resp = client.post("/api/chat", json={
                    "message": "draft me a CV",
                    "session_id": session.session_id,
                })
                body = resp.json()
                if resp.status_code != 200:
                    failures.append(f"draft_cv -> {resp.status_code}: {body}")
                elif body.get("reply_kind") != "redirect":
                    failures.append(
                        f"draft_cv reply_kind={body.get('reply_kind')!r}"
                    )
                elif not (body.get("redirect_to") or "").endswith("/cv"):
                    failures.append(
                        f"draft_cv redirect_to={body.get('redirect_to')!r}"
                    )
                else:
                    messages.append(
                        f"draft_cv: redirect_to={body['redirect_to']!r}"
                    )

                # 4. profile_query -> card with profile payload.
                next_intent["intent"] = "profile_query"
                next_intent["extra"] = {}
                resp = client.post("/api/chat", json={
                    "message": "what's my floor?",
                })
                body = resp.json()
                if resp.status_code != 200:
                    failures.append(f"profile_query -> {resp.status_code}: {body}")
                elif body.get("reply_kind") != "card":
                    failures.append(
                        f"profile_query reply_kind={body.get('reply_kind')!r}"
                    )
                elif "profile" not in (body.get("payload") or {}):
                    failures.append(
                        f"profile_query payload missing 'profile': "
                        f"{body.get('payload')}"
                    )
                else:
                    messages.append(
                        f"profile_query: card with payload.profile keys="
                        f"{list(body['payload']['profile'].keys())[:4]}"
                    )

                # 5. chitchat -> text fallback.
                next_intent["intent"] = "chitchat"
                next_intent["extra"] = {}
                resp = client.post("/api/chat", json={
                    "message": "hello",
                })
                body = resp.json()
                if resp.status_code != 200:
                    failures.append(f"chitchat -> {resp.status_code}: {body}")
                elif body.get("reply_kind") != "text":
                    failures.append(
                        f"chitchat reply_kind={body.get('reply_kind')!r}"
                    )
                else:
                    messages.append(
                        f"chitchat: text reply, intent={body.get('intent')!r}"
                    )

    finally:
        if original_route is not None:
            from trajectory.sub_agents import intent_router
            intent_router.route = original_route

    return messages, failures, 0.0


async def run() -> SmokeResult:
    return await run_smoke(NAME, _body)


if __name__ == "__main__":
    result = asyncio.run(run())
    print(result.summary())
    for m in result.messages:
        print("  ", m)
    for f in result.failures:
        print("  FAIL:", f)
