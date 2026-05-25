# CLAUDE.md — AskPicky

> Operating manual for Claude Code working on this repo.
> Read this first, every session.
> For **what AskPicky is** (positioning, free/premium split, roadmap), read [ASKPICKY.md](./ASKPICKY.md). That document is canonical and supersedes anything here on contradiction.

*Last updated 2026-05-24 — multi-provider routing (DeepSeek V4 Flash/Pro, Anthropic, OpenAI), 6-label verdict taxonomy, Firecrawl anti-bot fallback, LangGraph orchestrator wrapper, benchmark harness + CI dashboard.*

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

### Rule 2 — 6-label verdict taxonomy
The verdict agent produces one of six labels: STRONG_GO, GO, TRY_ANYWAY, ASK_FIRST, PASS, BLOCKED. Hard blockers (company dissolved, Gazette insolvency, SOC ineligible, deal-breaker triggered) force BLOCKED. Negotiable blockers (sponsor not listed, salary below floor) downgrade to TRY_ANYWAY or ASK_FIRST.

Verdict.entropy_norm (0-1) measures evidence spread across signal pillars. Motivation mismatch is a StretchConcern, not a hard blocker. A STRONG_GO or GO with any hard blocker is a programmatic error — the guard flips it.

### Rule 3 — Writing-style injection in every generator
Every Phase 4 generator (CV tailor, cover letter, likely questions, salary strategist, draft_reply) receives the user's `WritingStyleProfile` in its system prompt. If `sample_count < 3`, the profile is directional only.

### Rule 4 — Parallel fan-out where it applies
Phase 1 research (9 sub-agents) and `full_prep` (4 Phase 4 generators) run in parallel via `asyncio.gather`. Serial execution is a performance bug.

### Rule 5 — Structured output everywhere
Every LLM call returns strict Pydantic-validated JSON. No free-form prose from sub-agents.

### Rule 6 — On-demand, not on-the-fly
`forward_job` runs Phase 1 + verdict and STOPS. Pack components are triggered by separate intents (`draft_cv`, `draft_cover_letter`, `salary_advice`, `predict_questions`, `draft_reply`) or by `full_prep`.

### Rule 7 — Model routing: cheapest that meets the bar; DeepSeek default

Routing is configured in `config.py::agent_model_map`. The provider abstraction in `llm.py` dispatches to Anthropic, DeepSeek (Anthropic-compatible endpoint), or OpenAI (native chat completions) based on the agent name.

**DeepSeek V4 Pro** ($0.435/$0.87 Mtok) — quality-critical agents:
- `verdict`, `self_audit`, `cover_letter`, `cv_tailor`, `salary_strategist`

**DeepSeek V4 Flash** ($0.14/$0.28 Mtok) — extraction, routing, triage, style:
- `intent_router`, `triage`, `jd_extractor`, `company_scraper_summariser`, `red_flags`, `ghost_job_jd_scorer`, `interview_questions`, `star_polisher`, `style_extractor`, `onboarding_parser`, `cv_parser`, `draft_reply`, `content_shield_tier2`

**Anthropic** (optional — used only when DeepSeek is unavailable):
- `offer_analyst`, managed agent sessions (`company_investigator`, `verdict_deep_research`, etc.)

**OpenAI** (benchmarks only, not production routing)

To swap a provider: edit `config.py::agent_model_map`, rebuild Docker. No code changes needed.

### Rule 8 — Cost discipline
All LLM calls go through `src/askpicky/llm.py` which tracks running cost. The `priority` argument lets non-essential calls refuse below `credits_warn_threshold_usd` (default $20). The free-tier rate limits in ASKPICKY.md §7 are the contract; the cost log validates it.

### Rule 9 — Content Shield on all untrusted content
Scraped pages, JD text, user messages, recruiter emails, onboarding samples — all untrusted. Before reaching an agent's prompt they pass through `validators/content_shield.py`:
1. **Tier 1 regex** — always runs.
2. **Tier 2 Sonnet classifier** — runs when Tier 1 flagged anything AND the downstream agent is high-stakes (verdict, salary strategist, any Phase 4 generator, draft_reply).

`MALICIOUS` + `REJECT` bails the pipeline with a user-visible message. The Shield is a **precondition for agent invocation**, not a post-hoc check.

---

## Adapter dispatch in `llm.py`

Three provider backends share one cost-tracking, prompt-caching, banned-phrase post-validator skeleton:

| Adapter | When | Mechanism |
|---------|------|-----------|
| Anthropic-compatible (DeepSeek + Anthropic) | All production agents | `client.messages.create` with `tool_use` forced output |
| OpenAI native | Benchmarks, optional routing | `chat.completions.create` with `response_format=json_schema` |

Adding a new agent = pick one provider tier in `config.py::agent_model_map` and document the choice in [AGENTS.md](./AGENTS.md).

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
|-------|--------|
| Language | Python 3.12+ |
| LLM | Multi-provider via `llm.py`: DeepSeek V4 Flash/Pro (Anthropic-compatible endpoint), Anthropic (Opus 4.7, Sonnet 4.6, Haiku 4.5), OpenAI (GPT-5.4, primary verdict) |
| Orchestration | `orchestrator.py` (imperative) + `langgraph_orchestrator.py` (opt-in StateGraph wrapper, checkpointed state) |
| Web | React 18 + Vite + TypeScript + TanStack Query + react-router + Tailwind |
| API | FastAPI + `sse-starlette` |
| Scraping | Playwright async + `trafilatura` + BeautifulSoup; Firecrawl fallback for anti-bot hosts (Glassdoor, Indeed, LinkedIn) |
| Gov data | `pandas` + `pyarrow` (parquet) on Sponsor Register, going rates, SOC codes, ASHE |
| App data | SQLite + `aiosqlite` |
| Embeddings | `sentence-transformers` (`all-MiniLM-L6-v2`) + `faiss-cpu`; pre-downloaded in Dockerfile; `HF_HOME=/data/huggingface` |
| Validation | `pydantic` v2 |
| File rendering | `python-docx` + `reportlab` |
| Benchmarking | `scripts/benchmarks/run.py` — 5 task × provider matrix; `--mock` for CI, live for quality comparison |
| CI | `.github/workflows/benchmarks.yml` — scheduled + workflow_dispatch |
| Tests | `pytest` + `pytest-asyncio`; smoke harness in `scripts/smoke_tests/` |

---

## Cuts landed in the 2026-05-22/23 overhaul

- **LaTeX CV path** — removed.
- **Multi-provider CV tailor v1** — replaced by unified `agent_model_map` routing in `config.py`.
- **Verdict ensemble** — removed; single-verdict path is canonical.
- **Binary GO/NO_GO verdict** — replaced by 6-label VerdictLabel taxonomy.
- **Cohere provider** — dead code, no integration. Removed from storage.py pricing and .env.
- **Hardcoded Anthropic routing** — replaced by per-agent provider/model map.
- **HANDOFF.md, SKILL.md, legacy entity_resolution stores** — archived or restored as needed.

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
