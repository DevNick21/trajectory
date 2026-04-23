"""Phase 4 — CV Tailor (agentic multi-turn retrieval path).

PROCESS.md Entry 36. Refactor of the legacy single-call path
(`cv_tailor_legacy.py`) into a multi-turn tool-use loop where Opus
iteratively searches FAISS for the career entries it needs as it drafts
the CV. Feature-flagged via `settings.enable_agentic_cv_tailor`;
default off until A/B validation confirms parity with legacy.

Two tools exposed to the agent:
  - `search_career_entries(query, kind_filter?, top_k?)` — semantic
    search via `storage.search_career_entries_semantic`. Results pass
    through Content Shield Tier 1 before being fed back to the model
    (career entries are user-supplied text — CLAUDE.md Rule 10).
  - `get_user_profile_field(field)` — single-field lookup against the
    `UserProfile` already loaded by the orchestrator. Trusted, no
    shielding.

Hallucination guard: every `career_entry` citation in the final
CVOutput must appear in `_retrieved_ids` (the executor tracks every
entry returned by any `search_career_entries` call). A cited but
un-retrieved entry raises `AgentCallFailed`; the dispatcher catches
and falls back to legacy.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from ..config import settings
from ..llm import AgentCallFailed, call_agent_with_tools
from ..prompts import load_prompt
from ..schemas import (
    CareerEntry,
    CVOutput,
    ExtractedJobDescription,
    ResearchBundle,
    STARPolish,
    UserProfile,
    WritingStyleProfile,
)
from ..storage import search_career_entries_semantic
from ..validators.banned_phrases import contains_banned
from ..validators.citations import ValidationContext, validate_output
from ..validators.content_shield import shield as shield_content

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = load_prompt("cv_tailor_agentic")

_CE_MARKER = re.compile(r"\[ce:([^\]]+)\]")

_MAX_TOTAL_RETRIEVED = 25
_MIN_SEARCH_CALLS = 3  # enforced post-hoc in the executor


# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------


_SEARCH_TOOL: dict[str, Any] = {
    "name": "search_career_entries",
    "description": (
        "Semantic search over the user's career history. Returns the most "
        "relevant CareerEntry objects for a query. Make multiple focused "
        "calls; don't try to get everything in one query."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "A specific capability, technology, or experience you're "
                    "looking for. Good: 'production Python observability'. "
                    "Bad: 'all my projects'."
                ),
            },
            "kind_filter": {
                "type": "string",
                "enum": [
                    "ANY",
                    "cv_bullet",
                    "qa_answer",
                    "star_polish",
                    "project_note",
                    "preference",
                    "motivation",
                    "deal_breaker",
                    "writing_sample",
                    "conversation",
                ],
                "description": (
                    "Restrict results to one CareerEntry.kind. Use ANY "
                    "unless you specifically need only project_notes or "
                    "only star_polishes, etc."
                ),
                "default": "ANY",
            },
            "top_k": {
                "type": "integer",
                "minimum": 1,
                "maximum": 10,
                "default": 5,
                "description": (
                    "Number of results. 3-5 for focused queries; up to 10 "
                    "for broad exploration. Total entries retrieved across "
                    "all calls is capped at 25."
                ),
            },
        },
        "required": ["query"],
    },
}

_PROFILE_FIELDS = (
    "name",
    "base_location",
    "visa_status",
    "salary_floor",
    "salary_target",
    "target_soc_codes",
    "linkedin_url",
    "github_url",
    "motivations",
    "deal_breakers",
    "good_role_signals",
    "current_employment",
)

_PROFILE_TOOL: dict[str, Any] = {
    "name": "get_user_profile_field",
    "description": (
        "Fetch a single field from the user's profile. Use for context "
        "not available in career entries."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "field": {
                "type": "string",
                "enum": list(_PROFILE_FIELDS),
            }
        },
        "required": ["field"],
    },
}


# ---------------------------------------------------------------------------
# Tool executor
# ---------------------------------------------------------------------------


class CVTailorToolExecutor:
    """Runs the agent's tool calls; tracks retrieved entry IDs for the
    post-hoc hallucination check."""

    def __init__(self, profile: UserProfile, session_id: Optional[str]):
        self._profile = profile
        self._session_id = session_id
        self._retrieved_ids: set[str] = set()
        self._search_call_count = 0
        self._profile_call_count = 0

    @property
    def retrieved_ids(self) -> set[str]:
        return self._retrieved_ids

    @property
    def search_call_count(self) -> int:
        return self._search_call_count

    async def execute(self, tool_name: str, tool_input: dict) -> str:
        if tool_name == "search_career_entries":
            return await self._search(tool_input)
        if tool_name == "get_user_profile_field":
            return await self._profile_field(tool_input)
        return json.dumps({"error": f"unknown tool: {tool_name}"})

    async def _search(self, tool_input: dict) -> str:
        query = (tool_input.get("query") or "").strip()
        if not query:
            return json.dumps({"error": "query is required"})
        kind_filter = tool_input.get("kind_filter", "ANY") or "ANY"
        top_k = int(tool_input.get("top_k", 5) or 5)

        # Cap retrieval after we've already pulled the per-session max.
        remaining = _MAX_TOTAL_RETRIEVED - len(self._retrieved_ids)
        if remaining <= 0:
            return json.dumps({
                "error": (
                    f"retrieval budget exhausted ({_MAX_TOTAL_RETRIEVED} "
                    "entries). Use what you already have."
                ),
                "results": [],
            })
        top_k = min(top_k, remaining)

        entries: list[CareerEntry] = await search_career_entries_semantic(
            user_id=self._profile.user_id,
            query=query,
            kind_filter=kind_filter,
            top_k=top_k,
        )
        self._search_call_count += 1
        self._retrieved_ids.update(e.entry_id for e in entries)

        # CLAUDE.md Rule 10: career entries are user-supplied text. Tier
        # 1 only — agentic CV tailor's downstream output schema (CVOutput)
        # is structured enough that residual injection cannot leak free-
        # form text into a generator.
        results = []
        for e in entries:
            cleaned, _ = await shield_content(
                content=e.raw_text[:1500],
                source_type="user_message",
                downstream_agent="cv_tailor",
            )
            results.append({
                "entry_id": e.entry_id,
                "kind": e.kind,
                "raw_text": cleaned,
            })
        return json.dumps({"results": results})

    async def _profile_field(self, tool_input: dict) -> str:
        field = tool_input.get("field")
        if field not in _PROFILE_FIELDS:
            return json.dumps({"error": f"unknown field: {field}"})
        value = getattr(self._profile, field, None)
        if hasattr(value, "model_dump"):
            value = value.model_dump()
        self._profile_call_count += 1
        return json.dumps({"field": field, "value": value}, default=str)


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------


async def generate(
    jd: ExtractedJobDescription,
    research_bundle: ResearchBundle,
    user: UserProfile,
    retrieved_entries: list[CareerEntry],  # ignored — agentic path retrieves on demand
    style_profile: WritingStyleProfile,
    star_material: Optional[list[STARPolish]] = None,
    citation_ctx: Optional[ValidationContext] = None,
) -> CVOutput:
    """Same signature as `cv_tailor_legacy.generate` for dispatcher
    drop-in. `retrieved_entries` is accepted but unused — the agent
    pulls career entries on demand via the search tool."""
    executor = CVTailorToolExecutor(user, session_id=None)

    user_input = _build_user_input(jd, research_bundle, style_profile, star_material)

    cv = await call_agent_with_tools(
        agent_name="cv_tailor_agentic",
        system_prompt=SYSTEM_PROMPT,
        user_input=user_input,
        tools=[_SEARCH_TOOL, _PROFILE_TOOL],
        tool_executor=executor.execute,
        response_schema=CVOutput,
        model=settings.opus_model_id,
        effort="xhigh",
        max_iterations=10,
    )

    # Post-hoc minimum-searches enforcement. Falls back to legacy.
    if executor.search_call_count < _MIN_SEARCH_CALLS:
        raise AgentCallFailed(
            f"cv_tailor_agentic emitted final CV after only "
            f"{executor.search_call_count} search call(s); minimum is "
            f"{_MIN_SEARCH_CALLS}."
        )

    # Post-hoc hallucination + banned-phrase + citation validation.
    failures = _post_validate(cv, executor.retrieved_ids, citation_ctx)
    if failures:
        raise AgentCallFailed(
            "cv_tailor_agentic post-validation failed: " + "; ".join(failures)
        )

    return cv


def _build_user_input(
    jd: ExtractedJobDescription,
    research_bundle: ResearchBundle,
    style_profile: WritingStyleProfile,
    star_material: Optional[list[STARPolish]],
) -> str:
    style_hint = (
        f"tone={style_profile.tone}, "
        f"formality={style_profile.formality_level}/10, "
        f"hedging={style_profile.hedging_tendency}"
    )
    if style_profile.sample_count < 3:
        style_hint += " (low confidence — directional only)"

    polishes_summary: list[dict] = []
    if star_material:
        for p in star_material:
            polishes_summary.append({
                "question": p.question,
                "situation": p.situation.text,
                "task": p.task.text,
                "action": p.action.text,
                "result": p.result.text,
            })

    payload = {
        "jd": {
            "role_title": jd.role_title,
            "seniority": jd.seniority_signal,
            "required_skills": jd.required_skills,
            "specificity_signals": jd.specificity_signals[:5],
            "remote_policy": jd.remote_policy,
            "location": jd.location,
        },
        "company": research_bundle.company_research.company_name,
        "company_culture_claims": [
            c.claim for c in research_bundle.company_research.culture_claims[:5]
        ],
        "writing_style": {
            "hint": style_hint,
            "signature_patterns": style_profile.signature_patterns[:5],
            "avoided_patterns": style_profile.avoided_patterns[:5],
            "examples": style_profile.examples[:3],
        },
        "star_polishes": polishes_summary,
        "instructions": (
            "Career entries are NOT provided in this message. You must "
            "retrieve them via the `search_career_entries` tool, calling "
            "at least 3 times before emitting the final CV. Also call "
            "`get_user_profile_field('name')` before emitting."
        ),
    }
    return json.dumps(payload, default=str)


def _post_validate(
    cv: CVOutput,
    retrieved_ids: set[str],
    citation_ctx: Optional[ValidationContext],
) -> list[str]:
    failures: list[str] = []

    # Hallucination check — every cited entry must have been retrieved.
    cited_ids: set[str] = set()
    for role in cv.experience:
        for bullet in role.bullets:
            for marker in _CE_MARKER.findall(bullet.text):
                cited_ids.add(marker)
            for c in bullet.citations:
                if c.kind == "career_entry" and c.entry_id:
                    cited_ids.add(c.entry_id)
    hallucinated = cited_ids - retrieved_ids
    if hallucinated:
        failures.append(
            "career_entry citations not in retrieved set: "
            + ", ".join(sorted(hallucinated))
        )

    # Banned phrases — same check as the legacy post-validator.
    all_text_parts = [cv.professional_summary]
    for role in cv.experience:
        for b in role.bullets:
            all_text_parts.append(b.text)
    all_text = " ".join(all_text_parts)
    clean = _CE_MARKER.sub("", all_text)
    for phrase in contains_banned(clean):
        failures.append(f"Banned phrase in CV: '{phrase}'")

    # Standard citation validator if context was provided.
    if citation_ctx is not None:
        failures.extend(validate_output(cv, citation_ctx))

    return failures
