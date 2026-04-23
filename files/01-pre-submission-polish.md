# Claude Code prompt — Trajectory pre-submission polish

> Paste this entire file to Claude Code as the task brief. Read it fully before writing any code.
>
> **Scope:** pre-submission fixes only. Demo polish and honesty rewrites. No architectural changes. No new features.
>
> **Companion prompts:**
> - `02-managed-agents-company-investigator.md` — real MA integration (post-polish, substantial)
> - `03-jsonld-extractor.md` — pre-LLM schema.org parser (post-submission safe to defer)
> - `04-latex-cv-renderer.md` — alternative CV template path (post-submission)
> - `05-cv-tailor-agentic.md` — FAISS-as-tool refactor of CV tailor (post-submission)
> - `06-skill-trajectory-new-subagent.md` — install the 7-step discipline skill (post-submission)

---

## Context

Trajectory is 72 hours from submission. The main code path works end-to-end — a green run was achieved at $2.66 total cost, 6/6 gate tests passed. This task does not build new features. It fixes five specific issues found during review that affect either demo quality or submission honesty.

Read before starting:

1. `CLAUDE.md` — operating rules.
2. `src/trajectory/bot/onboarding.py` — specifically `finalise_onboarding` and the `name="User"` TODO comment.
3. `src/trajectory/bot/handlers.py` — specifically `on_start` and where the onboarding session is created.
4. `src/trajectory/sub_agents/onboarding_parser.py` — the `_call_parser` function and its `model=` argument.
5. `src/trajectory/llm.py` — specifically `_call_via_managed_agents`, `_routes_through_managed_agents`, and the `use_managed_agents` flag plumbing.
6. `src/trajectory/config.py` — `use_managed_agents` and `managed_agents_beta_header`.
7. `scripts/fetch_gov_data.py` — specifically `fetch_going_rates()`.
8. `SUBMISSION.md` §3 (video VO), §4 (written description, judging-criteria table).
9. `README.md` — the "What it does" section.
10. `PROCESS.md` — the last entry, to know where your additions start numbering.

## The five fixes

### Fix 1 — Capture user's name from Telegram

**Problem.** `bot/onboarding.py:finalise_onboarding` hardcodes `name="User"` with a TODO comment. Every generated CV renders with "User" as the applicant name. Embarrassing on camera.

**Fix.**

1. In `bot/handlers.py::on_start`, after creating the `OnboardingSession`, read `update.effective_user.first_name` (required field in Telegram) and store it:

   ```python
   ob = OnboardingSession(user_id=user_id)
   # Telegram requires first_name on every user — capture it so we don't
   # need to ask during onboarding.
   tg_first_name = (update.effective_user.first_name or "").strip()
   if tg_first_name:
       ob.answers["name"] = tg_first_name
   _onboarding_sessions[chat_id] = ob
   ```

2. In `bot/onboarding.py::finalise_onboarding`, replace the hardcoded `name="User"` line with:

   ```python
   name=session.answers.get("name") or "",
   ```

   Empty string, never the literal "User" placeholder. Empty strings are handled gracefully by downstream renderers (verify this — check `renderers/cv_docx.py` and `renderers/cv_pdf.py` handle empty `cv.name`).

3. If `cv.name` renders poorly when empty, fall back to `"Candidate"` in the renderer itself, not in the profile. The profile should never contain a sentinel value.

4. Remove the TODO comment. Replace with a one-line comment explaining the Telegram-sourced default.

### Fix 2 — Onboarding parser: Opus → Sonnet

**Problem.** `onboarding_parser._call_parser` currently calls `call_agent` with `model=settings.opus_model_id, effort="low"`. Per-reply cost is ~$0.15. Per-onboarding (7 stages) is ~$1.00. The task is per-field structured extraction from a single reply — Sonnet 4.6 handles this at ~$0.01/reply.

**Fix.**

1. Change the `model=` argument in `onboarding_parser._call_parser` to `settings.sonnet_model_id`. Leave `effort="low"`.

2. Update the docstring at the top of `onboarding_parser.py` — the comment says "Opus 4.7 low-effort per-stage parser". Change to "Sonnet 4.6 low-effort per-stage parser" and add a one-sentence rationale: per-field extraction from a single reply is not a reasoning task, so Sonnet is the correct tier per CLAUDE.md Rule 7.

3. Update `scripts/smoke_tests/onboarding_parser.py`. The `ESTIMATED_COST_USD` constant is `0.15` — which was accurate only on Opus. Change to `0.05` (covers 3 Sonnet low round-trips with margin).

4. Run the onboarding smoke test locally if the user's environment supports it. If it passes on Sonnet low, the swap is validated. If Sonnet low fails any assertion, revert to `settings.opus_model_id` and report back.

   Before running anything against the real API, confirm with the user that they want you to spend ~$0.05 of their API credits on a validation run. Do not assume yes.

### Fix 3 — Refresh stale Skilled Worker going rates

**Problem.** `scripts/fetch_gov_data.py::fetch_going_rates()` returns a hardcoded 10-row skeleton from April 2024 rates:

| SOC | Current parquet | Actual 2026 regime |
|---|---|---|
| General threshold | (not modelled) | **£41,700** |
| New entrant floor | £30,900 | **£33,400** |
| SOC 2136 going rate | £40,300 | **~£52,000** |

This means any visa-holder demo would fail: Trajectory would pass a job at £42k on SOC 2136 when the real threshold is ~£52k, or cite the wrong shortfall amount on a NO_GO verdict.

**Fix.**

1. **Do not attempt to scrape the live gov.uk going rates page during this task.** That's the post-hackathon proper fix; it needs a URL resolver similar to `_resolve_sponsor_register_url` plus a real Appendix Skilled Occupations parser. Too much scope for this prompt.

2. Instead, update the hardcoded skeleton in `fetch_going_rates()` to 2026 values. Source your numbers from public 2026 immigration-law references; do a quick `web_search` for "SOC <code> going rate 2026 skilled worker" for each SOC in the list. Cite your source for each SOC in a code comment so the numbers are defensible.

3. Use these 2026 values for the SOCs currently in the skeleton (verify against a current source before committing — my numbers below are from April 2026 web searches but check them):

   | SOC | Title | going_rate | new_entrant_rate |
   |---|---|---|---|
   | 2136 | Programmers and software development professionals | 52000 | 33400 |
   | 2135 | IT business analysts, architects, systems designers | 55000 | 33400 |
   | 2137 | Web and multimedia professionals | 45000 | 33400 |
   | 2139 | IT and telecom professionals | 50000 | 33400 |
   | 2134 | IT project managers | 58000 | 33400 |
   | 3534 | Finance and investment analysts | 56000 | 33400 |
   | 2424 | Business and financial project management | 62000 | 33400 |
   | 2221 | Medical practitioners | 60000 | 41750 (Health & Care route) |
   | 2119 | Natural and social science professionals | 41700 | 33400 |
   | 2425 | Management consultants and business analysts | 56000 | 33400 |
   | 1150 | Chief executives and senior officials | 95000 | 66500 |

   **The new_entrant_rate floor is £33,400 for standard cases as of 2026.** This is a hard floor from the Home Office's tradeable-points Option E — even if 70% of the going rate would be lower, £33,400 applies. Code this floor explicitly. Do not hand-calculate percentages from memory.

4. Add a new field `general_threshold_gbp = 41700` as a module-level constant in `fetch_going_rates()`, written into the parquet as a single row or as a separate parquet file. The verdict agent uses this when the SOC-specific going rate is below the general threshold — the binding constraint is `max(general_threshold, going_rate)`. Check `sub_agents/soc_check.py::_verify_sync` — if it doesn't already implement this max, add it. If it does, verify the threshold value isn't stale there too.

5. Update the comment at the top of `fetch_going_rates()` to state: "Hardcoded skeleton reflecting the July 2025 regime (general threshold £41,700; new entrant floor £33,400). This is a demo stand-in. Post-hackathon, replace with a real parser of the gov.uk Skilled Worker going rates page — see PROCESS.md Entry <N>."

6. If the user has a stale `data/processed/going_rates.parquet` checked out, the fetcher will skip re-running because of the existing-file guard. Tell the user in your summary that they need to run `rm data/processed/going_rates.parquet && python scripts/fetch_gov_data.py` for the new values to take effect.

### Fix 4 — Managed Agents honesty rewrite

**Problem.** `SUBMISSION.md` §3, §4, and `README.md` claim:

> "Eight Opus 4.7 sub-agents run in parallel via Managed Agents."

The code does not do this. `llm.py::_call_via_managed_agents` calls `client.messages.create(...)` with the Managed Agents beta header attached — which is a no-op because that header belongs on `/v1/sessions` endpoints, not `/v1/messages`. Shipping the claim unchanged is an honesty risk with judges who check code.

**Fix.** This is a documentation-only fix for now. A separate prompt (`02-managed-agents-company-investigator.md`) covers building a genuine Managed Agents integration — that's optional and post-polish.

In this task, you make three edits:

**1. `SUBMISSION.md` §3 — video VO.**

Find the line:
> "Eight Opus 4.7 sub-agents run in parallel via Managed Agents."

Replace with:
> "Eight Opus 4.7 and Sonnet 4.6 sub-agents run in parallel — JD extraction, Companies House, Sponsor Register, SOC going rates, ghost-job detection, salary benchmarking, red flags. Thirty seconds. What I used to do in four hours, badly."

Also remove the phrase "via Managed Agents" anywhere else in §3.

**2. `SUBMISSION.md` §4 — written description.**

Find:
> "Paste a job URL and eight Opus 4.7 sub-agents run in parallel via Managed Agents: company scraping, Companies House, Glassdoor, Sponsor Register, SOC going rates, ghost-job detection across four signals, and salary benchmarking."

Replace with:
> "Paste a job URL and eight sub-agents run in parallel: company scraping, Companies House, Glassdoor, Sponsor Register, SOC going rates, ghost-job detection across four signals, and salary benchmarking. Opus 4.7 handles the reasoning-heavy agents (verdict, red flags, ghost-job scoring) with adaptive thinking at xhigh effort; Sonnet 4.6 handles the extraction pipeline. Every output is Pydantic-validated structured JSON, and every claim in the final verdict must resolve to a scraped URL + verbatim snippet, a gov.uk field, or a specific entry in the user's career history."

**3. `SUBMISSION.md` §4 — judging-criteria table.**

Replace the "Opus 4.7 Use (25%)" row's evidence column. Currently cites "eight Opus 4.7 sub-agents … parallel via Managed Agents". Replace with:

> "16-agent orchestration (12 Opus, 4 Sonnet) with adaptive thinking and structured tool-use output, Pydantic-validated at every call, citation validator enforcing no invented data, and an injection-resistant two-tier content shield on every untrusted input."

**4. `README.md` — "What it does" section.**

Find the bullet referencing Managed Agents. Replace with a version that uses accurate language: "Eight sub-agents run in parallel via `asyncio.gather` — each returns Pydantic-validated structured output."

**5. Do not touch the code in this task.** Leaving the dead `_call_via_managed_agents` stub in place for this task is fine — prompt `02-managed-agents-company-investigator.md` handles code cleanup as part of the real integration. If the user chooses to skip that prompt entirely, a separate follow-up will delete the dead code.

### Fix 5 — PROCESS.md entries

Append four new entries at the end of `PROCESS.md`. Use the next available entry numbers. (If your last entry is 25, these become 26-29.)

**Entry N — Onboarding parser: regex → per-stage LLM.**

Document:
- Trigger: live test revealed regex in `finalise_onboarding` failed silently on typical replies (5 pounds → £30k default; "I don't work" → single-item list; green flags never populated).
- Decision: replace with per-stage Sonnet low parser. 7 stages, one coroutine each. Three-status output (`parsed` / `needs_clarification` / `off_topic`).
- Architecture choices: prompts as markdown files under `prompts/onboarding/`; `AdvanceOutcome` dataclass instead of new state machine branch; clarification cap of 3 per stage with graceful "skip" on the third; off-topic cap of 3 per session before abandonment; 2000-char input cap as DoS defence; Content Shield Tier 1 on every reply.
- Model choice: initial deploy used Opus low; corrected to Sonnet low on honesty review — per-field extraction from a single reply is not a reasoning task.
- What was NOT added: CLARIFYING state (the dataclass handled it); explicit name question (captured from Telegram `first_name` instead).

**Entry N+1 — Known data freshness: going_rates.parquet.**

Document:
- `scripts/fetch_gov_data.py::fetch_going_rates()` ships a hardcoded skeleton because the live gov.uk resolver was never implemented for this data source (only for the Sponsor Register).
- Skeleton updated to 2026 values (general threshold £41,700; new entrant floor £33,400; SOC 2136 going rate ~£52,000).
- Forward-looking: post-hackathon, implement a real parser of the Appendix Skilled Occupations page following the same pattern as `_resolve_sponsor_register_url`.

**Entry N+2 — Managed Agents claim correction.**

Document:
- The submission materials claimed "via Managed Agents" in three places. The code did not do this — `_call_via_managed_agents` calls the Messages API with the MA beta header, which is a no-op on `/v1/messages`.
- Fix applied: submission materials rewritten to describe the actual architecture (`asyncio.gather` parallel fan-out with Pydantic-validated structured output). The dead code stub is still present and will be addressed in a separate task (see prompt `02-managed-agents-company-investigator.md`).
- Why the dead stub wasn't deleted in this pass: the user may opt to build a real Managed Agents integration for the company scraper, in which case the code touched is a superset of the deletion.

**Entry N+3 — Repo review: deferred defects.**

Document (short list, one line each):

- Verdict truncates scraped_pages text to 1200 chars in `_serialise_bundle`. Risk of dropping citable evidence on long pages. Deferred; post-hackathon fix.
- Self-audit `_apply_rewrites_to_strings` uses `str.replace(..., count=1)` per leaf, which can hit the wrong occurrence when the same banned phrase appears in multiple fields. Proper fix needs field-path threading through `AuditFlag`. Deferred.
- Content shield `shield()` does not emit a flag for agents that aren't in either `HIGH_STAKES_AGENTS` or `LOW_STAKES_AGENTS`. New agents without explicit registration receive Tier 1 but no Tier 2 regardless of risk. Post-hackathon, add a registry check that raises at startup.

## Acceptance criteria

Task is complete when all are true:

- [ ] `bot/handlers.py::on_start` captures `update.effective_user.first_name` into `ob.answers["name"]`.
- [ ] `bot/onboarding.py::finalise_onboarding` uses `session.answers.get("name") or ""` instead of `"User"`. No sentinel placeholder anywhere.
- [ ] Renderer fallback (if needed): `cv.name` empty renders as `"Candidate"` in `renderers/cv_docx.py` and `renderers/cv_pdf.py`, not `"User"`.
- [ ] `sub_agents/onboarding_parser.py::_call_parser` uses `model=settings.sonnet_model_id, effort="low"`. Docstring updated.
- [ ] `scripts/smoke_tests/onboarding_parser.py` has `ESTIMATED_COST_USD = 0.05`.
- [ ] `scripts/fetch_gov_data.py::fetch_going_rates()` uses 2026 values for every SOC in its skeleton, with a per-SOC source comment. General threshold £41,700 is stored and consulted.
- [ ] `sub_agents/soc_check.py::_verify_sync` computes `max(general_threshold, going_rate)` as the binding threshold. If it didn't before, it does now.
- [ ] `SUBMISSION.md` and `README.md` no longer claim "via Managed Agents" blanket over the 8-agent pipeline. Rewrites match Fix 4 §1–4 verbatim (or close paraphrase acceptable — user reviews the draft).
- [ ] `PROCESS.md` has four new entries as specified. Numbering continuous with existing entries.
- [ ] `pytest tests/` all green. `ruff check src/ tests/ scripts/` no new warnings.
- [ ] The user has been told they need `rm data/processed/going_rates.parquet && python scripts/fetch_gov_data.py` to apply the new going rates.

## What NOT to do

- Do not delete `_call_via_managed_agents`, `_routes_through_managed_agents`, `use_managed_agents`, or `managed_agents_beta_header` in this task. Prompt 02 handles that.
- Do not build any new agent.
- Do not scrape the live gov.uk Skilled Worker page in this task. That's post-hackathon work.
- Do not make the Sonnet swap without running the onboarding smoke test first (with user consent on the ~$0.05 cost).
- Do not rewrite parts of SUBMISSION.md beyond the three edit locations specified. The file's structure is finalised.
- Do not rename, reformat, or restructure PROCESS.md. Append only.

## If you're unsure

Stop and ask. Each of these fixes touches submission-sensitive material. Silent guessing is worse than a blocked question.
