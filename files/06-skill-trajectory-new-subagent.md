# Claude Code prompt — install the `trajectory-new-subagent` skill

> Paste this entire file to Claude Code as the task brief. Read fully before writing code.
>
> **Scope:** install a Claude Code skill that enforces the 7-step pattern for adding new sub-agents to Trajectory. Small task — file copy, frontmatter check, trigger validation. Post-submission.
>
> **When to run:** any time post-submission. The content has been drafted. This is the installation + integration task.

---

## Why this exists

Every sub-agent in Trajectory follows the same 7-step pattern, and every time one is added (onboarding_parser being the most recent), something gets missed on the first pass. Common misses from live review:

- Prompt exists but model/effort not documented in-code (was Opus low for onboarding_parser; should have been Sonnet from the start).
- Sub-agent written but not registered in `HIGH_STAKES_AGENTS` or `LOW_STAKES_AGENTS` in `content_shield.py` — so shield returns without running.
- Smoke test written but not added to `run_all.py`, so it doesn't run in CI.
- `_AGENT_REGISTRY` in `scripts/audit_prompt.py` missed, so the static audit skips the new prompt.

A Claude Code skill enforces the pattern. When Claude Code encounters "add a new sub-agent", "create a phase N agent", or edits in `src/trajectory/sub_agents/`, it loads the skill and walks the 7 steps explicitly.

## Reading you must do first

1. The draft skill content at `/mnt/user-data/outputs/SKILL.md` if still present in the user's workspace. If not, recreate from the 7-step pattern documented below.
2. `CLAUDE.md` — Rule 7 (correct tier per agent), Rule 11 (new-agent discipline).
3. Any existing `.claude/skills/` directory structure in the repo. If the directory doesn't exist, you'll create it.
4. `PROCESS.md` — numbering for the new entry.
5. Anthropic Claude Code skills docs — `https://docs.claude.com/en/docs/claude-code/skills` if accessible, otherwise the user's existing skill examples if any are installed.

## The 7-step pattern

This is the pattern the skill enforces. Every new sub-agent in Trajectory must complete all seven:

1. **Prompt file.** Markdown in `src/trajectory/prompts/<agent_name>.md`. Top comment block documenting: agent purpose, untrusted inputs, trusted inputs, model+effort choice, output schema.
2. **Schema.** Pydantic model in `src/trajectory/schemas.py`. Output shape. Named `<AgentName>Output` or similar.
3. **Sub-agent module.** `src/trajectory/sub_agents/<agent_name>.py`. Exposes `async def run(...) -> <AgentName>Output`. Internal `_call_<agent_name>` wraps `call_agent` with the chosen model+effort.
4. **Model + effort choice documented.** Inside the module docstring, one-sentence rationale per CLAUDE.md Rule 7: why Sonnet vs Opus, why that effort level. Cross-reference the effort rubric in CLAUDE.md.
5. **Content Shield registration.** In `src/trajectory/validators/content_shield.py`, add agent name to either `HIGH_STAKES_AGENTS` or `LOW_STAKES_AGENTS`. HIGH_STAKES = output feeds verdict or gets rendered; LOW_STAKES = output is intermediate or cached.
6. **Audit script registration.** In `scripts/audit_prompt.py::_AGENT_REGISTRY`, add an entry with:
   - `agent_name`
   - `prompt_path` (relative to repo root)
   - `trusted_upstream_agents` (list of agent names whose output this agent consumes)
   - `untrusted_inputs` (list of scraper/user-input sources that reach this agent)
7. **Smoke test.** `scripts/smoke_tests/<agent_name>.py` with:
   - `ESTIMATED_COST_USD` constant (honest estimate, Sonnet ~$0.02, Opus low ~$0.15, Opus xhigh ~$0.50+).
   - Single real-API round trip.
   - At least one assertion on the output shape.
   - Registered in `scripts/smoke_tests/run_all.py` with `cheap=` flag set correctly.

Miss any of these seven and the agent is either wrong-tier, unshielded, un-audited, or un-tested. The skill exists to make missing them impossible.

## What to build

### File 1: `.claude/skills/trajectory-new-subagent/SKILL.md`

If `/mnt/user-data/outputs/SKILL.md` exists from the earlier session, copy it. If not, write from scratch following the structure below.

**Frontmatter:**

```yaml
---
name: trajectory-new-subagent
description: Enforces the 7-step pattern when adding a new sub-agent to Trajectory. Triggers on requests like "add a new agent", "create a phase N agent", "new sub-agent for <task>", or edits that create files under src/trajectory/sub_agents/, modify src/trajectory/schemas.py to add an agent output schema, add entries to src/trajectory/validators/content_shield.py's HIGH_STAKES_AGENTS or LOW_STAKES_AGENTS, or add entries to scripts/audit_prompt.py's _AGENT_REGISTRY.
---
```

The description is the trigger specification. Claude Code's dispatcher reads it to decide when to load the skill. Be specific — too vague and it loads on irrelevant edits; too narrow and it misses legitimate cases. The description above names three trigger phrases and four file-path signals.

**Body (after frontmatter):**

```markdown
# Adding a new sub-agent to Trajectory

You are adding a new LLM-backed sub-agent to the Trajectory codebase. The
project has an established 7-step pattern; every agent in `src/trajectory/sub_agents/`
follows it. Do not skip steps, and do not combine them.

## The seven steps, in order

### Step 1 — Prompt file

Create `src/trajectory/prompts/<agent_name>.md`. Top of file:

    <!--
    Purpose: <one sentence>
    Untrusted inputs: <list — scraped pages, user messages, etc.>
    Trusted inputs: <list — profile, gov_data, prior validated agent outputs>
    Model: <Sonnet 4.6 | Opus 4.7>
    Effort: <low | medium | high | xhigh>
    Output schema: <SchemaName from schemas.py>
    -->

Then the system prompt. Follow the style of `cv_tailor.md` or `verdict.md`
depending on whether the agent is generative or analytical.

### Step 2 — Schema

In `src/trajectory/schemas.py`, add a Pydantic model named `<AgentName>Output`.
Every field:
  - Has a concrete type (no `Any`, no bare `dict`).
  - Has a default where the field is optional.
  - Has a docstring or `Field(description=...)` explaining the field.

If the output contains claims that must be cited, the claim fields are
`Citation`-bearing. Follow the pattern in `CompanyResearch.culture_claims`.

### Step 3 — Sub-agent module

Create `src/trajectory/sub_agents/<agent_name>.py`:

    """<Agent purpose>.

    Model: <choice>. Effort: <choice>. Rationale: <one sentence per CLAUDE.md Rule 7>.
    """

    async def run(...) -> <AgentName>Output:
        ...

    async def _call_<agent_name>(user_input: str, *, session_id: str) -> <AgentName>Output:
        return await call_agent(
            agent_name="<agent_name>",
            system_prompt=PROMPT,
            user_input=user_input,
            response_schema=<AgentName>Output,
            model=settings.<model_id_field>,
            effort="<effort>",
            session_id=session_id,
        )

### Step 4 — Model + effort documented

The docstring in Step 3 must state the model and effort choice with a
one-sentence rationale. Cross-reference CLAUDE.md Rule 7:

  - Sonnet low: structured extraction from a single reply. Cheap per call (~$0.01-0.02).
  - Sonnet medium: light reasoning, JSON output with schema translation.
  - Opus low: shallow reasoning over a medium input.
  - Opus medium: standard reasoning tasks, cross-referencing 2-3 sources.
  - Opus high: deep reasoning, multi-source synthesis.
  - Opus xhigh: adaptive thinking, the highest-stakes generative or evaluative work.

When in doubt, err toward Sonnet — an honest tier downgrade is always
preferable to a silent cost overrun.

### Step 5 — Content Shield registration

In `src/trajectory/validators/content_shield.py`, add agent name to either:
  - `HIGH_STAKES_AGENTS` — output feeds verdict, gets rendered, or crosses a
    trust boundary (e.g. into a subprocess).
  - `LOW_STAKES_AGENTS` — output is intermediate, cached internally, and
    doesn't reach the user directly.

Un-registered agents receive Tier 1 shielding on input but no Tier 2 on
output. That's correct for some agents and wrong for others. Be explicit.

### Step 6 — Audit script registration

In `scripts/audit_prompt.py`, add an entry to `_AGENT_REGISTRY`:

    "<agent_name>": {
        "prompt_path": "src/trajectory/prompts/<agent_name>.md",
        "trusted_upstream_agents": [<list>],
        "untrusted_inputs": [<list — "scraped_pages", "user_reply", etc.>],
    }

This is what the static audit uses to trace injection reachability. Miss this
and new agents are invisible to the audit.

### Step 7 — Smoke test

Create `scripts/smoke_tests/<agent_name>.py`:

    ESTIMATED_COST_USD = <honest number>

    async def main():
        # Build minimal realistic input.
        # Call the agent.
        # Assert output shape.
        ...

Register in `scripts/smoke_tests/run_all.py`:

    SMOKE_TESTS.append(
        SmokeTest(
            module="<agent_name>",
            cost_usd=<cost>,
            cheap=<True if cost < 0.05 else False>,
        )
    )

## Before you finish

Run, in order:

1. `pytest tests/` — no new failures.
2. `ruff check src/ tests/ scripts/` — no new warnings.
3. `python scripts/audit_prompt.py` — the new agent appears in the output.
4. `python scripts/smoke_tests/run_all.py --cheap-only` — if `cheap=True`, your
   smoke test ran and passed. If `cheap=False`, tell the user it's gated and
   suggest they run it manually.

## Common mistakes

- Step 4 forgotten: model choice buried in the code, not documented. A future
  reviewer (or a future you) won't know why Sonnet instead of Opus.
- Step 5 partial: added to one list but not the other. `content_shield.shield()`
  does not error on unknown agents — it just returns early. Silent failure.
- Step 7 registered with wrong `cheap` flag: an Opus xhigh smoke test flagged
  `cheap=True` will burn the daily budget on every CI run.
- Prompt file checked in but empty placeholder. Audit doesn't catch this
  because it only checks registration, not content.
```

### File 2: `.claude/skills/trajectory-new-subagent/_examples/onboarding_parser_reference.md`

Copy `src/trajectory/sub_agents/onboarding_parser.py`, `src/trajectory/prompts/onboarding/*.md`, and the relevant `schemas.py` fragment into a single markdown file as a worked example. Include:
- The module docstring showing Step 4 done correctly (after the Sonnet swap from prompt 01).
- The schema additions.
- The content_shield registration.
- The audit_prompt registration.
- The smoke test.

This serves as the canonical "here's what done looks like" reference. Claude Code can load it when the skill fires to anchor the pattern in concrete code.

### File 3: `.claude/settings.json` (if not already present)

If the repo doesn't have `.claude/settings.json`, create one with minimum:

```json
{
  "skills": {
    "trajectory-new-subagent": {
      "enabled": true
    }
  }
}
```

If settings.json already exists, add the skills entry to it.

### File 4: `.gitignore` check

The `.claude/` directory SHOULD be committed (it's project configuration, not user state). Verify no existing `.gitignore` rule excludes it. If there's a catch-all `.claude/*` or similar, remove it and add more specific excludes for any user-local files (e.g. `.claude/cache/`).

### File 5: PROCESS.md entry

Append:

**Entry N — Claude Code skill: `trajectory-new-subagent`.**

Document:
- Trigger: onboarding_parser was added with Opus low when Sonnet low was correct. The pattern to prevent this exists in CLAUDE.md Rule 7 but isn't enforced — a skill does enforce.
- Decision: install a skill that walks the 7-step pattern for any new sub-agent.
- What the skill covers: prompt file + schema + module + model choice + shield registration + audit registration + smoke test.
- What it doesn't cover: agent prompt content (that's judgment; the skill enforces structure, not voice).
- Forward-looking: skills 2-5 already scoped (`trajectory-citation-discipline`, `trajectory-gov-data-source`, `trajectory-prompt`, `trajectory-smoke`). Install them separately as each becomes a demonstrated pain point.

## Hard constraints

1. **Don't enable the skill in a way that triggers on every edit to `src/trajectory/`.** The frontmatter description is the trigger gate. Review it before committing. Too-broad triggers are noise; too-narrow triggers are invisible.
2. **Don't modify any existing agent.** The skill applies on the next new agent. Retrofit is not this task.
3. **Do not inline the 7-step content into CLAUDE.md.** CLAUDE.md already lists the 7 items briefly (Rule 11). The skill is where the detailed walk-through lives. Keeping them separate prevents duplication drift.
4. **The reference example must be current.** If `onboarding_parser.py` still has `settings.opus_model_id` when you copy it, fix it first (or run prompt 01 first). A reference that ships with a wrong tier defeats the point.
5. **Skill description word count matters.** Claude Code's dispatcher reads it; overly long descriptions can slow triggering or get ignored. Stay under 80 words in the description field.

## Verification

After installation:

1. Open a Claude Code session in the repo. Start a message with "I want to add a new sub-agent for <task>" and confirm the skill loads (Claude Code surfaces loaded skills in the session UI).
2. Try an edit that touches `src/trajectory/sub_agents/<new_file>.py` — confirm the skill fires on the file-path signal.
3. Try an edit that only touches `src/trajectory/renderers/` — confirm the skill does NOT fire (false-positive check).
4. Run `python scripts/audit_prompt.py` — no errors; all existing agents pass audit (the skill didn't accidentally break the registry).

Document the three verification results in the user's summary.

## Acceptance criteria

- [ ] `.claude/skills/trajectory-new-subagent/SKILL.md` exists with correct frontmatter and the 7-step body.
- [ ] `.claude/skills/trajectory-new-subagent/_examples/onboarding_parser_reference.md` exists with a current (post-prompt-01 Sonnet) reference.
- [ ] `.claude/settings.json` enables the skill.
- [ ] `.gitignore` does not exclude `.claude/` project config.
- [ ] Skill description is under 80 words and triggers on the specified signals.
- [ ] Verification steps 1-4 pass; documented in the user summary.
- [ ] `PROCESS.md` has the new entry.
- [ ] `pytest tests/` all green. `ruff check` no new warnings.

## What NOT to do

- Do not retrofit existing agents to the pattern "because the skill exists now."
- Do not duplicate the 7-step content into CLAUDE.md.
- Do not install skills 2-5 in this task.
- Do not modify the skill's trigger description without explicit user review — the trigger is the contract with Claude Code's dispatcher.
- Do not write a `pre-commit` hook that enforces the 7 steps. A skill is a soft guide; a hook is a hard block. The soft guide is enough.

## If you're unsure

Stop. Ask. The skill is a small file but its triggers affect every future Claude Code session in this repo.
