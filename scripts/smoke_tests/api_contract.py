"""Smoke test - OpenAPI contract coverage for assist and memory routes.

This is the lightweight drift guard between FastAPI/Pydantic and the
hand-written TypeScript client until full schema codegen is introduced.

Cost: $0.
"""

from __future__ import annotations

from ._common import SmokeResult, prepare_environment, run_smoke

NAME = "api_contract"
REQUIRES_LIVE_LLM = False


async def _body() -> tuple[list[str], list[str], float]:
    prepare_environment()

    from askpicky.api.app import create_app

    app = create_app()
    spec = app.openapi()

    messages: list[str] = []
    failures: list[str] = []
    paths = spec.get("paths", {})

    required_routes = [
        ("/api/assist/start", "post"),
        ("/api/assist/suggest-memory", "post"),
        ("/api/assist/critique-draft", "post"),
        ("/api/assist/polish", "post"),
        ("/api/assist/approve", "post"),
        ("/api/memory/inbox", "get"),
        ("/api/memory/inbox/{item_kind}/{item_id}", "patch"),
        ("/api/memory/inbox/{item_kind}/{item_id}", "delete"),
        ("/api/memory/inbox/merge", "post"),
        ("/api/memory/export", "get"),
        ("/api/memory/privacy/purge-expired", "post"),
    ]
    for path, method in required_routes:
        if method not in paths.get(path, {}):
            failures.append(f"missing OpenAPI route: {method.upper()} {path}")

    components = spec.get("components", {}).get("schemas", {})
    for schema_name in (
        "AssistStartRequest",
        "SuggestMemoryRequest",
        "CritiqueDraftRequest",
        "ApproveAnswerResponse",
        "MemoryInboxUpdateRequest",
        "MemoryExportResponse",
    ):
        if schema_name not in components:
            failures.append(f"missing OpenAPI schema: {schema_name}")

    start_props = components.get("AssistStartRequest", {}).get("properties", {})
    if "private_mode" not in start_props:
        failures.append("AssistStartRequest.private_mode missing from OpenAPI.")

    suggest_props = components.get("SuggestMemoryRequest", {}).get("properties", {})
    if "assist_session_id" not in suggest_props:
        failures.append("SuggestMemoryRequest.assist_session_id missing from OpenAPI.")
    if "include_private" not in suggest_props:
        failures.append("SuggestMemoryRequest.include_private missing from OpenAPI.")

    update_props = components.get("MemoryInboxUpdateRequest", {}).get("properties", {})
    if "text" not in update_props or "summary" not in update_props:
        failures.append("MemoryInboxUpdateRequest edit fields missing from OpenAPI.")

    messages.append(f"assist/memory paths checked={len(required_routes)}")
    return messages, failures, 0.0


async def run() -> SmokeResult:
    return await run_smoke(NAME, _body)


if __name__ == "__main__":
    import asyncio

    asyncio.run(run())
