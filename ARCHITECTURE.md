# ARCHITECTURE.md — Trajectory System Design

> System-level reference. Read this after CLAUDE.md when you need to
> understand *why* the architecture is shaped the way it is.

---

## 1. System diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                    USER (Telegram)                              │
└────────────────────────┬────────────────────────────────────────┘
                         │ natural language / commands
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│  bot/app.py  (python-telegram-bot, async long-polling)          │
│   - Listens on updates                                          │
│   - Per-user session context                                    │
│   - Routes to handlers.py                                       │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│  bot/handlers.py                                                │
│   - Dispatches to onboarding flow OR intent router              │
│   - Formats structured outputs as Telegram messages             │
└──────┬────────────────────────────────────────────────┬─────────┘
       │                                                │
       │ onboarding path                                │ main path
       ▼                                                ▼
┌─────────────────────┐                      ┌──────────────────────┐
│ bot/onboarding.py   │                      │ sub_agents/          │
│  6-topic flow       │                      │  intent_router.py    │
│  + style samples    │                      └──────────┬───────────┘
└──────────┬──────────┘                                 │
           │                                            │
           ▼                                            ▼
┌─────────────────────┐                      ┌──────────────────────┐
│ Writing Style       │                      │  orchestrator.py     │
│ Extractor + Onbd.   │                      │  (per-intent        │
│ Orchestrator        │                      │  pipelines)         │
└──────────┬──────────┘                      └──────┬───┬───────────┘
           │                                        │   │
           └────────────┐                ┌──────────┘   └──────────┐
                        ▼                ▼                         ▼
                  ┌────────────────────────────┐    ┌──────────────────┐
                  │ storage.py                 │    │ Phase 1 / 4      │
                  │  - SQLite (sessions,       │    │ sub-agent        │
                  │    career_entries,         │    │ fan-outs         │
                  │    profiles,               │    │ (asyncio or      │
                  │    style_profiles)         │    │ Managed Agents)  │
                  │  - FAISS (embeddings)      │    └──────────────────┘
                  │  - parquet (gov data)      │
                  └────────────────────────────┘
```

---

## 2. Data flow — `forward_job` end-to-end

```
1. User forwards URL in Telegram.
2. handlers.on_message receives update.
3. intent_router classifies → "forward_job" + extracted job_url.
4. orchestrator.handle_forward_job(user, job_url):
     a. Create Session row.
     b. Phase 1 Managed Agents session start (or asyncio fallback):
        ├─ company_scraper.run(job_url) → CompanyResearch + ExtractedJD
        ├─ companies_house.lookup(company_name) → CompaniesHouseSnapshot
        ├─ reviews.fetch(company_name) → reviews excerpts
        ├─ red_flags.detect(...) → RedFlagsReport
        ├─ ghost_job_detector.score(jd, scraped_pages, ch, age)
        │    → GhostJobAssessment
        ├─ salary_data.fetch(role, location) → SalarySignals
        │
        ├─ (visa_holder only) sponsor_register.lookup(company_name)
        │    → SponsorStatus
        └─ (visa_holder only) soc_check.verify(jd, user) → SocCheckResult
     c. Assemble ResearchBundle.
     d. verdict.generate(research_bundle, user, retrieved_entries)
        → Verdict.
     e. Persist session.phase1_output + session.verdict.
     f. Render verdict as Telegram message(s).
     g. If GO: append "Want me to draft your CV, cover letter, or
        salary advice? Just ask." (no auto-pack)
5. User message handling ends. Awaits next incoming message.
```

---

## 3. Data flow — `draft_cover_letter` (user-triggered, post-verdict)

```
1. User: "Draft me a cover letter for this one."
2. intent_router → "draft_cover_letter" + job_url_ref from most
   recent session.
3. orchestrator.handle_draft_cover_letter:
     a. Load session + its ResearchBundle + Verdict.
     b. If verdict.decision == NO_GO → reply with verdict reasoning,
        stop.
     c. Retrieve top-12 CareerEntries relevant to this JD via FAISS.
     d. Load WritingStyleProfile.
     e. Check: do we have STAR material from a prior Phase 3 session?
        If not, offer to run a 3-question dialogue first.
     f. cover_letter.generate(...) → CoverLetterOutput.
     g. self_audit.run(output, research_bundle, style_profile)
        → SelfAuditReport.
     h. If flags present (and not HARD_REJECT): apply rewrites in
        place, re-audit once.
     i. Render to Telegram.
     j. Persist to session.pack.cover_letter.
```

---

## 4. Data flow — `salary_advice` (standalone intent)

Same as `draft_cover_letter` but calls `salary_strategist.generate(...)`, with the addition that `JobSearchContext` is **computed fresh** from storage (not stored):

```
compute_job_search_context(user_id):
    - urgency_level: derived from:
        * months_until_visa_expiry (if visa holder, <6mo → +weight)
        * recent_rejections_count (last 30d, >3 → +weight)
        * current_employment (UNEMPLOYED + search_duration>6mo → +weight)
        * applications_in_last_30_days (>15 → +weight)
      Weights map to LOW / MEDIUM / HIGH / CRITICAL.
    - other fields read directly from storage.
```

Urgency computation is centralised in `orchestrator.py:compute_urgency()`. Changing the heuristic changes salary advice everywhere — exactly the coupling we want.

---

## 5. Parallelism model

### Phase 1 (the Opus 4.7 showpiece)

```python
# orchestrator.py (simplified sketch — not the implementation)

async def run_phase_1(session, user):
    tasks = [
        company_scraper.run(job_url),
        companies_house.lookup(company_name),
        reviews.fetch(company_name),
        red_flags.detect(...),
        ghost_job_detector.score(...),
        salary_data.fetch(...),
    ]
    if user.user_type == "visa_holder":
        tasks.append(sponsor_register.lookup(company_name))
        tasks.append(soc_check.verify(...))

    results = await asyncio.gather(*tasks, return_exceptions=True)
    # Each result is either the agent's Pydantic output or an exception.
    # Bundle assembler logs failures, continues with partial bundles
    # unless a verdict-critical sub-agent failed.
```

**Managed Agents wrapping:**

```python
async with managed_agents_session(agent_id="phase_1_research") as session:
    result = await session.run(input=ResearchInput(...))
```

The Managed Agents session's tool list is the set of sub-agent primitives plus the gov data readers. Inside, the session uses the same `asyncio.gather` pattern but with tracing and checkpointing by Anthropic's runtime.

**If Managed Agents beta bites** — 2-hour debugging budget, then fall back to plain `asyncio.gather` outside any session wrapper. The orchestrator's interface stays identical; the session context manager becomes a no-op.

### Phase 4 (parallel on `full_prep`, serial on single-intent)

For `full_prep`:
```python
tasks = [
    cv_tailor.generate(...),
    cover_letter.generate(...),
    likely_questions.generate(...),
    salary_strategist.generate(...),
]
results = await asyncio.gather(*tasks)
```

For single-intent calls (`draft_cv`, etc.), only that generator runs. `full_prep` is the second Opus 4.7 parallel showpiece.

---

## 6. Storage — SQLite schema

```sql
CREATE TABLE users (
    user_id         TEXT PRIMARY KEY,
    profile_json    TEXT NOT NULL,      -- serialised UserProfile
    created_at      TIMESTAMP NOT NULL,
    updated_at      TIMESTAMP NOT NULL
);

CREATE TABLE career_entries (
    entry_id        TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    kind            TEXT NOT NULL,
    raw_text        TEXT NOT NULL,
    structured_json TEXT,
    source_session_id TEXT,
    created_at      TIMESTAMP NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);
CREATE INDEX idx_career_entries_user ON career_entries(user_id);
CREATE INDEX idx_career_entries_kind ON career_entries(user_id, kind);

CREATE TABLE writing_style_profiles (
    profile_id      TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    profile_json    TEXT NOT NULL,
    created_at      TIMESTAMP NOT NULL,
    updated_at      TIMESTAMP NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE TABLE sessions (
    session_id      TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    intent          TEXT NOT NULL,
    job_url         TEXT,
    phase1_json     TEXT,               -- ResearchBundle as JSON
    verdict_json    TEXT,               -- Verdict as JSON
    pack_json       TEXT,               -- Pack as JSON, grows over time
    messages_json   TEXT,               -- full chat log (capped at 200)
    created_at      TIMESTAMP NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);
CREATE INDEX idx_sessions_user_created ON sessions(user_id, created_at DESC);

CREATE TABLE scraped_pages_cache (
    -- avoids re-scraping the same URL across sessions
    url             TEXT PRIMARY KEY,
    fetched_at      TIMESTAMP NOT NULL,
    text            TEXT NOT NULL,
    text_hash       TEXT NOT NULL
);
CREATE INDEX idx_scraped_pages_fetched_at ON scraped_pages_cache(fetched_at);

CREATE TABLE llm_cost_log (
    -- tracks credits burn over time
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT,
    agent_name      TEXT NOT NULL,
    model           TEXT NOT NULL,
    input_tokens    INTEGER NOT NULL,
    output_tokens   INTEGER NOT NULL,
    estimated_cost_usd REAL NOT NULL,
    created_at      TIMESTAMP NOT NULL
);
```

Embeddings live in a separate FAISS index on disk (`data/embeddings.faiss`). Each embedding is keyed by `entry_id`. `rebuild_embeddings.py` can reconstruct the index from the `career_entries` table if it corrupts.

---

## 7. Citation resolution — the moat

The citation validator in `validators/citations.py` is the single most important piece of non-LLM code in this repo. Getting it wrong undermines everything.

```python
# Simplified pseudocode

def validate_citation(c: Citation, ctx: ValidationContext) -> bool:
    if c.kind == "url_snippet":
        page = ctx.research_bundle.get_page(c.url)
        if page is None:
            return False
        # Check verbatim (exact string match, case-insensitive whitespace)
        if normalise(c.verbatim_snippet) not in normalise(page.text):
            return False
        return True

    elif c.kind == "gov_data":
        # Parse "sponsor_register.status" → look up on the snapshot
        field_path = c.data_field.split(".")
        value = resolve_path(ctx, field_path)
        return str(value) == c.data_value

    elif c.kind == "career_entry":
        return ctx.career_store.exists(c.entry_id)

    return False


def validate_output(output: BaseModel, ctx: ValidationContext) -> list[str]:
    """Return list of citation IDs that failed to resolve."""
    errors = []
    for citation in extract_all_citations(output):
        if not validate_citation(citation, ctx):
            errors.append(describe_citation(citation))
    return errors
```

The `normalise` function collapses whitespace, lowercases, strips punctuation. The verbatim check is strict on words, lenient on formatting. Exact-match is too brittle.

---

## 8. Model routing — decision table

| Caller | Model | Effort | Reason |
|--------|-------|--------|--------|
| intent_router | Opus 4.7 | xhigh | Misroute is costly to UX |
| verdict | Opus 4.7 | xhigh | Headline judgement call |
| question_designer | Opus 4.7 | xhigh | Quality-critical |
| star_polisher | Opus 4.7 | xhigh | Subtlety + no-invent rule |
| style_extractor | Opus 4.7 | xhigh | Complex pattern extraction |
| onboarding_orchestrator | Opus 4.7 | xhigh | Mapping conversation to schema |
| salary_strategist | Opus 4.7 | xhigh | Money matters |
| cv_tailor | Opus 4.7 | xhigh | Voice + grounding |
| cover_letter | Opus 4.7 | xhigh | Voice + grounding |
| likely_questions | Opus 4.7 | xhigh | Specificity demand |
| draft_reply | Opus 4.7 | xhigh | Voice matters most here |
| self_audit | Opus 4.7 | xhigh | Catches everything upstream missed |
| ghost_job_jd_scorer | Opus 4.7 | xhigh | Subtle signal combination |
| red_flags_detector | Opus 4.7 | xhigh | Legal/reputational stakes |
| company_scraper_summariser | Sonnet 4.6 | medium | Structured extraction |
| jd_extractor | Sonnet 4.6 | medium | Structured extraction |
| citation validator LLM spot-checks | Sonnet 4.6 | medium | Cheap verification |

---

## 9. Error handling philosophy

Three failure modes, three responses:

1. **Transient (network, rate limit, parse error)** — retry with backoff up to 2 times. If still failing, fall back gracefully per agent (e.g., skip that Phase 1 sub-agent, verdict agent notes the gap).

2. **Validation failure (invalid JSON, citation doesn't resolve)** — retry once with validator feedback in the prompt. Second failure → fail loud to the user: "I couldn't produce a well-grounded answer. Try giving me more context or samples."

3. **Data genuinely unavailable (no Glassdoor data for this role, no Companies House record)** — don't retry. Mark `data_gaps` in the output. Downstream agents handle the gap honestly (e.g., salary strategist asks the recruiter to share their band first).

Never swallow errors silently. Every failure is logged with session_id for debug.

---

## 10. Concurrency & rate limits

- Anthropic rate limits on Opus 4.7: respect them. The `llm.py` wrapper implements a token-bucket rate limiter.
- Companies House API: 600 requests per 5 minutes. More than enough.
- RapidAPI (Glassdoor/Levels): per subscription. Budget ~20 calls.
- `python-jobspy` on Indeed: aggressive rate limits. Cache aggressively.
- LinkedIn official Sign-In: user-action only, no rate limit worry.
- Telegram bot long-polling: single connection per bot instance; no concurrency concern.

Per-session parallelism is capped at 10 in-flight LLM calls to avoid hammering Anthropic and blowing credits on a runaway session.

---

## 11. Deployment

For the hackathon demo, Trajectory runs locally on the author's laptop:

1. `uv run python -m trajectory.bot.app` — starts the Telegram bot (long-polling).
2. `uv run streamlit run src/trajectory/dashboard/app.py` — session history dashboard.
3. Data stored in `./data/` directory.

No public deployment required. The demo video's real-footage segment records a session happening on the laptop in real-time.

Post-hackathon, deployment targets Railway or Fly.io with managed SQLite and a persistent volume for the FAISS index. Webhook-based Telegram (not long-polling) for production.

---

## 12. What's intentionally missing

Design decisions to skip features that aren't worth the scope:

- **No user auth beyond Telegram user_id.** Telegram's `chat_id` is the user key. No passwords, no OAuth dance for the app itself.
- **No team/multi-tenant.** Solo user per Telegram account.
- **No multi-language.** English only, UK focus.
- **No offline mode.** Requires internet for every call.
- **No billing.** Users don't pay. Credits budget bounds usage.
- **No notifications.** Bot speaks only when spoken to (no pushed reminders during the hackathon scope).

All of these are valid V2 adds. None of them belong in the hackathon.

---

## 13. Invariants worth naming

These must always hold. If a code change makes one of them false, that change is wrong.

1. Every user-visible generated claim carries a resolvable Citation.
2. Every LLM call goes through `llm.py` (no direct `anthropic.Anthropic()` in sub_agents).
3. The verdict agent always runs after Phase 1 completes, never before.
4. The self_audit always runs after a Phase 4 generation, never skipped.
5. The banned-phrase check runs twice on every pack output: once in the generator (soft warn), once in self_audit (hard flag).
6. The citation validator runs on every Phase 2 and Phase 4 output.
7. The onboarding flow cannot be skipped — every user must have a profile before their first forward_job.
8. `user.user_type` is immutable after onboarding (can be updated via `profile_edit` intent but with an explicit confirmation step).
9. The Sponsor Register data is re-fetched every time the bot starts (data freshness matters for visa-holder verdicts).
10. Credits are deducted-and-logged atomically per call, never in aggregate after the fact.
