# AskPicky

> **Verify roles before you apply.**
> UK-first, visa-aware, agent-powered job search assistant. Forward a job URL, get a cited verdict grounded in live UK government data, then ask for a tailored CV, cover letter, salary strategy, or interview prep on demand.

AGPL-3.0 · Python 3.11+ · Anthropic SDK + first-party Citations · No auto-apply, ever.

*Last updated 2026-05-22 23:30 BST · HEAD `60add03` (Close gap #7: explicit per-pillar signal weights as verdict priors). All 9 architecture gaps from the 2026-05-17 review now closed — see [HANDOFF.md](./HANDOFF.md) §4.*

---

## What it does

**Forward a job → cited verdict.**
A mix of deterministic + LLM checks run in parallel against the JD, the company, and live UK government data (Companies House profile + officers + charges + PSC, The Gazette insolvency notices, Sponsor Register, SOC, ASHE). Picky combines them into a GO / NO_GO decision and explains exactly why — every load-bearing claim cites a verbatim source.

**Visa-aware out of the box.**
Sponsor Register (with fuzzy-match + Splink rescoring), SOC threshold and new-entrant rule, Appendix Skilled Occupations eligibility, Companies House signals. The visa wedge is built in, not bolted on.

**Writes in your voice, not AI voice.**
3–5 writing samples at onboarding plus your uploaded CV feed a `WritingStyleProfile` that's injected into every generator. A self-audit rejects AI clichés and runs a company-swap test — any sentence that would read identically with a different company name gets flagged.

**Adapts salary advice to your situation.**
Opening number, floor, ceiling, and four negotiation scripts adjust to your urgency, recent rejections, visa timeline, employment status, and the role's posted band.

**Tracks what happens after you apply.**
One-tap outcome reporting in Telegram feeds the data network. The more users report, the better the verdicts get at telling you whether a role is worth your time.

**Never auto-applies.** Philosophically off-limits. The user is always in the loop. The spam paradox is real.

---

## Two surfaces, one orchestrator

| Surface | Best for | What you get |
|---|---|---|
| **Web** (Vite + React) | Desktop. Onboarding, session review, pack editing. | Wizard onboarding, dashboard with live Phase 1 SSE streaming, per-session detail pages with citations + pack generators + downloadable files. |
| **Telegram bot** | Mobile. Quick "should I apply?" checks. | Forward a URL, get the verdict + pack as chat messages and document attachments. Day-21 nudge for outcome reporting. |

Both share one FastAPI orchestrator, one 9-agent Phase 1 pipeline (with 7 Anthropic Managed Agents sessions wired in for sandboxed multi-step work), and one SQLite + FAISS state store. A transport-agnostic `ProgressEmitter` protocol (`src/askpicky/progress/`) streams progress over Telegram edits or SSE without duplicating business logic.

---

## Phase 1 checks (run on every forward)

| Check | What it catches |
|---|---|
| Ghost-job detector | Stale posting + not on careers page + vague JD + company distress |
| Sponsor Register | Whether the employer holds a Skilled Worker licence (visa holders) — fuzzy + CRN-aware |
| SOC threshold | Whether the offered salary clears the going rate for the role's SOC code |
| Companies House | Dissolution, administration, overdue filings, wind-up resolutions |
| Salary benchmarking | Offered vs. personal floor vs. market 10th percentile (ASHE) |
| Red flags | Layoffs, lawsuits, Glassdoor patterns, regulatory actions, leaver signals |
| Reviews investigator | Public-page review aggregation (Managed Agents sandbox) |
| JSON-LD pre-LLM extractor | Avoids an Opus call when the page exposes Schema.org JobPosting |
| Company scrape + summariser | Site-wide signal feed for the verdict |

Then the verdict agent reasons over all of it. The Citations API guarantees every quoted snippet is verbatim from the source.

---

## On-demand pack generation

Forwarding doesn't generate a pack — Picky won't burn your credits on a role you haven't decided to pursue. Once you've read the verdict, ask for what you need:

- `draft_cv` → tailored CV as DOCX + PDF
- `draft_cover_letter` → tailored cover letter as DOCX + PDF (Citations-backed)
- `predict_questions` → 8–12 likely interview questions with strategy notes
- `salary_advice` → opening number, floor, ceiling + 4 negotiation scripts
- `draft_reply` → recruiter reply, short and long variants
- `full_prep` → all four in parallel via `asyncio.gather`

---

## Free vs premium

See [ASKPICKY.md](./ASKPICKY.md) §7–§8 for the full split. In short:

**Free** covers the core: full onboarding, verdicts (rate-limited), all visa-specific features, all pack generation, personal memory, application tracker, one-tap outcome reporting.

**Premium** adds:
- Real-time hiring intent verification (live web research)
- Pre-application employer benchmarks (built from the data network)
- Salary defensibility against Home Office rules
- Application autopsy after rejection

Contribute outcomes → earn credits → never need to pay.

---

## Run it locally

```bash
# Backend
python -m venv .venv && . .venv/bin/activate    # or .venv\Scripts\activate on Windows
pip install -e .
pip install -r requirements.txt

# Fetch UK gov data (Sponsor Register, ASHE, SOC codes, Appendix Skilled Occupations)
python scripts/fetch_gov_data.py

# Copy .env.example to .env, fill ANTHROPIC_API_KEY + TELEGRAM_BOT_TOKEN + DEMO_USER_ID
cp .env.example .env

# Web frontend
cd frontend && npm install && npm run dev

# Backend (in another shell)
uvicorn askpicky.api.app:app --reload --port 8000

# Telegram bot (in another shell)
python -m askpicky.bot.app
```

---

## Smoke tests

```bash
# 33 tests, ~5 min, $0 — no LLM calls, must stay green
python -m scripts.smoke_tests.run_all --cheap

# Full live suite (~$5, ~10 min)
python -m scripts.smoke_tests.run_all
```

The cheap suite is the regression net every change has to hold. Each LLM-backed test honours `SMOKE_<NAME>_MOCK=1` for free-iteration.

---

## What's not in here

- Auto-apply (philosophical no, permanently)
- Trust badges for applicants (spam paradox)
- AI-content detection (adversarial, unwinnable)
- Identity verification (different problem)
- Employer-facing ATS (different sales motion)
- LangChain / LangGraph / RapidAPI / Firecrawl (raw Anthropic SDK only)
- Postgres or Redis (SQLite is enough through the first 100 users)

---

## Docs

- [ASKPICKY.md](./ASKPICKY.md) — canonical product definition (free/premium split, roadmap, four-question test)
- [CLAUDE.md](./CLAUDE.md) — operating manual for AI-assisted dev
- [AGENTS.md](./AGENTS.md) — agent prompt inventory + adapter assignments
- [PROCESS.md](./PROCESS.md) — decision log
- [docs/history/](./docs/history/) — superseded planning notes

---

## Licence

AGPL-3.0. Code is open; the aggregated employer-behaviour data network is closed. Contributors sign a CLA — see [CONTRIBUTING.md](./CONTRIBUTING.md) once it exists.
