# Trajectory

A dual-surface personal assistant for UK job seekers — **React web app** for deep work and **Telegram bot** for on-the-go. Forward a job URL, get an honest verdict grounded in live UK government data, then ask for a tailored CV, cover letter, salary strategy, or interview prep on demand.

Built by someone who spent 18 months job-searching in the UK on a Graduate visa. Every feature exists because a real information asymmetry existed.

---

## What it does

**Forward a job → instant verdict.**
Trajectory runs 8 parallel research checks, combines them into a GO / NO_GO decision, and explains exactly why — with citations you can click.

**Asks three targeted questions before generating anything.**
Rather than producing a generic pack, it asks questions designed around the specific role's gaps: what's missing in your background relative to this JD, what the company's culture signals suggest you need to address, what the salary situation demands.

**Writes in your voice, not AI voice.**
During onboarding you provide 3–5 writing samples. Every generated output — CV bullets, cover letter paragraphs, salary scripts — passes through your extracted style profile and a self-audit that rejects AI clichés.

**Adapts salary advice to your actual situation.**
Opening number, floor, and negotiation scripts adjust to your urgency level, recent rejection count, visa timeline, and employment status. A visa holder with 4 months to expiry negotiates differently than someone employed and patient.

**Never auto-applies.** Philosophically off-limits. The user is always in the loop.

**Optional Managed Agents integration.** For stateful web investigation, Trajectory includes a sandboxed company investigator that runs inside a Claude Managed Agents session — Claude chooses which company pages to fetch based on what each page reveals, instead of running a fixed discovery list. Set `enable_managed_company_investigator=true` in your environment to opt in. See `src/trajectory/managed/company_investigator.py`.

---

## Two surfaces, one orchestrator

| Surface | Best for | What you get |
| --- | --- | --- |
| **Web** (Vite + React) | Desktop. Onboarding, session review, pack editing. | Onboarding wizard, dashboard with live Phase 1 streaming over Server-Sent Events, per-session detail pages with evidence + pack generators + downloadable files. |
| **Telegram bot** | Mobile. Quick "should I apply?" checks. | Forward a URL, get the verdict + pack as chat messages and document attachments. Onboarding lives on the web — new users get redirected. |

Both surfaces share a single FastAPI orchestrator, a 16-agent Phase 1 pipeline, and a SQLite + FAISS state store. A transport-agnostic `ProgressEmitter` protocol (`src/trajectory/progress/`) lets the same orchestrator stream progress over Telegram message edits or SSE without duplicating business logic — a new surface (Slack, CLI, etc.) only needs a new emitter implementation (~50 lines).

The full dual-surface design rationale lives in [MIGRATION_PLAN.md](MIGRATION_PLAN.md), including ADRs for web-primary scope, the `ProgressEmitter` abstraction, and ephemeral client-side onboarding state.

---

## Checks run on every job

| Check | What it catches |
| ----- | --------------- |
| Ghost-job detector | Stale posting + not on careers page + vague JD + company distress |
| Sponsor Register | Whether the employer holds a Skilled Worker licence (visa holders) |
| SOC threshold | Whether the offered salary clears the going rate for the role's SOC code |
| Companies House | Dissolution, administration, overdue filings, wind-up resolutions |
| Salary benchmarking | Offered vs. personal floor vs. market 10th percentile |
| Deal-breaker scan | Flags any user-stated deal-breaker triggered by the JD |
| Motivation fit | Scores each stated motivation against the JD and company research |
| Red flags | Layoffs, lawsuits, Glassdoor CEO approval, review patterns |

Hard blockers force a NO_GO regardless of everything else. Every claim cites a verbatim snippet, a specific gov.uk field, or a specific entry from your career history.

---

## What you get on request

| Command | Output |
| ------- | ------ |
| `draft_cv` | Tailored CV as `.docx` + `.pdf`, bullets grounded in your career entries |
| `draft_cover_letter` | Cover letter as `.docx` + `.pdf`, written in your voice |
| `salary_advice` | Opening number, floor, ceiling, and four negotiation scripts |
| `predict_questions` | 8–12 likely interview questions with strategy notes per question |
| `draft_reply` | Short and long variants of a recruiter reply |
| `full_prep` | All four generators in parallel |

---

## Architecture

```text
┌──────────────────┐         ┌──────────────────┐
│  Telegram client │         │   Web (Vite +    │
│     (mobile)     │         │    React, SSE)   │
└────────┬─────────┘         └────────┬─────────┘
         │ long-poll                  │ HTTP + SSE
         ▼                            ▼
┌──────────────────┐         ┌──────────────────┐
│   bot/app.py     │         │   api/app.py     │
│   handlers       │         │   routes         │
└────────┬─────────┘         └────────┬─────────┘
         │    TelegramEmitter │ SSEEmitter
         └──────────┬─────────┘
                    ▼
        ┌───────────────────────────┐
        │ orchestrator.py           │
        │ ProgressEmitter protocol  │
        │ sub_agents/ (16 agents)   │
        │ validators/ + renderers/  │
        └───────────┬───────────────┘
                    ▼
        ┌───────────────────────────┐
        │ SQLite + FAISS + files    │
        └───────────────────────────┘
```

**Phase 1 — 8 parallel sub-agents** (JD extraction, company scraper, Companies House, Sponsor Register, SOC check, ghost-job scorer, salary data, red flags) → **Verdict** (Opus 4.7, xhigh) with citation validation.

**Phase 4 — on-demand pack** (CV tailor, cover letter, likely questions, salary strategist) fans out via `asyncio.gather`.

Progress streams uniformly across both surfaces — Telegram edits a single message, the web app renders a checklist that ticks as each agent completes. Same orchestrator, two transports. All LLM outputs are Pydantic-validated JSON.

---

## Stack

**Backend (Python 3.11, async throughout):**

- **Anthropic SDK** — Opus 4.7 (quality-critical reasoning) + Sonnet 4.6 (extraction)
- **FastAPI + uvicorn + sse-starlette** — web surface
- **python-telegram-bot v21** — Telegram surface (async long-polling)
- **Playwright + trafilatura + BeautifulSoup** — web scraping
- **python-jobspy** — public-page job listing aggregation (Indeed, LinkedIn)
- **pandas + pyarrow** — Sponsor Register, going rates, SOC codes, ASHE Tables 2/3/15 (parquet)
- **SQLite + aiosqlite** — sessions, career entries, cost log
- **sentence-transformers + FAISS** — semantic retrieval over career history
- **python-docx + reportlab** — CV and cover letter file generation
- **Streamlit** — legacy session history dashboard
- **Pydantic v2** — every LLM input and output

**Frontend (`frontend/`):**

- **Vite + React 18 + TypeScript + Tailwind CSS** — build + UI
- **shadcn/ui** primitives (copied into `src/components/ui/`, not installed)
- **TanStack Query** — server state
- **React Hook Form + Zod** — form validation
- **React Router** — client routing

No RapidAPI. No closed-source API marketplace wrappers. All salary data from ONS (ASHE) and open public sources.

---

## Setup

### Prerequisites

- Python 3.11+ and Node 20+
- A Telegram bot token ([BotFather](https://t.me/botfather))
- Anthropic API key
- Companies House API key (free — [register here](https://developer.company-information.service.gov.uk/))

### Install

```bash
git clone https://github.com/yourusername/trajectory.git
cd trajectory

# Backend
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
playwright install chromium

# Frontend
cd frontend && npm install && cd ..
```

### Configure

```bash
cp .env.example .env
# Fill in your keys
```

```env
ANTHROPIC_API_KEY=sk-ant-...
TELEGRAM_BOT_TOKEN=...
COMPANIES_HOUSE_API_KEY=...

# Dual-surface identity — set to your Telegram numeric user id
# so both surfaces resolve to the same user_profiles row.
DEMO_USER_ID=123456789

# Web surface (defaults shown)
API_PORT=8000
WEB_ORIGIN=http://localhost:5173
WEB_URL=http://localhost:5173
```

### Fetch UK government data

```bash
python scripts/fetch_gov_data.py
```

Downloads the Sponsor Register, Skilled Worker going rates, Appendix Skilled Occupations, SOC 2020 codes, and ASHE Tables 2/3/15 (ONS annual earnings percentiles). Takes ~2 minutes on first run. Rerun to refresh data.

### Run

Three processes — all talk to the same SQLite file + FAISS index:

```bash
# Terminal 1 — Telegram bot
python -m trajectory.bot.app

# Terminal 2 — FastAPI (web backend)
./scripts/run_api.sh

# Terminal 3 — Vite (web frontend)
./scripts/run_web.sh
```

Then visit `http://localhost:5173` in the browser, or `/start` your bot on Telegram. New users are redirected from Telegram to the web onboarding wizard — once the profile exists, both surfaces share it.

**Legacy Streamlit dashboard** (session history — superseded by the web app, kept for quick inspection):

```bash
streamlit run src/trajectory/dashboard/app.py
```

---

## Development

```bash
# Backend
pytest                    # ~200 tests, including SSE end-to-end integration
ruff check src/ tests/    # lint

# Frontend
cd frontend
npm run lint              # tsc -b --noEmit
npm run build             # vite build
```

Key suites:

- `tests/test_citations.py` — citation resolution (verbatim match, gov field path, career entry existence)
- `tests/test_ghost_job_combination.py` — signal combination logic
- `tests/test_verdict_branching.py` — user-type hard blocker rules (visa holder vs. UK resident)
- `tests/test_progress_emitter.py` — ProgressEmitter protocol + NoOp / SSE / Telegram implementations
- `tests/test_api_forward_job_integration.py` — end-to-end SSE with the real orchestrator and mocked sub-agents

### Key architectural rules

1. **No invented data.** Every claim resolves to a scraped URL + snippet, a gov.uk field, or a career entry ID.
2. **User-type branching is mandatory.** Visa holders get the sponsor/SOC blocker set; UK residents do not.
3. **Writing style injection is mandatory.** Every Phase 4 generator receives the user's `WritingStyleProfile`.
4. **Parallel fan-out is mandatory.** Phase 1 and `full_prep` run in parallel. Serial execution is a bug.
5. **Structured output everywhere.** All LLM calls return Pydantic-validated JSON.
6. **On-demand, not on-the-fly.** `forward_job` runs Phase 1 + verdict and stops. Pack components are user-triggered.
7. **Opus 4.7 for quality-critical reasoning.** Sonnet 4.6 only for extraction and summarisation.

Full rules and rationale: [CLAUDE.md](CLAUDE.md)

---

## What it doesn't do

- Auto-apply (philosophically off-limits, permanently)
- LinkedIn scraping (Sign-In With LinkedIn only)
- Store raw chat transcripts (only structured career entries persist)
- Multi-tenant auth (single-user for the demo)

---

## Licence

MIT — see [LICENSE](LICENSE).
