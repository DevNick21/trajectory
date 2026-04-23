# Claude Code prompt — Trajectory pre-submission polish (revised)

> Paste this entire file to Claude Code as the task brief. Read it fully before writing any code.
>
> **This is a revised version of the earlier `01-pre-submission-polish.md`.** Three of the original five fixes turned out to be already done or partially done in the current repo. This version drops the obsolete work and tightens the remaining asks so Claude Code doesn't duplicate effort.
>
> **Scope:** pre-submission fixes only. Demo polish, honesty rewrites, data freshness, and a CLAUDE.md drift audit. No architectural changes. No new features.
>
> **Companion prompts (unchanged):**
> - `02-managed-agents-company-investigator.md`
> - `03-jsonld-extractor.md`
> - `04-latex-cv-renderer.md`
> - `05-cv-tailor-agentic.md`
> - `06-skill-trajectory-new-subagent.md`

---

## Context

Trajectory's main code path works end-to-end. A green run was achieved at $2.66 total cost, 6/6 gate tests passed. This task does not build new features.

**Before you touch any code, do a state check first.** A previous session's work has already landed some of what an earlier version of this prompt asked for. Specifically verified as already done:

- `bot/handlers.py::on_start` already captures `update.effective_user.first_name` (and last_name/username) into `ob.display_name`. No change needed there.
- `bot/onboarding.py::finalise_onboarding` already uses `session.display_name or "User"`.
- `sub_agents/onboarding_parser.py::_call_parser` already uses `settings.sonnet_model_id, effort="low"`. Docstring already documents the rationale.

If any of the above is NOT in the state I described, stop and tell the user — something has regressed since the last green run.

Read before starting:

1. `CLAUDE.md` — operating rules. Read with Fix 4 in mind — you'll be auditing this file later in the task.
2. `src/trajectory/config.py` — `use_managed_agents`, `managed_agents_beta_header`.
3. `src/trajectory/llm.py` — `_call_via_managed_agents`, `_routes_through_managed_agents`, the `use_managed_agents` flag plumbing.
4. `scripts/fetch_gov_data.py::fetch_going_rates()` — specifically the hardcoded skeleton and its comment at lines 248-254.
5. `src/trajectory/sub_agents/soc_check.py::_verify_sync` — specifically the threshold selection logic.
6. `SUBMISSION.md` — §3 (video VO), §4 (written description, judging-criteria table). The file is gitignored but lives in the local checkout.
7. `README.md` — search for any mention of "Managed Agents". Based on the shared repo state this phrase currently doesn't appear — in which case Fix 2 has no README.md edit to make.
8. `PROCESS.md` — the last entry (gitignored locally). You need this to know where your additions start numbering.

## The four fixes

### Fix 1 — Refresh stale Skilled Worker going rates

**Problem.** `scripts/fetch_gov_data.py::fetch_going_rates()` ships a hardcoded 10-row skeleton. The comment at the top of the function already acknowledges that only SOC 2136 was updated to the April 2026 regime; the other 10 SOC codes still hold April 2024 values. The general £41,700 threshold isn't stored anywhere, so `soc_check` can't consult it.

The practical consequence is a failing visa-holder demo: Trajectory would pass a job at £42k on SOC 2135 when the real binding threshold is `max(41700, 55000) = 55000`, or cite the wrong shortfall on a NO_GO verdict.

**Fix.**

1. **Do not attempt to scrape the live gov.uk going rates page in this task.** The proper fix needs a URL resolver similar to `_resolve_sponsor_register_url` plus an Appendix Skilled Occupations parser. Out of scope.

2. Update the hardcoded skeleton to 2026 values. For each row, add a one-line code comment citing the public 2026 source you used. Do a `web_search` for "SOC <code> going rate 2026 skilled worker" per SOC. These are the target values as of April 2026 (verify before committing):

   | SOC | Title | going_rate | new_entrant_rate |
   |---|---|---|---|
   | 2136 | Programmers and software development professionals | 52000 | 33400 |
   | 2135 | IT business analysts, architects, systems designers | 55000 | 33400 |
   | 2137 | Web and multimedia professionals | 45000 | 33400 |
   | 2139 | IT and telecom professionals | 50000 | 33400 |
   | 2134 | IT project managers | 58000 | 33400 |
   | 3534 | Finance and investment analysts | 56000 | 33400 |
   | 2424 | Business and financial project management | 62000 | 33400 |
   | 2221 | Medical practitioners | 60000 | 41750 |
   | 2119 | Natural and social science professionals | 41700 | 33400 |
   | 2425 | Management consultants and business analysts | 56000 | 33400 |
   | 1150 | Chief executives and senior officials | 95000 | 66500 |

   The new_entrant_rate floor of £33,400 is a hard Home Office floor for standard cases as of 2026 — even if 70% of the going rate would be lower, £33,400 applies. Code the floor explicitly; do not hand-calculate percentages from memory.

   SOC 2136 is already at 52000 / 33400, so the existing row stays as-is. You're updating the other ten.

3. Add a module-level constant `GENERAL_THRESHOLD_GBP = 41_700` in `scripts/fetch_gov_data.py`. Write it into the parquet as a single additional row or as a separate parquet file — whichever is simpler to read back. Either way, update `_load()` in `sub_agents/soc_check.py` to expose the value.

4. Update `soc_check.py::_verify_sync`. Currently the threshold selection is:

   ```python
   if ne_eligible and new_entrant_rate is not None:
       threshold = new_entrant_rate
   elif going_rate is not None:
       threshold = going_rate
   ```

   This ignores the general £41,700 threshold. The binding constraint per the 2026 regime is `max(general_threshold, role_specific_rate)`. Rewrite to:

   ```python
   role_rate = (
       new_entrant_rate if (ne_eligible and new_entrant_rate is not None)
       else going_rate
   )
   if role_rate is not None and general_threshold is not None:
       threshold = max(role_rate, general_threshold)
   elif role_rate is not None:
       threshold = role_rate
   elif general_threshold is not None:
       threshold = general_threshold
   else:
       threshold = None
   ```

   The `general_threshold` variable comes from the new parquet row/file you added in step 3. Don't hardcode it in two places.

5. Update the comment block at the top of `fetch_going_rates()` to read:

   > "Hardcoded skeleton reflecting the April 2026 regime (general threshold £41,700; new entrant floor £33,400). SOC 2136 was updated in an earlier pass (PROCESS.md Entry 27); this pass refreshes the remaining rows. Post-hackathon, replace with a real parser of the gov.uk Skilled Worker going rates page — see the corresponding PROCESS.md entry (numbered below)."

6. Tell the user in your summary that they need to delete the stale parquet and re-run the fetcher for the new values to take effect:

   ```bash
   rm data/processed/going_rates.parquet
   python scripts/fetch_gov_data.py
   ```

### Fix 2 — Managed Agents honesty rewrite

**Problem.** `llm.py::_call_via_managed_agents` attaches `anthropic-beta: managed-agents-2026-04-01` as a default header on a client that then calls `client.messages.create(...)`. That header belongs on `/v1/sessions`, not `/v1/messages` — so on the Messages API endpoint it's a no-op. `settings.use_managed_agents` defaults to `True`, so Phase 1 agents do route through this function, and the function just makes a plain Messages API call dressed up to look like it's using MA.

If SUBMISSION.md §3 or §4 claims "via Managed Agents" and a judge checks the code, the claim fails.

**Fix.** Documentation-only in this task. The real integration lives in prompt 02. Code cleanup of the dead MA stub also lives in prompt 02, so that code stays in place for now.

Before editing:

- **Grep SUBMISSION.md for the phrase "Managed Agents".** If it doesn't appear, Fix 2 is a no-op and you skip straight to Fix 3. Confirm that result to the user.
- **Grep README.md for the same phrase.** Based on the shared repo snapshot, README.md doesn't currently contain "Managed Agents" — the "What it does" section uses architecture language but not this phrase. If your grep agrees, skip the README edit.

Assuming SUBMISSION.md does contain the phrase:

**`SUBMISSION.md` §3 — video VO.**

Find the line containing "via Managed Agents" in the VO script. Replace it with:

> "Eight Opus 4.7 and Sonnet 4.6 sub-agents run in parallel — JD extraction, Companies House, Sponsor Register, SOC going rates, ghost-job detection, salary benchmarking, red flags. Thirty seconds. What I used to do in four hours, badly."

Remove the phrase "via Managed Agents" anywhere else in §3.

**`SUBMISSION.md` §4 — written description.**

Find the sentence containing "via Managed Agents". Replace with:

> "Paste a job URL and eight sub-agents run in parallel: company scraping, Companies House, Glassdoor, Sponsor Register, SOC going rates, ghost-job detection across four signals, and salary benchmarking. Opus 4.7 handles the reasoning-heavy agents (verdict, red flags, ghost-job scoring) with adaptive thinking at xhigh effort; Sonnet 4.6 handles the extraction pipeline. Every output is Pydantic-validated structured JSON, and every claim in the final verdict must resolve to a scraped URL + verbatim snippet, a gov.uk field, or a specific entry in the user's career history."

**`SUBMISSION.md` §4 — judging-criteria table.**

Replace the "Opus 4.7 Use (25%)" row's evidence column. If it cites "eight Opus 4.7 sub-agents … parallel via Managed Agents", swap it for:

> "16-agent orchestration (12 Opus, 4 Sonnet) with adaptive thinking and structured tool-use output, Pydantic-validated at every call, citation validator enforcing no invented data, and an injection-resistant two-tier content shield on every untrusted input."

**Do not touch the code in this task.** Prompt 02 handles the dead-stub cleanup as part of a real integration. If the user opts to skip prompt 02, a follow-up will delete the dead code separately.

### Fix 3 — PROCESS.md entries

Append new entries at the end of `PROCESS.md`. Use the next available number. Some of what an earlier version of this prompt wanted is already captured in existing entries:

- Entry 26 (onboarding parser: regex → per-stage LLM) is referenced by `onboarding_parser.py`'s docstring and should already exist. If it doesn't, create it — but verify first by opening PROCESS.md and scanning for "Entry 26".
- Entry 27 (going rates freshness) is referenced by `fetch_going_rates()`'s comment. If it doesn't exist, create it — but again verify first.

Whatever the next number is (call it N), append:

**Entry N — Skilled Worker going rates: 2026 refresh.**

Document:
- Trigger: April 2026 visa-holder demos would fail — most SOC rates in the skeleton were 2024 values. SOC 2136 had been refreshed in Entry 27, but the others and the £41,700 general threshold were not.
- Decision: refresh all remaining rates to the 2026 regime using public immigration-law sources (one cited source per SOC in code comments). Add a module-level `GENERAL_THRESHOLD_GBP = 41_700` constant stored in the parquet and consumed by `soc_check._verify_sync`.
- Semantics change: `soc_check` now computes `max(role_specific_rate, general_threshold)` — previously only the role rate was consulted, which would pass jobs below the general threshold when the role rate happened to be lower.
- Forward-looking: build a real parser of the Appendix Skilled Occupations page to replace this skeleton, following `_resolve_sponsor_register_url`.

**Entry N+1 — Managed Agents claim correction.**

Document:
- Trigger: code review found that `llm._call_via_managed_agents` attaches the MA beta header to a plain Messages API call — a no-op on `/v1/messages`. SUBMISSION.md claimed "via Managed Agents" on top of this.
- Decision: submission materials rewritten to describe the actual architecture (`asyncio.gather` parallel fan-out with Pydantic-validated structured output). The dead code stub stays in place for prompt 02 to handle — the user may opt to build a real MA integration for the company scraper, in which case the code touched is a superset of deletion.

**Entry N+2 — Deferred defects from repo review.**

One line each:

- Verdict truncates scraped_pages text to 1200 chars in `_serialise_bundle`. Risk of dropping citable evidence on long pages. Deferred; post-hackathon.
- Self-audit `_apply_rewrites_to_strings` uses `str.replace(..., count=1)` per leaf, which can hit the wrong occurrence when the same banned phrase appears in multiple fields. Proper fix needs field-path threading through `AuditFlag`. Deferred.
- Content shield `shield()` does not emit a flag for agents not in either `HIGH_STAKES_AGENTS` or `LOW_STAKES_AGENTS`. New agents without explicit registration receive Tier 1 but no Tier 2 regardless of risk. Add a registry check that raises at startup — post-hackathon.

### Fix 4 — CLAUDE.md drift audit

**Problem.** `CLAUDE.md` has accreted three days of directives across green-run iterations. Opus 4.7 takes CAPS and "NEVER/ALWAYS" directives very literally — stale ones silently degrade every future Claude Code session, and conflicting directives produce unpredictable behaviour when they both fire on the same turn. This is the last chance pre-submission to tighten it.

**Fix.** Audit, don't rewrite wholesale.

1. Open `CLAUDE.md` and list every directive that matches any of these patterns:
   - Starts with `ALWAYS`, `NEVER`, `DO NOT`, `MUST`, or `MUST NOT`
   - Is in CAPS for more than three words
   - References a specific file path, function name, or module name
   - Gives a numbered rule in a "Rules" or "Operating rules" block

2. For each listed directive, classify it into exactly one of:
   - **KEEP** — still accurate, still load-bearing.
   - **STALE** — references a file, symbol, pattern, or behaviour that no longer exists in the repo (verify with `grep` or `view` — don't guess).
   - **CONFLICTING** — contradicts another directive elsewhere in CLAUDE.md, or contradicts the actual code behaviour after earlier fixes in this session.
   - **TOO RIGID** — correct in spirit but phrased so absolutely that Opus 4.7 is likely to over-trigger on it (Tharik's term for this pattern is "over-indexing"). Example: an `ALWAYS` rule that should allow an escape hatch for a legitimate exception.

3. Present the classified list to the user as a table (Directive | Classification | Proposed action | Rationale). **Stop here.** Do not edit CLAUDE.md until the user approves the proposed edits.

4. After approval, apply the edits. For STALE: delete. For CONFLICTING: rewrite to resolve the conflict, citing which directive it was reconciled against. For TOO RIGID: soften with a narrow scope clause (e.g. "ALWAYS X unless Y" or "Prefer X; consider Y when…"). For KEEP: untouched.

5. After edits, do a second pass: count the `NEVER`/`ALWAYS` directives before and after. Report both counts. If the total dropped by more than 30% or grew at all, pause and ask the user if that's intended.

**Do not:**
- Rewrite the entire CLAUDE.md from scratch.
- Change the section structure.
- Touch directives that are clearly operational (e.g. "Python 3.11+", "run ruff before committing").
- Modify any directive without an explicit classification and rationale in the table.

**Scope cap:** if the audit produces more than 8 proposed edits, that's a signal CLAUDE.md has accumulated more drift than is safe to fix in a pre-submission pass. Stop at 8, apply those, flag the rest as a PROCESS.md deferred item.



Task is complete when all are true:

- [ ] State check at the top of this prompt confirmed — name capture, Sonnet parser, PROCESS.md Entry 26/27 all verified present (or the user told they're absent).
- [ ] `scripts/fetch_gov_data.py::fetch_going_rates()` uses 2026 values for every SOC in its skeleton, with a per-SOC source comment. `GENERAL_THRESHOLD_GBP = 41_700` is stored and exposed.
- [ ] `sub_agents/soc_check.py::_verify_sync` computes `max(role_specific_rate, general_threshold)`. Threshold selection code matches Fix 1 step 4.
- [ ] If SUBMISSION.md contained "Managed Agents", it has been rewritten per Fix 2 §1-3. If it didn't, the user has been told.
- [ ] If README.md contained "Managed Agents", it has been rewritten; otherwise untouched.
- [ ] `PROCESS.md` has up to three new entries as specified. Numbering continuous with existing entries; entry numbers in the code comments (`onboarding_parser.py` docstring, `fetch_going_rates()` comment) still resolve.
- [ ] `pytest tests/` all green. `ruff check src/ tests/ scripts/` no new warnings.
- [ ] User has been told: `rm data/processed/going_rates.parquet && python scripts/fetch_gov_data.py` to apply the new going rates.
- [ ] CLAUDE.md directives audited. A classified table was presented to the user before any edits. Approved edits applied. Before/after `NEVER`/`ALWAYS` counts reported. Edit count ≤ 8; overflow deferred to PROCESS.md.

## What NOT to do

- Do not re-add `ob.answers["name"]` plumbing; `ob.display_name` already exists.
- Do not swap the onboarding parser model; it's already Sonnet low.
- Do not delete `_call_via_managed_agents`, `_routes_through_managed_agents`, `use_managed_agents`, or `managed_agents_beta_header` in this task. Prompt 02 handles that.
- Do not build any new agent.
- Do not scrape the live gov.uk Skilled Worker page.
- Do not touch the SOC 2136 row in the skeleton; it's already correct.
- Do not rewrite parts of SUBMISSION.md beyond the three edit locations specified.
- Do not rename, reformat, or restructure PROCESS.md. Append only.
- Do not rewrite CLAUDE.md wholesale — Fix 4 is targeted edits only, and only after the user approves the classified table.

## If you're unsure

Stop and ask. Each of these fixes touches submission-sensitive material. Silent guessing is worse than a blocked question — especially on Fix 2 where a grep miss is the difference between doing nothing and doing something productive.