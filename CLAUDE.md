# CLAUDE.md — Trajectory

> Operating manual for Claude Code working on this repository.
> Read this first, every session.

## What this project is

Trajectory is a Telegram-native personal assistant for UK job seekers. Users onboard once with career history, motivations, deal-breakers, writing-style samples, and urgency context. They then interact in natural language: forward jobs, ask for CV/cover letter drafts, request salary advice, draft recruiter replies, or query their own history.

The differentiators — the things that must be preserved in every design and implementation decision:

1. **UK government data grounding.** The Sponsor Register, SOC going rates, Companies House, and Home Office statistics are the backbone of credibility. Every verdict cites live data.
2. **Writing in the user's voice.** Generated output must sound like the user, not like AI. A style profile derived from their own samples is injected into every generator.
3. **Motivation-aware scoring.** Jobs are scored against the user's stated motivations and deal-breakers, not just salary and role match.
4. **Situational salary advice.** Salary recommendations adapt to the user's urgency, recent rejections, visa timeline, and employment status.
5. **On-demand generation.** Pack components (CV, cover letter, interview questions, salary advice) are produced only when explicitly requested. Nothing is generated on the fly.
6. **Citation discipline.** Every non-trivial claim in any generated output must cite either a verbatim company-page snippet, a specific UK government data field, or a specific user career-entry ID. Invented citations are the worst possible failure.
7. **Never auto-applies.** The tool explicitly does not apply to jobs. The user is always in the loop.

## Problem Statement

**Build From What You Know.** The author has spent 18 months job-searching in the UK on a Graduate visa. Trajectory is built from that lived experience. The visa-holder path is sharper; the UK-resident path is primary by market size.

---

## Hard architectural rules

These apply to every piece of code in this repo. If a change violates one of them, it is wrong.

### Rule 1 — No invented data

No agent may emit a claim without a resolvable citation. The citation validator runs after every generation call and rejects outputs where any claim does not resolve to:

- a scraped URL + verbatim snippet in the research bundle, or
- a specific gov.uk data field (e.g., `sponsor_register.row_id_42891`), or
- a specific `CareerEntry.entry_id` from the user's knowledge store.

When the validator rejects, the orchestrator retries once with feedback, then fails loud. It never ships an unsupported claim.

### Rule 2 — User-type branching is mandatory in the verdict

The verdict agent must check `user_profile.user_type` and apply the correct hard blocker set:

- `uk_resident`: ghost-job, company distress, personal salary floor, market 10th percentile, deal-breaker trigger, motivation misalignment.
- `visa_holder`: all of the above PLUS sponsor register status, SOC threshold, SOC eligibility, nationality grant rate context.

A `GO` verdict with any hard blocker present is a programmatic error — the validator flips it to `NO_GO` and logs.

### Rule 3 — Writing style injection is mandatory in generators

Every Phase 4 generator (CV tailor, cover letter, likely questions, salary strategist scripts, draft_reply) must receive the user's `WritingStyleProfile` in its system prompt. The self-audit checks style conformance.

If `WritingStyleProfile.sample_count < 3`, use the profile as directional only — do not force distinctive phrasing on low-confidence data.

### Rule 4 — Parallel fan-out where it applies

Phase 1 research (8 sub-agents) and `full_prep` (4 Phase 4 generators) must run in parallel via `asyncio.gather` or Managed Agents multi-agent coordination. Serial execution is a performance bug, not an acceptable fallback, unless Managed Agents beta is actively failing.

### Rule 5 — Structured output everywhere

Every LLM call returns strict Pydantic-validated JSON. No free-form prose outputs from sub-agents. The orchestrator composes final user-facing messages from structured data.

### Rule 6 — On-demand, not on-the-fly

`forward_job` runs Phase 1 and verdict, then STOPS. It does not generate a pack. Pack components are triggered by separate intents (`draft_cv`, `draft_cover_letter`, `salary_advice`, `predict_questions`, `draft_reply`) or by the aggregate `full_prep` intent.

### Rule 7 — Nothing cheaps out on Opus 4.7 for quality-critical reasoning

The "Opus 4.7 Use" judging criterion is 25% of the score. Default Opus 4.7 (xhigh effort) for:

- Intent router
- Verdict
- Question designer
- STAR polisher
- Writing style extractor
- Self-audit
- Salary strategist
- Ghost-job JD scorer
- All Phase 4 generators

Sonnet 4.6 only for:

- JD extraction from scraped pages
- Scrape content summarisation
- Simple formatting/reshaping tasks

### Rule 8 — Credits are for runtime, not coding help

The $500 Anthropic credits fund the product's runtime API calls. Budget aggressively:

- ~$100 for build-time prompt iteration (expect 15–25 full pipeline runs)
- ~$30 for demo recording
- ~$80 reserve for judge testing
- ~$290 remaining buffer

Do not artificially downgrade to Sonnet to save credits on quality-critical agents.

### Rule 9 — Telegram-native affordances must match the demo promise

Two affordances are not optional polish — they are architectural:

1. **Streaming Phase 1 progress.** The `forward_job` handler MUST use `asyncio.as_completed` (not `gather`) and edit the in-progress Telegram message each time a sub-agent resolves. The bot's `bot/progress_stream.py` module wraps this with a 1.2s debounce for Telegram's edit rate limit. A batch-complete "here are all 8 results at once" response is a regression — the demo video promises progressive reveals and the real bot must deliver them.

2. **File generation for CV and cover letter.** `handle_draft_cv` and `handle_draft_cover_letter` MUST produce both a `.docx` (via `python-docx`) and a `.pdf` (via `reportlab`) through the `renderers/` package, and the bot MUST send both via `send_document` alongside any chat-bubble preview. In-chat Markdown is a preview, not the deliverable. The user's goal is to attach a real file to a real application — the product must close that loop.

No file generation for `LikelyQuestionsOutput` or `SalaryRecommendation` — those live better as scrollable chat content.

---

## Stack

| Layer | Choice | Reason |
|-------|--------|--------|
| Language | Python 3.11 | Project default, strong async story |
| LLM | `anthropic` SDK + `managed-agents-2026-04-01` beta header | Direct control over parallel fan-out |
| Bot | `python-telegram-bot` v21, async long-polling | Long-polling avoids webhook infra for the demo |
| Scraping | Playwright async + `trafilatura` + BeautifulSoup | Playwright for dynamic sites, trafilatura for clean text extraction |
| Job listings | `python-jobspy` for Indeed/Glassdoor only | LinkedIn uses official Sign-In With LinkedIn |
| Data (gov) | `pandas` + `pyarrow` (parquet) | Fast lookup, immutable at runtime |
| Data (app) | SQLite + `sqlalchemy` + `aiosqlite` | No infra burden; migratable to Postgres later |
| Embeddings | `sentence-transformers` (`all-MiniLM-L6-v2`) + `faiss-cpu` | Local, fast, 384-dim |
| Validation | `pydantic` v2 | Every LLM I/O goes through it |
| Dashboard | `streamlit` | Single-page history view, fast to ship |
| File rendering | `python-docx` + `reportlab` | CV/cover letter as downloadable .docx and .pdf |
| Tests | `pytest` + `pytest-asyncio` | Light — demo first |

**No LangChain.** Raw SDK + `asyncio.gather` gives full control over sub-agent prompts and is cleaner for the Opus 4.7 parallel pattern.

---

## Managed Agents integration

Trajectory uses Managed Agents for two blocks:

1. **Phase 1 research** — wrapped as a single Managed Agents session. Benefits: sandboxed tool execution, tracing, checkpointing. The 8 sub-agents run inside via `asyncio.gather`.
2. **`full_prep` Phase 4 fan-out** — second Managed Agents session. Same pattern.

Everything else uses the plain Messages API (interactive, latency-sensitive).

**2-hour cutoff rule:** if Managed Agents beta is flaking (auth issues, session-create failures, inconsistent outputs), spend no more than 2 hours debugging. Rip it out. Use plain Messages API + `asyncio.gather` for those phases. Log the decision in the repo README.

Research preview access for multi-agent coordination is **not** assumed. The single-agent Managed Agents API is sufficient.

---

## Directory layout

```
trajectory/
├── CLAUDE.md                       # this file
├── ARCHITECTURE.md                 # full system design (sibling reference)
├── AGENTS.md                       # all agent prompt specs
├── SCHEMAS.md                      # Pydantic model catalogue
├── PROJECT_STRUCTURE.md            # file list and responsibilities
├── PROCESS.md                      # design decision log
├── SUBMISSION.md                   # video script / description / checklist
├── CLAUDE_DESIGN_PLAYBOOK.md       # visual production guide
├── README.md                       # user-facing, written before submission
├── LICENSE                         # MIT
├── pyproject.toml
├── .env.example
├── .gitignore
│
├── data/
│   ├── raw/                        # fetched gov data CSVs, PDFs
│   └── processed/                  # parquet files for fast lookup
│
├── scripts/
│   ├── fetch_gov_data.py           # downloads Sponsor Register, going rates, SOC codes
│   └── rebuild_embeddings.py       # rebuilds FAISS index from CareerEntry table
│
├── src/trajectory/
│   ├── __init__.py
│   ├── config.py                   # pydantic-settings for env vars
│   ├── schemas.py                  # all Pydantic models (see SCHEMAS.md)
│   ├── storage.py                  # SQLite + FAISS + session persistence
│   ├── llm.py                      # Anthropic SDK wrappers + Managed Agents
│   ├── orchestrator.py             # top-level pipeline coordination
│   │
│   ├── sub_agents/
│   │   ├── company_scraper.py
│   │   ├── companies_house.py
│   │   ├── reviews.py
│   │   ├── red_flags.py
│   │   ├── ghost_job_detector.py
│   │   ├── salary_data.py
│   │   ├── sponsor_register.py
│   │   ├── soc_check.py
│   │   ├── verdict.py
│   │   ├── question_designer.py
│   │   ├── star_polisher.py
│   │   ├── style_extractor.py
│   │   ├── self_audit.py
│   │   ├── salary_strategist.py
│   │   ├── intent_router.py
│   │   ├── cv_tailor.py
│   │   ├── cover_letter.py
│   │   ├── likely_questions.py
│   │   └── draft_reply.py
│   │
│   ├── bot/
│   │   ├── app.py                  # python-telegram-bot entry point
│   │   ├── handlers.py             # message handlers per intent
│   │   ├── onboarding.py           # conversational onboarding flow
│   │   ├── formatting.py           # render structured outputs as Telegram messages
│   │   └── progress_stream.py      # streams Phase 1 sub-agent completion via message edits
│   │
│   ├── renderers/                  # structured output -> downloadable file
│   │   ├── __init__.py
│   │   ├── cv_docx.py              # python-docx renderer for CVOutput
│   │   ├── cv_pdf.py               # reportlab renderer for CVOutput
│   │   ├── cover_letter_docx.py    # python-docx renderer for CoverLetterOutput
│   │   └── cover_letter_pdf.py     # reportlab renderer for CoverLetterOutput
│   │
│   ├── validators/
│   │   ├── citations.py            # citation resolution & verification
│   │   ├── banned_phrases.py       # cliché detection
│   │   └── schema_retry.py         # retry-with-feedback on invalid Pydantic output
│   │
│   └── dashboard/
│       └── app.py                  # Streamlit session history UI
│
├── tests/
│   ├── test_citations.py
│   ├── test_ghost_job_combination.py
│   ├── test_verdict_branching.py
│   └── fixtures/
│       └── sample_research_bundle.json
│
└── .claude/
    └── agents/                     # if using Claude Code subagent files
        ├── verdict.md
        ├── question_designer.md
        └── (one per sub_agent)
```

---

## Development flow

When extending this codebase, Claude Code follows this order:

1. **Read AGENTS.md** to find the affected agent's spec. Do not invent prompts from scratch — the specs are the source of truth.
2. **Read SCHEMAS.md** before touching any data flowing between modules. Pydantic models in this project are contracts, not hints.
3. **Write the Pydantic I/O first**, then the agent prompt, then the orchestrator wiring, then the test. In that order.
4. **Never skip the citation validator.** If a generator is added that doesn't produce verifiable claims, add its outputs to the validator's closed set of acceptable citation targets.
5. **Never broaden banned_phrases silently.** If a new cliché pattern is added, log it and add a test case.

---

## Citation discipline (detail)

Citations are the moat. Every generated claim must resolve.

**Citation types:**

```python
class Citation(BaseModel):
    kind: Literal["url_snippet", "gov_data", "career_entry"]
    # for url_snippet:
    url: str | None
    verbatim_snippet: str | None   # must match scraped text
    # for gov_data:
    data_field: str | None         # e.g. "sponsor_register.status"
    data_value: str | None         # e.g. "A_RATED"
    # for career_entry:
    entry_id: str | None
```

**Validation loop (`validators/citations.py`):**

```
for each claim in generated output:
    c = claim.citation
    match c.kind:
        case "url_snippet":
            if c.verbatim_snippet not in research_bundle.scraped_pages[c.url].text:
                reject
        case "gov_data":
            if resolve_gov_field(c.data_field) != c.data_value:
                reject
        case "career_entry":
            if not career_store.exists(c.entry_id):
                reject
```

Rejections trigger a single retry with `validator_feedback` in the regeneration prompt. A second rejection fails loud with a user-facing fallback: `"I couldn't produce a well-grounded answer for this. Try asking in a different way, or give me more samples."`

---

## Banned phrases (enforced in self-audit)

These appear in no final output. The self-audit agent flags them for rewrite:

```
passionate, team player, results-driven, synergy, go-getter,
proven track record, rockstar, ninja, thought leader,
game-changer, leverage (as verb), touch base, circle back,
reach out, excited to apply, dynamic, hit the ground running,
self-starter, out of the box, move the needle, deep dive
```

The self-audit also runs the **company-swap test**: any sentence where swapping the target company name wouldn't change the meaning is flagged. Every claim must be specific to this company, not boilerplate.

---

## Testing strategy

Demo quality outranks test coverage. That said:

- **Citation validator tests are required.** False negatives here kill the moat.
- **Verdict branching tests are required.** User-type rules must not silently break.
- **Ghost-job signal combination tests are required.** Combinatorial logic is easy to get wrong.
- Everything else: skip unless a bug bites twice.

---

## Things this codebase does not do

Do not add any of the following without explicit scope approval:

- Auto-applying to jobs (philosophically off-limits, permanently)
- Writing code for the user's applications (a job search tool, not a coding tool)
- LinkedIn scraping — use Sign-In With LinkedIn only
- Storing raw chat transcripts indefinitely — only structured `CareerEntry` rows persist
- Multi-tenant authentication for the demo — single-user Telegram flow is sufficient
- Postgres — SQLite is fine through at least the first 100 users

---

## Credits check — before any LLM call

All LLM calls go through `src/trajectory/llm.py`. That module maintains a running credit estimate based on input/output tokens. If `remaining_credits < 20` USD, the wrapper logs a warning and refuses calls classified as non-essential (every call above `priority=CRITICAL`).

Demo recording and submission day operate in `priority=CRITICAL` mode — all calls go through.

---

## When stuck

The project author (Kene) has been iterating on this design for hours. If something in the implementation feels ambiguous:

1. Check AGENTS.md for the relevant agent's prompt and validation rules.
2. Check SCHEMAS.md for the Pydantic contract.
3. Check PROCESS.md for why a decision was made.
4. If still ambiguous, default to the behaviour that preserves the differentiators listed at the top of this file.

**The architecture is stable. Do not redesign. Implement.**