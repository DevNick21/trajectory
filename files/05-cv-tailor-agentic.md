# Claude Code prompt — CV tailor: agentic retrieval refactor

> Paste this entire file to Claude Code as the task brief. Read fully before writing code.
>
> **Scope:** refactor the CV tailor from a single-turn "stuff everything into the prompt" call into a multi-turn tool-use loop where the agent retrieves career entries via FAISS semantic search as it writes. Feature-flagged. Legacy path stays as fallback.
>
> **When to run:** post-submission. This touches the crown jewel — CV generation. Production quality degradation on this path is the worst possible demo failure. Shipping requires side-by-side A/B validation on at least five real CV drafts before flipping the default.

---

## Why this exists

The current `cv_tailor` agent receives the entire career_entries corpus in its user_input, regardless of which entries are relevant to the target role. Problems:

1. **Context window pressure.** A candidate with 40 projects and 15 years of experience produces a 40k-token user_input. Opus handles it, but the agent's attention is diluted — less relevant entries still appear in the input.
2. **No explicit relevance reasoning.** The agent has to decide "this React project is relevant to the Fullstack role" implicitly. It can't say "show me projects tagged with React." It has to scan everything linearly.
3. **No iterative refinement.** If the agent realises mid-draft that it needs a Python infrastructure example to balance a bullet list, it can't go find one — it has to work with what's already in the prompt.

Tool-use with FAISS addresses all three: the agent calls `search_career_entries(query="React production deployment")` and gets the top-k semantically matched entries. The agent decides what to look for, based on the JD it's reading. This is the textbook use case for agentic retrieval.

## Reading you must do first

1. `src/trajectory/sub_agents/cv_tailor.py` — the full current implementation. Note the input shape, output shape, prompt structure.
2. `src/trajectory/prompts/cv_tailor.md` — the system prompt.
3. `src/trajectory/storage.py` — specifically the FAISS index construction and any existing `search_career_entries` functions. If none exists, you'll add one.
4. `src/trajectory/schemas.py::CVOutput`, `CareerEntry`, `ExtractedJobDescription`.
5. `src/trajectory/llm.py::call_agent` — you'll need a parallel function for multi-turn tool use.
6. `CLAUDE.md` — Rules 7, 10, 11.
7. `PROCESS.md` — numbering.
8. Anthropic tool-use docs — fetch `https://docs.claude.com/en/docs/build-with-claude/tool-use` before coding.

## Architecture

### High-level flow

**Current (legacy):**
```
CareerEntry[] (all) + ExtractedJobDescription + style_profile
  ↓ single call_agent → Opus xhigh → CVOutput
```

**New (agentic):**
```
ExtractedJobDescription + style_profile  (no career entries up-front)
  ↓ multi-turn loop:
     agent → tool_use(search_career_entries, query=...)
          → tool_result(top-k matching entries)
     agent → tool_use(search_career_entries, query=...)
          → tool_result(top-k matching entries)
     (up to N iterations)
     agent → final CVOutput
```

### FAISS semantic search tool

Tool schema exposed to the agent:

```json
{
  "name": "search_career_entries",
  "description": "Semantic search over the user's career history. Returns the most relevant CareerEntry objects for a query. Use this to find experience that matches specific JD requirements. Make multiple focused calls; don't try to get everything in one query.",
  "input_schema": {
    "type": "object",
    "properties": {
      "query": {
        "type": "string",
        "description": "A specific capability, technology, or experience you're looking for. Good examples: 'production Python system with observability', 'React component library', 'regulated industry compliance'. Bad examples: 'all my projects', 'relevant experience' (too vague)."
      },
      "kind_filter": {
        "type": "string",
        "enum": ["ANY", "PROJECT", "ROLE", "EDUCATION", "CERTIFICATION"],
        "description": "Restrict results to one kind of entry. Use ANY unless you specifically need only projects or only roles.",
        "default": "ANY"
      },
      "top_k": {
        "type": "integer",
        "description": "Number of results to return. Use 3-5 for focused queries, up to 10 for broad exploration. Keep totals across all tool calls under 25 to avoid context bloat.",
        "default": 5,
        "minimum": 1,
        "maximum": 10
      }
    },
    "required": ["query"]
  }
}
```

Implementation: `storage.search_career_entries_semantic(query, kind_filter, top_k)` — thin wrapper over the existing FAISS index. If the wrapper doesn't exist, write it. It should return a `list[CareerEntry]` sorted by score descending.

### Secondary tool: `get_user_profile_field`

The agent sometimes needs profile context that isn't a career entry (e.g. preferred location, visa status, compensation expectation). Instead of pre-stuffing profile into the prompt, expose:

```json
{
  "name": "get_user_profile_field",
  "description": "Fetch a single field from the user's profile. Use for context not available in career entries.",
  "input_schema": {
    "type": "object",
    "properties": {
      "field": {
        "type": "string",
        "enum": [
          "name",
          "location_preference",
          "visa_status",
          "target_compensation_min",
          "target_compensation_max",
          "target_roles",
          "avoid_companies",
          "avoid_industries"
        ]
      }
    },
    "required": ["field"]
  }
}
```

Implementation: lookup against the stored `UserProfile` object passed into the CV tailor invocation.

### System prompt updates

Rewrite `cv_tailor.md` to:

1. Open with "You have two tools: `search_career_entries` and `get_user_profile_field`. Use them to build the CV. Do NOT assume the career entries you need are already in your context — they're not. Start by searching."
2. Require minimum 3 `search_career_entries` calls before emitting the final CVOutput. (Enforced prompt-side; the loop should also count and reject early submission.)
3. Require at least one `get_user_profile_field` call for `name` before emitting the CV. Absent name handling still goes through the empty-string-fallback path from Fix 1 in prompt 01, but the agent must have tried.
4. Cap total tool calls at 8 to prevent runaway cost. Exceeding this triggers forced emission.
5. Preserve all existing content rules from the current `cv_tailor.md`: bullet style, STAR framing, business-outcome framing, no invented metrics, citation to career_entry_id.
6. After the final CVOutput is produced, a post-check verifies every cited `career_entry_id` was returned by one of the agent's tool calls. If an entry was cited but never retrieved, that's a hallucination and the draft fails validation.

### Multi-turn call wrapper

Add to `llm.py`:

```python
async def call_agent_with_tools(
    *,
    system_prompt: str,
    user_input: str,
    tools: list[dict],
    tool_executor: Callable[[str, dict], Awaitable[Any]],  # (tool_name, tool_input) → result
    response_schema: type[BaseModel],
    model: str,
    effort: Literal["low", "medium", "high", "xhigh"],
    session_id: Optional[str] = None,
    max_iterations: int = 10,
    agent_name: str,
) -> BaseModel:
    """Run a multi-turn tool-use loop. Returns the final parsed response.

    Raises:
        RuntimeError: if max_iterations exceeded without final response.
        ValidationError: if final response doesn't validate against schema.
    """
    ...
```

Key aspects:

- Builds messages list across turns.
- On each turn, sends the message list + tools to the API.
- If response is `tool_use`, execute the tool via `tool_executor`, append tool_use + tool_result to message list, continue.
- If response is a final message with structured JSON matching `response_schema`, validate and return.
- Token usage accumulated across turns, logged once at end.
- Content Shield is applied to `tool_executor` outputs before they're fed back into the model. This is the new place shield integration matters — tool results are untrusted-ish, especially `search_career_entries` outputs (user-supplied text).

### Tool executor

```python
class CVTailorToolExecutor:
    def __init__(self, profile: UserProfile, session_id: str):
        self._profile = profile
        self._session_id = session_id
        self._retrieved_ids: set[str] = set()  # track for post-hoc hallucination check

    async def execute(self, tool_name: str, tool_input: dict) -> str:
        if tool_name == "search_career_entries":
            entries = await storage.search_career_entries_semantic(
                user_id=self._profile.user_id,
                query=tool_input["query"],
                kind_filter=tool_input.get("kind_filter", "ANY"),
                top_k=tool_input.get("top_k", 5),
            )
            self._retrieved_ids.update(e.id for e in entries)
            return json.dumps([e.model_dump() for e in entries], default=str)

        if tool_name == "get_user_profile_field":
            field = tool_input["field"]
            value = getattr(self._profile, field, None)
            return json.dumps({"field": field, "value": value}, default=str)

        raise ValueError(f"unknown tool: {tool_name}")
```

### Fallback wrapper

```python
async def tailor_cv_with_fallback(
    *,
    jd: ExtractedJobDescription,
    profile: UserProfile,
    style_profile: Optional[StyleProfile],
    session_id: str,
) -> CVOutput:
    """Try the agentic path. Fall back to legacy on failure."""
    if settings.enable_agentic_cv_tailor:
        try:
            return await cv_tailor_agentic.run(
                jd=jd,
                profile=profile,
                style_profile=style_profile,
                session_id=session_id,
            )
        except (RuntimeError, ValidationError) as exc:
            logger.warning("agentic CV tailor failed, falling back: %s", exc)

    return await cv_tailor_legacy.run(
        jd=jd,
        profile=profile,
        style_profile=style_profile,
        session_id=session_id,
    )
```

Rename the current `cv_tailor.py` → `cv_tailor_legacy.py` (and update imports). The new agentic path is `cv_tailor_agentic.py`. Both expose a `run` function with the same signature.

### Feature flag

Add to `config.py`:

```python
enable_agentic_cv_tailor: bool = False
```

Default false. Production path is legacy. Agentic path opt-in via env var.

## Hard constraints

1. **Legacy path unchanged.** Don't refactor `cv_tailor_legacy.py`. Rename + leave alone. Flipping the flag produces the old behaviour byte-identically.
2. **Min 3 search calls.** Enforced both in the prompt and in the loop. If the agent tries to emit CVOutput after < 3 searches, reject and continue the loop with a "you must search first" system message.
3. **Max 8 tool calls total.** After the 8th call, the next turn is forced to produce CVOutput (system message nudges this).
4. **Max 10 iterations.** Ceiling on total loop turns including tool calls + final. Exceeding raises and falls back to legacy.
5. **Citation hallucination check.** Every `career_entry_id` in the final CVOutput's bullets must appear in `tool_executor._retrieved_ids`. Any citation to an un-retrieved entry → `ValidationError`, fallback triggers.
6. **Shield tool results.** `search_career_entries` results go through `shield()` before being returned to the model. `get_user_profile_field` doesn't (profile is first-party data).
7. **Token budget.** Log cumulative tokens across all turns. Target: median session under 35k input + 5k output. If you see the median trending over 50k input, the loop is too exploratory — tighten the prompt.
8. **Don't break the audit script.** `scripts/audit_prompt.py::_AGENT_REGISTRY` expects one entry per agent module. Register `"cv_tailor_agentic"` as a new entry; leave `"cv_tailor"` pointing at the legacy module.

## Implementation plan

### Step 1 — Docs brief

Fetch `https://docs.claude.com/en/docs/build-with-claude/tool-use` and confirm:

- Exact shape of `tool_use` response blocks and `tool_result` content blocks.
- How to append tool_use + tool_result to the message list between turns.
- Whether `thinking={"type": "adaptive"}` interacts with tool use (relevant because CV tailor uses Opus xhigh).
- Whether `tool_choice={"type": "auto"}` is the right setting for this use case or whether we should force tool use on turn 1.

Write the brief to the user; wait for review.

### Step 2 — Storage layer

Verify `storage.search_career_entries_semantic` exists. If not, write it as a thin wrapper over the existing FAISS index. Test: feed 10 career entries into storage, query with 3 different strings, assert reasonable ranking.

### Step 3 — Rename legacy

Move `cv_tailor.py` → `cv_tailor_legacy.py`. Update:
- Any imports.
- `_AGENT_REGISTRY` entry.
- Smoke test imports.
- Ensure `pytest` still passes with the rename alone.

### Step 4 — Multi-turn wrapper

Write `call_agent_with_tools` in `llm.py`. Unit-test with a mocked SDK: simulate a 4-turn conversation with 3 tool calls + final response.

### Step 5 — Tool executor

Write `CVTailorToolExecutor`. Unit-test the two tools in isolation with a synthetic `UserProfile` and a synthetic FAISS-backed `search_career_entries_semantic` (also mocked).

### Step 6 — Agent module

Write `cv_tailor_agentic.py`:

```python
async def run(
    *,
    jd: ExtractedJobDescription,
    profile: UserProfile,
    style_profile: Optional[StyleProfile],
    session_id: str,
) -> CVOutput:
    ...
```

- Build the tools list from the two JSON schemas.
- Instantiate `CVTailorToolExecutor(profile, session_id)`.
- Build `user_input` containing: JD (shielded), style_profile (raw, first-party), and explicit instructions to start by searching.
- Call `call_agent_with_tools(...)` with model=`settings.opus_model_id`, effort=`"xhigh"`, thinking=`"adaptive"`, tool_choice=`"auto"`, response_schema=`CVOutput`.
- Post-hoc hallucination check: iterate CVOutput bullets, verify every `career_entry_id` in `executor._retrieved_ids`. Raise `ValidationError` on mismatch.

### Step 7 — Prompt rewrite

Rewrite `cv_tailor.md`. Rename to `cv_tailor_agentic.md` for clarity; keep `cv_tailor_legacy.md` as the copy of the old prompt.

### Step 8 — Wrapper

Write `tailor_cv_with_fallback` in `sub_agents/cv_tailor.py` (now a dispatcher). Update `orchestrator.handle_draft_cv` to call the wrapper, not the agent directly.

### Step 9 — Tests

**`tests/test_call_agent_with_tools.py`** — mocked SDK end-to-end.

**`tests/test_cv_tailor_agentic.py`** — mocked executor:

- 4-turn happy path: 3 searches + 1 profile lookup + final → returns valid CVOutput.
- Early submission (< 3 searches) → loop continues, eventually hits max_iterations, raises.
- 9 tool calls → forced emission on turn 10.
- Citation to un-retrieved entry → ValidationError.
- Max iterations exceeded → RuntimeError.

**`tests/test_cv_tailor_fallback.py`**:

- Flag off → legacy runs, agentic not touched.
- Flag on, agentic succeeds → returns agentic output.
- Flag on, agentic raises → legacy runs, returns legacy output.

### Step 10 — Smoke test

`scripts/smoke_tests/cv_tailor_agentic.py` — real API:

- Feed a realistic JD and a corpus of 20 synthetic career entries.
- `ESTIMATED_COST_USD = 0.35` (Opus xhigh, ~40k input + 4k output across turns).
- Gate behind `SMOKE_AGENTIC_CV=1`.
- Assert valid CVOutput with citations that all resolve.

### Step 11 — A/B test script

Write `scripts/ab_cv_tailors.py`:

- Takes a JD URL and a corpus as input.
- Runs both paths. Produces side-by-side PDF outputs.
- Measures: tokens used, latency, citation count, hallucination rate (post-hoc check).

Document in the PROCESS.md entry how to interpret the outputs — the goal is to validate the agentic path matches or beats legacy on quality before flipping the default.

### Step 12 — PROCESS.md entry

Append:

**Entry N — CV tailor: agentic retrieval refactor.**

Document:
- Trigger: the legacy path stuffs the entire career_entries corpus into a single call. On users with 20+ entries, this dilutes attention and burns context. No ability for the agent to say "I need a Python infrastructure example" mid-draft.
- Decision: add an agentic path where cv_tailor uses FAISS semantic search as a tool, iteratively pulling relevant entries based on the JD. Feature-flagged, opt-in, legacy as fallback.
- Architecture: `call_agent_with_tools` multi-turn wrapper; two tools (`search_career_entries`, `get_user_profile_field`); Content Shield on search results; min 3 / max 8 tool calls; post-hoc hallucination check on citations; max 10 total turns.
- Why opt-in: CV quality is the crown jewel. Production traffic stays on the battle-tested legacy path until A/B validation on ≥5 real CV drafts confirms quality parity or improvement.
- Forward-looking: track per-JD token delta vs legacy; if agentic materially reduces cost and matches quality, flip default.

## Acceptance criteria

- [ ] Docs-reading brief (Step 1) produced and reviewed.
- [ ] `cv_tailor.py` → `cv_tailor_legacy.py` rename; all imports updated; tests pass on rename alone.
- [ ] `storage.search_career_entries_semantic` exists and is tested.
- [ ] `call_agent_with_tools` in `llm.py` with full unit test coverage.
- [ ] `CVTailorToolExecutor` with `_retrieved_ids` tracking.
- [ ] `cv_tailor_agentic.py` + `cv_tailor_agentic.md` exist.
- [ ] `tailor_cv_with_fallback` dispatcher in `sub_agents/cv_tailor.py`; orchestrator updated.
- [ ] Feature flag `enable_agentic_cv_tailor` defaults False.
- [ ] All unit tests green.
- [ ] Smoke test exists behind `SMOKE_AGENTIC_CV=1` gate.
- [ ] A/B script exists and has been run at least once against a synthetic corpus.
- [ ] `audit_prompt.py::_AGENT_REGISTRY` has entries for both `cv_tailor_legacy` (trusted upstream: profile, JD) and `cv_tailor_agentic` (trusted upstream: profile, JD, FAISS results).
- [ ] `PROCESS.md` has the new entry.
- [ ] `pytest tests/` all green. `ruff check` no new warnings.

## What NOT to do

- Do not delete the legacy path.
- Do not flip `enable_agentic_cv_tailor` default to True in this task.
- Do not skip the A/B script.
- Do not remove the post-hoc citation hallucination check.
- Do not expand the tool set beyond the two specified.
- Do not let the agent retrieve more than 25 entries total across all tool calls in one session (enforce at executor level).
- Do not swallow errors from the agentic path silently in production logs — log them at WARNING so anyone reviewing can see the fallback rate.

## If you're unsure

Stop. Ask. This path replaces the most user-facing, highest-stakes agent in Trajectory. Getting it wrong is visible.
