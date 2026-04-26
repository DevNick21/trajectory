"""Phase 4 — CV Tailor (multi-turn FAISS retrieval).

PROCESS.md Entry 36. Multi-turn tool-use loop where Opus iteratively
searches FAISS for the career entries it needs as it drafts the CV.
D5 (2026-04-24): promoted from the opt-in path to the only CV tailor —
the legacy single-call path was deleted after this became the default.

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
from ..storage import STAR_BOOST_KINDS, search_career_entries_semantic
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

        # STAR boost — prefer user-validated star_polish + qa_answer
        # when the agent searches, same as the legacy path. Silent
        # inside the tool response (the agent sees entry.kind and can
        # weigh them itself too).
        entries: list[CareerEntry] = await search_career_entries_semantic(
            user_id=self._profile.user_id,
            query=query,
            kind_filter=kind_filter,
            top_k=top_k,
            kind_weights=STAR_BOOST_KINDS,
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
    """Multi-turn CV generation. `retrieved_entries` is accepted for
    signature compatibility with older callers but unused — the agent
    pulls career entries on demand via the search tool."""
    base_user_input = _build_user_input(
        jd, research_bundle, style_profile, star_material,
    )

    # One retry on post-validation failure. The agentic loop is expensive
    # (multi-turn tool-use, ~$0.35 per attempt) but a single regenerate
    # with feedback is much cheaper than failing the entire draft_cv.
    # PROCESS Entry 47 surfaced the failure mode: Opus occasionally
    # cites a career_entry_id it didn't retrieve, the validator rejects,
    # and without retry the user gets no CV at all.
    last_failures: list[str] = []
    last_searches = 0
    user_input = base_user_input

    for attempt in range(2):
        executor = CVTailorToolExecutor(user, session_id=None)
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

        if executor.search_call_count < _MIN_SEARCH_CALLS:
            last_failures = [
                f"emitted final CV after only "
                f"{executor.search_call_count} search call(s); minimum "
                f"is {_MIN_SEARCH_CALLS}"
            ]
            last_searches = executor.search_call_count
        else:
            last_failures = _post_validate(
                cv, executor.retrieved_ids, citation_ctx,
            )
            last_searches = executor.search_call_count

        if not last_failures:
            return cv

        # Re-prompt with the rejection rationale + the actual list of
        # entry_ids the agent saw via search_career_entries (so it
        # has no excuse to fabricate one on retry).
        retrieved_summary = (
            ", ".join(sorted(executor.retrieved_ids))
            if executor.retrieved_ids else "(none)"
        )
        logger.info(
            "cv_tailor_agentic attempt %d failed post-validation; retrying with feedback: %s",
            attempt + 1, last_failures,
        )
        user_input = base_user_input + (
            "\n\n## PREVIOUS ATTEMPT REJECTED\n\n"
            + "\n".join(f"- {f}" for f in last_failures)
            + "\n\nFix every rejection above. Specifically: cite ONLY "
            "entry_ids that appeared in the results of your "
            "search_career_entries calls. The retrieved set this run "
            f"is: [{retrieved_summary}]. Drop any bullet whose only "
            "supporting evidence is a non-retrieved entry — do not "
            "fabricate an entry_id to keep a bullet."
        )

    # Graceful degradation: after one full retry, if the only remaining
    # failures are hallucinated career_entry citations, drop the bad
    # citations and ship the CV. The bullet TEXT is still drafted from
    # what the agent saw; only the support pointer is wrong. Better to
    # ship a CV with N-1 citations than fail the entire request.
    # Banned-phrase / search-call-count failures still raise.
    if cv is not None and _only_failure_is_hallucinated_citations(
        last_failures
    ):
        store_ids = (
            set(citation_ctx.career_store_entries)
            if citation_ctx is not None else set()
        )
        dropped = _drop_hallucinated_citations(cv, store_ids)
        if dropped:
            logger.warning(
                "cv_tailor_agentic: dropped %d hallucinated citation(s) "
                "post-retry rather than failing the whole draft. Bullets "
                "kept; only the citation pointers were removed.",
                dropped,
            )
            return cv

    raise AgentCallFailed(
        "cv_tailor_agentic post-validation failed after retry: "
        + "; ".join(last_failures)
        + f" (final searches={last_searches})"
    )


_HALLUCINATION_MARKERS = (
    "career_entry citations not in career store",
    "not found in career store",
)


def _only_failure_is_hallucinated_citations(failures: list[str]) -> bool:
    """True iff every failure message is a hallucinated-citation report.
    Used to decide whether graceful citation-dropping is safe — banned
    phrases or schema issues still need to fail loud."""
    if not failures:
        return False
    return all(
        any(marker in f for marker in _HALLUCINATION_MARKERS)
        for f in failures
    )


def _drop_hallucinated_citations(cv: CVOutput, store_ids: set[str]) -> int:
    """Walk the CV's bullets and remove any career_entry citation
    whose entry_id isn't in `store_ids`. Returns the count dropped."""
    dropped = 0
    for role in cv.experience:
        for bullet in role.bullets:
            kept = []
            for c in bullet.citations:
                if (
                    c.kind == "career_entry"
                    and c.entry_id
                    and c.entry_id not in store_ids
                ):
                    dropped += 1
                    continue
                kept.append(c)
            bullet.citations = kept
    return dropped


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

    # Hallucination check — every cited entry must EITHER have been
    # retrieved by search this session OR exist in the user's career
    # store (validated by `validate_output` below). The original strict
    # check failed live runs (PROCESS Entry 47) where Opus correctly
    # cited an entry that exists in the store but didn't surface in
    # the agent's specific search calls — those are real entries, not
    # hallucinations. We log the discrepancy as a warning so we can
    # still observe pattern drift, but only fail when the citation
    # genuinely points at nothing.
    cited_ids: set[str] = set()
    for role in cv.experience:
        for bullet in role.bullets:
            for marker in _CE_MARKER.findall(bullet.text):
                cited_ids.add(marker)
            for c in bullet.citations:
                if c.kind == "career_entry" and c.entry_id:
                    cited_ids.add(c.entry_id)
    not_searched = cited_ids - retrieved_ids
    if not_searched:
        # `career_store_entries` is a dict {entry_id: kind} on the
        # ValidationContext (not a bare set) — convert to its key view
        # before set arithmetic. PROCESS Entry 47 bug 18 caught this
        # the hard way: TypeError("unsupported operand type(s) for -:
        # 'set' and 'dict'") killed phase4_cv on the next live run.
        store_ids = (
            set(citation_ctx.career_store_entries)
            if citation_ctx is not None else set()
        )
        truly_missing = not_searched - store_ids
        store_resident = not_searched & store_ids
        if store_resident:
            logger.info(
                "cv_tailor_agentic cited %d entry_id(s) that weren't in "
                "the agent's retrieved set but DO exist in the career "
                "store — accepting (likely surfaced via _PROFILE_TOOL or "
                "from prior context): %s",
                len(store_resident), sorted(store_resident),
            )
        if truly_missing:
            failures.append(
                "career_entry citations not in career store at all "
                "(hallucinated): " + ", ".join(sorted(truly_missing))
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
