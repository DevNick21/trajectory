"""Privacy metadata for the local SQLite open-core data model."""

from __future__ import annotations

import json
from typing import Any

USER_SCOPED_TABLES: dict[str, str | None] = {
    "user_profiles": "user_id",
    "career_entries": "user_id",
    "writing_style_profiles": "user_id",
    "sessions": "user_id",
    "llm_cost_log": None,
    "security_audit_events": "user_id",
    "queued_jobs": "user_id",
    "jobs": "user_id",
    "application_tracker": "user_id",
    "application_assist_sessions": "user_id",
    "answer_attempts": "user_id",
    "experience_atoms": "user_id",
    "story_frames": "user_id",
    "memory_edges": "user_id",
}


def redact_export_rows(*, table: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return export rows with high-variance raw text fields blanked."""

    if table not in {"answer_attempts", "career_entries"}:
        return rows
    redacted: list[dict[str, Any]] = []
    for row in rows:
        copied = dict(row)
        if "raw_text" in copied:
            copied["raw_text"] = ""
        if "payload" in copied:
            try:
                payload = json.loads(copied["payload"])
            except Exception:
                payload = None
            if isinstance(payload, dict):
                payload["raw_draft"] = ""
                payload["transcript"] = None
                copied["payload"] = payload
        redacted.append(copied)
    return redacted
