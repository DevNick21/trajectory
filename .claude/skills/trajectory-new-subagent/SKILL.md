---
name: trajectory-new-subagent
description: Enforces the 7-step pattern for adding a new LLM-backed sub-agent to Trajectory. Triggers on phrases like "add a new agent", "new sub-agent", "phase 1 agent", "phase 4 generator", on new files under src/trajectory/sub_agents/, new *Output schemas in schemas.py, new entries in HIGH_STAKES_AGENTS / LOW_STAKES_AGENTS in validators/content_shield.py, or new entries in _AGENT_REGISTRY in scripts/audit_prompt.py. Do NOT use for renderers, validators, bot handlers, or for editing prompts of already-registered agents.
---

# Adding a sub-agent to Trajectory

Every sub-agent in `src/trajectory/sub_agents/` follows the same 7-step pattern. Skipping any step produces silent bugs in production. Follow every step. If a step does not apply, say so explicitly in your response — do not omit silently.

## Context before starting

Before writing any code, confirm:

1. **Which phase does the agent belong to?**
   - Phase 1 (research / extraction from scraped content) → Sonnet 4.6, medium effort
   - Phase 2 (verdict) → Opus 4.7, xhigh effort, priority=CRITICAL
   - Phase 3 (dialogue shaping) → Opus 4.7, xhigh effort
   - Phase 4 (generation — CV, cover letter, etc.) → Opus 4.7, xhigh effort
   - Shield Tier 2 (classifier) → Sonnet 4.6, medium effort
   - Onboarding per-stage parser → Sonnet 4.6, low effort
   - Other structured extraction with a tiny schema → Sonnet 4.6, low or medium effort

   **CLAUDE.md Rule 7: Opus 4.7 for quality-critical reasoning, Sonnet 4.6 for extraction and summarisation.** Do not use Opus for structured extraction from clean input — that is a drift failure mode that has happened before in this repo.

2. **Is the agent input trusted or untrusted?** List every input and label it:
   - TRUSTED: user_profile, style_profile, other validated agent outputs, gov data
   - UNTRUSTED: scraped pages, user messages, recruiter emails, writing samples, any third-party text

3. **Is the agent high-stakes or low-stakes downstream of the Content Shield?**
   - HIGH_STAKES: can steer user-facing decisions (verdict, salary_strategist, cv_tailor, cover_letter, likely_questions, draft_reply)
   - LOW_STAKES: extracts fields or classifies; output cannot meaningfully leak into a final document (intent_router, jd_extractor, company_scraper_summariser, red_flags_detector, onboarding_parser, style_extractor)

## The 7 steps

### Step 1 — Create the prompt file

Location: `src/trajectory/prompts/<agent_name>.md`

Structure (read `src/trajectory/prompts/verdict.md` for the canonical example):

1. One-line role statement ("You are the …")
2. Inputs list — what the agent receives
3. HARD RULES (numbered, first in order)
4. Soft guidance and citation discipline
5. OUTPUT: valid JSON matching <SchemaName>. No prose outside JSON.

For onboarding-stage prompts, use the shared header + common_rules composition pattern in `src/trajectory/sub_agents/onboarding_parser.py` — write only the stage-specific paragraph at `src/trajectory/prompts/onboarding/<stage>.md`.

### Step 2 — Add Pydantic schemas

Location: `src/trajectory/schemas.py`

- Output schema: the thing the agent produces. Must be named explicitly in the prompt's OUTPUT section.
- Any new enums (Literal types) the schema needs.
- If output has citations, every claim-carrying field must carry a `Citation`.

Run mental validation: does every field in the schema have either a `Citation` or a clear reason it does not need one (style hint, counter, timestamp)?

### Step 3 — Write the sub-agent module

Location: `src/trajectory/sub_agents/<agent_name>.py`

Use this skeleton:

```python
"""<Phase X> — <Agent Purpose>.

<One paragraph explaining what it does and why.>
System prompt: src/trajectory/prompts/<agent_name>.md
"""

from __future__ import annotations

from ..prompts import load_prompt
from typing import Optional

from ..config import settings
from ..llm import call_agent
from ..schemas import <OutputSchema>, <InputTypes>
from ..validators.banned_phrases import contains_banned  # if a generator
from ..validators.citations import ValidationContext, validate_output  # if citations

SYSTEM_PROMPT = load_prompt("<agent_name>")


def _post_validate(output: <OutputSchema>) -> list[str]:
    """Return a list of failure messages. Empty = accepted."""
    failures: list[str] = []
    # Add checks specific to this agent.
    # For generators: banned phrases, citation validation.
    # For validators that emit structured output: enum membership, ranges.
    return failures


async def generate(  # or `run`, `score`, `classify` — match the phase
    *,  # all kwargs
    <inputs>,
    session_id: Optional[str] = None,
) -> <OutputSchema>:
    # Build user_input as JSON or a small structured string.
    # Pass untrusted content through shield() before including.

    return await call_agent(
        agent_name="<agent_name>",           # NOTE: must match _AGENT_REGISTRY key
        system_prompt=SYSTEM_PROMPT,
        user_input=user_input,
        output_schema=<OutputSchema>,
        model=<settings.opus_model_id | settings.sonnet_model_id>,  # step 4!
        effort="<xhigh|medium|low>",                                  # step 4!
        session_id=session_id,
        post_validate=_post_validate,
    )
```

Rule 3 (writing style injection) check: if this is a Phase 4 generator, the user_input MUST include the full writing_style_profile with signature_patterns and avoided_patterns. Not just a tone hint string.

### Step 4 — Choose model and effort, document why

In the docstring OR in a code comment next to the `call_agent` kwargs, state which model you chose and why. This is a required audit trail. Example:

```python
# Model: Sonnet 4.6 low effort.
# Why: structured extraction from 7 pre-validated user replies. No
# reasoning required — the schema is tight and the task is per-field.
# Opus xhigh would 10x the cost for no measurable quality gain.
```

**Before defaulting to Opus xhigh, ask: does this agent actually need reasoning, or is it extraction?** If the answer is "extraction", use Sonnet. The Opus-everywhere default is a known drift failure in this repo.

Common correct choices:

| Task shape | Model | Effort |
|---|---|---|
| Verdict with citation chains, trade-off weighing | Opus 4.7 | xhigh |
| CV / cover letter / likely questions generation | Opus 4.7 | xhigh |
| Salary strategist — 4 scripts + urgency calibration | Opus 4.7 | xhigh |
| Ghost job JD scoring (5-dimension rating) | Opus 4.7 | xhigh |
| Red flags detector (cross-source synthesis) | Opus 4.7 | xhigh |
| JD extractor from scraped text | Sonnet 4.6 | medium |
| Company summariser from scraped pages | Sonnet 4.6 | medium |
| Content Shield Tier 2 classifier | Sonnet 4.6 | medium |
| Onboarding per-stage parser (single reply → structured) | Sonnet 4.6 | low |
| Intent router (short user message → label) | Opus 4.7 | xhigh (misroute cost is high) |
| Style extractor from writing samples | Opus 4.7 | xhigh |

### Step 5 — Register in Content Shield routing

File: `src/trajectory/validators/content_shield.py`

Add the agent name (the same string you used as `agent_name="…"` in step 3) to exactly ONE of:

- `HIGH_STAKES_AGENTS` — Tier 2 Sonnet classifier runs on flagged content
- `LOW_STAKES_AGENTS` — Tier 1 only, classifier skipped

Verify with the test in `tests/test_content_shield.py::test_high_and_low_stakes_sets_are_disjoint` that you haven't added the name to both.

Decision heuristic:
- Does this agent's output directly reach the user as a document, verdict, or recommendation? → HIGH_STAKES
- Does this agent's output feed another agent as one of many signals? → LOW_STAKES

### Step 6 — Register in the Prompt Auditor

File: `scripts/audit_prompt.py`

Add an entry to `_AGENT_REGISTRY`:

```python
"<agent_name>": {
    "module": "trajectory.sub_agents.<agent_name>",
    "system_prompt_attr": "SYSTEM_PROMPT",
    "output_schema_symbol": "<OutputSchemaClassName>",
    "input_sources": [
        "<input_name>: TRUSTED",
        "<input_name>: UNTRUSTED",
    ],
},
```

Label EVERY input as trusted or untrusted. Do not skip inputs. This is the dataset the Prompt Auditor uses to run injection stress tests — incomplete labelling means incomplete auditing.

Run `python scripts/audit_prompt.py <agent_name>` once manually and read the output. If the auditor returns "WEAK" or "UNSAFE", rewrite the prompt before shipping.

### Step 7 — Smoke test

File: `scripts/smoke_tests/<agent_name>.py`

Use one of these as a template:
- `scripts/smoke_tests/content_shield.py` — for classifiers with simple input/output
- `scripts/smoke_tests/onboarding_parser.py` — for per-stage extractors
- `scripts/smoke_tests/verdict.py` — for full-pipeline generators

Your smoke test MUST:

1. Call `prepare_environment()` and `require_anthropic_key()` at the top
2. Exercise at least one positive case (expected output shape)
3. Exercise at least one negative case (wrong-shape input, adversarial input, or missing field)
4. Estimate cost correctly based on the model you chose in step 4. If you chose Sonnet low at ~$0.02/call, do not set `ESTIMATED_COST_USD = 0.15` — that assumed Opus pricing
5. Register in `scripts/smoke_tests/run_all.py` `_REGISTRY` with the correct `cheap` flag

## Completion checklist

Before declaring done, verify all seven:

- [ ] Prompt file in `src/trajectory/prompts/<name>.md` exists and loads via `load_prompt`
- [ ] Schema in `schemas.py` — output schema named and Pydantic-valid
- [ ] Sub-agent module in `src/trajectory/sub_agents/<name>.py` with docstring, SYSTEM_PROMPT constant, typed entrypoint
- [ ] Model + effort choice documented with a comment explaining why
- [ ] Agent name in EXACTLY ONE of `HIGH_STAKES_AGENTS` / `LOW_STAKES_AGENTS` in `content_shield.py`
- [ ] Entry in `_AGENT_REGISTRY` in `scripts/audit_prompt.py` with trusted/untrusted labels on every input
- [ ] Smoke test in `scripts/smoke_tests/<name>.py` with realistic cost estimate, registered in `run_all.py`

If any step was skipped because it genuinely does not apply (e.g. a deterministic non-LLM agent skipping model choice), state which and why in your response to the user.

## Common drift patterns to avoid

These are real bugs that have happened in this repo. Do not repeat them.

1. **Opus low for structured extraction.** If the task is parsing one reply into a Pydantic schema, Sonnet low is correct. Opus low is ~10x cost for zero quality gain.

2. **Missing Content Shield registration.** An agent that does not appear in either HIGH_STAKES or LOW_STAKES still receives content from the shield, but the shield's `shield()` helper does not know how to route Tier 2. The agent works, but its shielding posture is implicit and fragile. Always register explicitly.

3. **Incomplete `input_sources` in `_AGENT_REGISTRY`.** If you list 3 inputs but the agent actually consumes 5, the Prompt Auditor's injection test can only reason about 3. You will pass audit and still ship a vulnerable agent.

4. **Smoke-test cost estimates from the wrong model.** `ESTIMATED_COST_USD` feeds into `run_all.py`'s budget total. Wrong estimates lie to future-you about how much a test run costs.

5. **Missing `session_id` threading.** Every agent call threads `session_id` through so cost logs attribute correctly. Agents without it log to `session_id=NULL` and skew the dashboard's per-session cost metrics.
