# CLAUDE.md — AskPicky

> Operating manual for Claude Code working on this repo.
> Read this first, every session.
> For **what AskPicky is** (positioning, free/premium split, roadmap), read [ASKPICKY.md](./ASKPICKY.md). That document is canonical and supersedes anything here on contradiction.

*Last updated 2026-05-22 23:30 BST · HEAD `60add03` (Close gap #7: signal weights). Recent stream: architecture-gap closure pass (`210dd8d` → `60add03`) closed all 9 gaps from the 2026-05-17 architecture review at the data layer + verdict prompt level. See [HANDOFF.md](./HANDOFF.md) §4.*

---

## Project

- **Product spec:** [ASKPICKY.md](./ASKPICKY.md) (canonical)
- **Agent prompt inventory:** [AGENTS.md](./AGENTS.md)
- **Decision log:** [PROCESS.md](./PROCESS.md)
- **History (no longer authoritative):** [docs/history/](./docs/history/)

Package name: `askpicky` (was `trajectory`; rename landed 2026-05-22, no backward compat). Python imports are `from askpicky.X import Y`. Frontend brand strings say "AskPicky" / "Picky".

Test-mode opt-out for required-secret validation: `ASKPICKY_TEST_MODE=1` (was `TRAJECTORY_TEST_MODE`).

---

## Hard architectural rules

These apply to every piece of code. A change that violates one is wrong — fix the change, not the rule.

### Rule 1 — No invented data
No agent emits a claim without a resolvable citation. Source-grounded agents (cover_letter, likely_questions, salary_strategist, draft_reply, red_flags, verdict, offer_analyst) use Anthropic's Citations API via `call_with_citations` — every `cited_text` is a guaranteed-verbatim substring of the source. Schema-dense agents (cv_tailor, intent_router, etc.) use `call_structured` and embed `Citation` objects validated by `validators/citations.py`. Three citation kinds: `url_snippet`, `gov_data`, `career_entry`.

### Rule 2 — User-type branching in the verdict
The verdict agent checks `user_profile.user_type` and applies the correct hard-blocker set:
- `uk_resident`: ghost-job, company distress, personal salary floor, market 10th percentile, deal-breaker trigger.
- `visa_holder`: all of the above PLUS sponsor register status, SOC threshold, SOC eligibility, nationality grant rate context.

Motivation mismatch is a `StretchConcern`, not a hard blocker. A `GO` verdict with any hard blocker present is a programmatic error — the validator flips it to `NO_GO`.

### Rule 3 — Writing-style injection in every generator
Every Phase 4 generator (CV tailor, cover letter, likely questions, salary strategist, draft_reply) receives the user's `WritingStyleProfile` in its system prompt. If `sample_count < 3`, the profile is directional only.

### Rule 4 — Parallel fan-out where it applies
Phase 1 research (9 sub-agents) and `full_prep` (4 Phase 4 generators) run in parallel via `asyncio.gather`. Serial execution is a performance bug.

### Rule 5 — Structured output everywhere
Every LLM call returns strict Pydantic-validated JSON. No free-form prose from sub-agents.

### Rule 6 — On-demand, not on-the-fly
`forward_job` runs Phase 1 + verdict and STOPS. Pack components are triggered by separate intents (`draft_cv`, `draft_cover_letter`, `salary_advice`, `predict_questions`, `draft_reply`) or by `full_prep`.

### Rule 7 — Cheapest model that meets the bar; Opus only where judgement is the product

Bias toward cheap+fast for anything mechanical, structured, or pattern-matching.

**Opus 4.7 `xhigh`** — only the 6 calls where the *position itself* is the product:

- `verdict` (the take itself)
- `cv_tailor` (judgement about which bullets matter for a role)
- `cover_letter` (voice + Citations API)
- `salary_strategist` (negotiation reasoning + Code Execution)
- `offer_analyst` (offer-letter analysis with Files API + Citations)
- `prompt_auditor` (build-time only)

**Sonnet 4.6** — structured tasks with multi-page interpretive work:

- `style_extractor` (latent voice extraction from samples)
- `red_flags_detector` (Web Search + structured citations)
- `star_polisher`, `draft_reply` (voice-sensitive output)
- `company_scraper_summariser`, `onboarding_parser`, `content_shield_tier2`

**Haiku 4.5** — mechanical reshape / classification / single-doc structured extraction:

- `intent_router` (Tier-0 deterministic rules first — ~80% of messages never hit the LLM; Haiku for the rest)
- `cv_parser` (CV structure extraction + narrative bio in ONE call)
- `interview_questions.design` / `.predict` (merged from old `question_designer` + `likely_questions` 2026-05-22)
- `jd_extractor` (structured field-by-field reshape; JSON-LD tier-0 covers the major ATSes upstream)
- `ghost_job_jd_scorer` (5-dim specificity score; reverted from Opus xhigh)
- `self_audit` (banned-phrase + citation validation; mostly mechanical)
- `entity_resolution.judge` (ambiguous-CRN tie-break)

**Deterministic (no LLM)**:

- `intent_router` tier-0 (URL + keyword rules; ~1ms, $0)
- `agency_detection` (recruitment-agency post detector; gap #5)
- `gazette_check` (insolvency notice classifier with safety-valve fallback to generic code)
- `entity_resolution.footer_extractor` (Companies Act §82 boilerplate regex)
- `entity_resolution.local_ch_index` (parquet-backed name index)
- `signal_weights` (per-pillar verdict priors)

The 2026-05-22 simplification round downgraded ~10 agents from Sonnet to Haiku without smoke regressions, and tried regex replacements for `cv_parser` + `ghost_job_jd_scorer`. The regex tiers were reverted 2026-05-23 — both missed too many real-world inputs. Promote back to Sonnet/Opus only with empirical evidence (smoke + at least 3 production samples).

### Rule 8 — Cost discipline
All LLM calls go through `src/askpicky/llm.py` which tracks running cost. The `priority` argument lets non-essential calls refuse below `credits_warn_threshold_usd` (default $20). The free-tier rate limits in ASKPICKY.md §7 are the contract; the cost log validates it.

### Rule 9 — Telegram-native affordances
1. **Streaming Phase 1 progress.** `forward_job` routes each Phase 1 sub-agent's completion through `PhaseOneProgressStreamer.mark_complete()`. Debounced to 1.2s for Telegram's edit rate limit.
2. **File generation for CV and cover letter.** `handle_draft_cv` and `handle_draft_cover_letter` produce both `.docx` (`python-docx`) and `.pdf` (`reportlab`) via `renderers/`, sent via `send_document`. In-chat Markdown is a preview, not the deliverable.

No file generation for `LikelyQuestionsOutput` or `SalaryRecommendation` — chat-only.

### Rule 10 — Content Shield on all untrusted content
Scraped pages, JD text, user messages, recruiter emails, onboarding samples — all untrusted. Before reaching an agent's prompt they pass through `validators/content_shield.py`:
1. **Tier 1 regex** — always runs.
2. **Tier 2 Sonnet classifier** — runs when Tier 1 flagged anything AND the downstream agent is high-stakes (verdict, salary strategist, any Phase 4 generator, draft_reply).

`MALICIOUS` + `REJECT` bails the pipeline with a user-visible message. The Shield is a **precondition for agent invocation**, not a post-hoc check.

---

## Adapter dispatch in `llm.py`

Four execution shapes — pick one per agent:

| Adapter | When | Anthropic primitive |
|---|---|---|
| `call_structured(...)` | Schema-dense outputs, citations attach via `request_search_results` if needed | `output_config.format=tool_use` + adaptive thinking |
| `call_with_citations(...)` | Source-grounded text outputs, every claim cites a doc/gov-field/career-entry | Citations API + `cited_text` blocks |
| `call_with_tools(...)` | Agent needs Web Search, Web Fetch, or Code Execution | tool_use with server-side tools |
| `call_in_session(...)` | Long-running sandboxed work (multi-step investigation, advisor-paired generation) | `client.beta.sessions.*` (Managed Agents) |

All four share one cost-tracking, prompt-caching, banned-phrase post-validator skeleton. Adding a new agent = pick one adapter and document the choice in [AGENTS.md](./AGENTS.md).

---

## Banned phrases (self-audit enforces)

```
passionate, team player, results-driven, synergy, go-getter,
proven track record, rockstar, ninja, thought leader,
game-changer, leverage (as verb), touch base, circle back,
reach out, excited to apply, dynamic, hit the ground running,
self-starter, out of the box, move the needle, deep dive
```

Self-audit also runs the **company-swap test**: any sentence where swapping the target company name wouldn't change the meaning is flagged. Every claim must be specific.

---

## Stack

| Layer | Choice |
|---|---|
| Language | Python 3.11+ |
| LLM | `anthropic` SDK ≥0.97 (Opus 4.7 + Sonnet 4.6, Citations API, Files API, Managed Agents, server-side tools, Batch API) |
| Bot | `python-telegram-bot` v21+, async long-polling |
| Web | React 18 + Vite + TypeScript + TanStack Query + react-router + Tailwind + react-hook-form + zod |
| API | FastAPI + `sse-starlette` |
| Scraping | Playwright async + `trafilatura` + BeautifulSoup; Web Fetch tool fallback |
| Job listings | `python-jobspy` for Indeed/LinkedIn public pages only |
| Reviews | `managed/reviews_investigator.py` (Glassdoor mirrors / archive.org / Reddit / careers-page testimonials) — managed-only path |
| Salary data | ASHE (ONS) parquet lookup + posted JD band |
| Memory | `memory/` — SQLite-backed recorders + `recall()` tool for `salary_strategist`, `draft_reply`, `likely_questions` |
| Gov data | `pandas` + `pyarrow` (parquet) on Sponsor Register, going rates, SOC codes, Appendix Skilled Occupations, ASHE Tables 2/3/15 |
| App data | SQLite + `aiosqlite` |
| Embeddings | `sentence-transformers` (`all-MiniLM-L6-v2`) + `faiss-cpu` |
| Validation | `pydantic` v2 |
| File rendering | `python-docx` + `reportlab` |
| Tests | `pytest` + `pytest-asyncio`; smoke harness in `scripts/smoke_tests/` |

**No LangChain. No LangGraph. No RapidAPI. No Firecrawl. No Playwright Stealth. No OpenAI/Cohere code paths.** Raw Anthropic SDK + the four-adapter dispatch in `llm.py` only. All external data is either direct official APIs (Anthropic, Telegram, Companies House, gov.uk download endpoints) or Playwright/Web Fetch scraping of public pages.

---

## Cuts landed in the 2026-05-22 overhaul

- **LaTeX CV path** — `sub_agents/cv_latex_writer.py`, `cv_latex_repairer.py`, `renderers/cv_latex.py`, both `templates/*.tex.jinja`, the `LatexCVOutput` / `LatexRepairOutput` schemas, the `cv_latex_writer` / `cv_latex_repairer` content-shield entries.
- **Multi-provider CV tailor** — `sub_agents/cv_tailor_multi_provider.py`, `llm_providers.py`, `ats_routing.py`. Anthropic-only is the canonical path.
- **Legacy jobspy reviews** — `sub_agents/reviews.py`. Managed Agents `reviews_investigator` is mandatory; `ReviewExcerpt` moved to `schemas.py`.
- **Verdict ensemble** — `enable_verdict_ensemble` + `enable_verdict_ensemble_deep_research` flags, the `_v2()` branch in orchestrator. The deep-research session survives — it's now the spec for the premium "Real-time hiring intent verification" feature (ASKPICKY.md §8).
- **`cv_tailor_advisor` managed session** — was a no-op delegate to `cv_tailor_agentic`.
- **Dead config flags** — `enable_1hr_cache_for_batch`, `enable_bot_compaction`, `enable_bot_context_editing`, `enable_managed_reviews_investigator` (now mandatory), `enable_managed_cv_tailor`, `enable_multi_provider_cv_tailor`, `openai_api_key`, `cohere_api_key`, `openai_model_id`, `cohere_model_id`.
- **`new_claude.md`** — discarded alternate direction.
- **`trajec_notes.md`** — superseded by ASKPICKY.md; archived to `docs/history/`.
- **Hackathon framing** — Rule 8's credit-budget framing is now production cost discipline.

---

## Development flow

1. Read [ASKPICKY.md](./ASKPICKY.md) to confirm a feature is in scope (passes the four-question test in §3).
2. Read [AGENTS.md](./AGENTS.md) for the affected agent's prompt + adapter choice.
3. Write the Pydantic I/O first, then the agent prompt, then the orchestrator wiring, then the smoke test. In that order.
4. Pick the right adapter for any new agent — the four-shape table above is the only sanctioned dispatch surface.
5. Add a smoke test in `scripts/smoke_tests/`. The `--cheap` tier must stay green.
6. New Managed Agents sessions follow the `managed/company_investigator.py` template exactly.

---

## When stuck

1. Check [ASKPICKY.md](./ASKPICKY.md) §3 (the four-question test). A change failing 2+ should be cut, consolidated, or deferred.
2. Check [AGENTS.md](./AGENTS.md) for the agent's prompt + validation rules.
3. Check [PROCESS.md](./PROCESS.md) for why a decision was made.

**The architecture is stable. Do not redesign. Implement.**
