# Trajectory

A Telegram-native personal assistant for UK job seekers. Forward a job URL, get an honest verdict grounded in live UK government data — then ask for a tailored CV, cover letter, salary strategy, or interview prep on demand.

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
User message (Telegram)
        │
        ▼
  Intent Router (Opus 4.7)
        │
  ┌─────┴──────┐
  │            │
forward_job  pack generators
  │            │
  ▼            ▼
Phase 1 (8 parallel sub-agents)    Phase 4 (on-demand)
  - JD extraction (Sonnet)           - CV tailor (Opus)
  - Company scraper (Sonnet)         - Cover letter (Opus)
  - Companies House                  - Likely questions (Opus)
  - Sponsor Register (parquet)       - Salary strategist (Opus)
  - SOC check (parquet)
  - Ghost-job scorer (Opus)
  - Salary data
  - Red flags (Opus)
        │
        ▼
  Verdict (Opus 4.7, xhigh)
  + citation validation
  + GO/NO_GO with hard blockers
```

Phase 1 runs via `asyncio.as_completed` — the bot edits a single Telegram message in near-real-time as each check resolves. Phase 4 `full_prep` fans out in parallel via `asyncio.gather`.

All LLM outputs are Pydantic-validated JSON. No free-form prose from sub-agents.

---

## Stack

- **Python 3.11** — async throughout
- **Anthropic SDK** — Opus 4.7 (quality-critical reasoning) + Sonnet 4.6 (extraction)
- **python-telegram-bot v21** — async long-polling
- **Playwright + trafilatura + BeautifulSoup** — web scraping
- **pandas + pyarrow** — Sponsor Register, going rates, SOC codes (parquet)
- **SQLite + aiosqlite** — sessions, career entries, cost log
- **sentence-transformers + FAISS** — semantic retrieval over career history
- **python-docx + reportlab** — CV and cover letter file generation
- **Streamlit** — session history dashboard
- **Pydantic v2** — every LLM input and output

---

## Setup

### Prerequisites

- Python 3.11+
- A Telegram bot token ([BotFather](https://t.me/botfather))
- Anthropic API key
- Companies House API key (free — [register here](https://developer.company-information.service.gov.uk/))
- RapidAPI key (Glassdoor salary data — optional, degrades gracefully)

### Install

```bash
git clone https://github.com/yourusername/trajectory.git
cd trajectory
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
playwright install chromium
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
RAPIDAPI_KEY=...
```

### Fetch UK government data

```bash
python scripts/fetch_gov_data.py
```

Downloads the Sponsor Register, Skilled Worker going rates, Appendix Skilled Occupations, and SOC 2020 codes. Takes ~60 seconds. Rerun whenever you want fresh data.

### Run

```bash
python -m trajectory.bot.app
```

Send `/start` to your bot on Telegram.

**Dashboard** (session history):

```bash
streamlit run src/trajectory/dashboard/app.py
```

---

## Development

```bash
pytest                    # run tests
ruff check src/ tests/    # lint
```

The required test suite covers:

- `tests/test_citations.py` — citation resolution (verbatim match, gov field path, career entry existence)
- `tests/test_ghost_job_combination.py` — signal combination logic (2 HARD → LIKELY_GHOST HIGH, etc.)
- `tests/test_verdict_branching.py` — user-type hard blocker rules (visa holder vs. UK resident)

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
