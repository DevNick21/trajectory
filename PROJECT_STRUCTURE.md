# PROJECT_STRUCTURE.md — File-by-File Reference

> What each file does, what it imports, what it exports.
> Look here when you're about to create a new file and unsure where it belongs.

---

## Top-level

```
trajectory/
├── CLAUDE.md
├── ARCHITECTURE.md
├── AGENTS.md
├── SCHEMAS.md
├── PROJECT_STRUCTURE.md
├── CLAUDE_DESIGN_PLAYBOOK.md
├── PROCESS.md
├── SUBMISSION.md
├── README.md
├── LICENSE                     # MIT
├── pyproject.toml
├── .env.example
├── .gitignore
├── data/                       # see below
├── scripts/
├── src/trajectory/
├── tests/
└── .claude/agents/             # optional — Claude Code subagent files
```

## `data/`

```
data/
├── raw/                        # downloaded gov data, git-ignored
│   ├── sponsor_register.csv
│   ├── going_rates.csv
│   ├── soc_codes.csv
│   └── appendix_skilled_occupations.csv
│
├── processed/                  # parquet versions, loaded at runtime
│   ├── sponsor_register.parquet
│   ├── going_rates.parquet
│   └── soc_codes.parquet
│
└── trajectory.db               # SQLite runtime DB, git-ignored
```

`data/embeddings.faiss` also lives here when first built.

---

## `scripts/`

### `scripts/fetch_gov_data.py`

Downloads all public UK gov data needed by the system and converts to parquet.

**Inputs:** none.
**Outputs:** files in `data/raw/` and `data/processed/`.

Fetches:
- Sponsor Register (Workers) CSV from gov.uk
- Skilled Worker going rates (scraped HTML table → CSV)
- Appendix Skilled Occupations (scraped HTML → CSV)
- SOC 2020 codes (reference table)

Runs once at the start of the hackathon, then whenever you want to refresh. Takes ~60 seconds on a decent connection.

### `scripts/rebuild_embeddings.py`

Regenerates `data/embeddings.faiss` from all `career_entries` rows. Run when the index gets corrupted or schema changes.

### `scripts/smoke_test.py`

End-to-end smoke test: fixture user + fixture job URL → runs full pipeline → asserts verdict is produced with resolvable citations. Run at the end of Wednesday/Thursday/Friday to confirm nothing's broken.

---

## `src/trajectory/`

### `src/trajectory/__init__.py`

Empty. Just makes the package importable.

### `src/trajectory/config.py`

pydantic-settings-based config loader. Reads `.env`. Single source of truth for:

```python
class Settings(BaseSettings):
    anthropic_api_key: str
    telegram_bot_token: str
    companies_house_api_key: str
    rapidapi_key: str

    # feature flags
    use_managed_agents: bool = True
    enforce_rate_limit: bool = False

    # paths
    data_dir: Path = Path("./data")
    sqlite_db_path: Path = Path("./data/trajectory.db")
    faiss_index_path: Path = Path("./data/embeddings.faiss")

    # budget
    credits_budget_usd: float = 500.0
    credits_warn_threshold_usd: float = 20.0

    model_config = SettingsConfigDict(env_file=".env")

settings = Settings()
```

### `src/trajectory/schemas.py`

Every Pydantic model. See SCHEMAS.md for the full contents. This file should be pasteable directly from SCHEMAS.md's code block.

### `src/trajectory/storage.py`

SQLite + FAISS persistence. Exports:

```python
async def get_user_profile(user_id: str) -> UserProfile | None
async def upsert_user_profile(profile: UserProfile) -> None

async def insert_career_entry(entry: CareerEntry) -> None
async def retrieve_relevant_entries(
    user_id: str,
    query_text: str,
    k: int = 12,
) -> list[CareerEntry]

async def get_writing_style_profile(user_id: str) -> WritingStyleProfile | None
async def upsert_writing_style_profile(profile: WritingStyleProfile) -> None

async def insert_session(session: Session) -> None
async def get_session(session_id: str) -> Session | None
async def update_session(session: Session) -> None
async def get_recent_sessions(user_id: str, n: int = 5) -> list[Session]

async def cache_scraped_page(url: str, text: str, fetched_at: datetime) -> None
async def get_cached_page(url: str, max_age_hours: int = 24) -> str | None

async def log_llm_cost(
    session_id: str | None,
    agent_name: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> None
async def total_cost_usd() -> float
```

### `src/trajectory/llm.py`

Single point of entry for all LLM calls. Exports:

```python
async def call_agent(
    agent_name: str,
    system_prompt: str,
    user_input: str | list[dict],
    output_schema: type[BaseModel],
    model: str = "claude-opus-4-7",
    effort: str = "xhigh",
    max_retries: int = 2,
    session_id: str | None = None,
    priority: Literal["CRITICAL", "NORMAL"] = "NORMAL",
) -> BaseModel:
    """
    Universal agent call. Handles:
    - Anthropic SDK initialisation
    - Managed Agents session routing (if agent_name starts with "phase_1_"
      or "phase_4_fanout_")
    - JSON parsing + Pydantic validation
    - Retry loop with validator feedback
    - Cost logging to storage.log_llm_cost
    - Credit budget check (refuses non-CRITICAL calls under threshold)
    """

async def stream_agent(...) -> AsyncIterator[str]:
    """For cases where streaming UX matters (onboarding follow-ups)."""
```

Internal:
- `_build_messages(system, user) -> list[dict]`
- `_count_tokens_estimate(...)` for cost logging
- `_load_managed_agents_client()` with beta header
- `_plain_messages_api_fallback(...)` if Managed Agents beta fails

### `src/trajectory/orchestrator.py`

Top-level pipeline functions, one per intent. Exports:

```python
async def handle_forward_job(user: UserProfile, job_url: str) -> Session
async def handle_draft_cv(user, session_ref, extra_context) -> CVOutput
async def handle_draft_cover_letter(user, session_ref, extra) -> CoverLetterOutput
async def handle_predict_questions(user, session_ref) -> LikelyQuestionsOutput
async def handle_salary_advice(user, session_ref) -> SalaryRecommendation
async def handle_draft_reply(user, incoming_msg, user_intent_hint) -> DraftReplyOutput
async def handle_full_prep(user, session_ref) -> Pack
async def handle_profile_query(user, query_text) -> str
async def handle_profile_edit(user, edit_text) -> UserProfile

async def compute_job_search_context(user_id: str) -> JobSearchContext
```

Each handler:
1. Loads required state from storage.
2. Dispatches to sub_agents.
3. Runs citation validation.
4. Runs self_audit on Phase 4 outputs.
5. Persists updated session.
6. Returns the output (handlers format it for Telegram).

### `src/trajectory/sub_agents/`

One file per agent. Each agent:
- Exports a single async function (usually `run` or `generate`).
- Takes Pydantic input, returns Pydantic output.
- Calls `llm.call_agent(...)` internally.
- Contains its system prompt as a module-level constant copied from `AGENTS.md`.

#### `sub_agents/company_scraper.py`

```python
async def run(job_url: str) -> tuple[CompanyResearch, ExtractedJobDescription]:
    """Playwright-fetch the JD page + company's careers/blog/values/about.
    Calls jd_extractor + company_scraper_summariser. Caches via storage."""
```

#### `sub_agents/companies_house.py`

```python
async def lookup(company_name: str) -> CompaniesHouseSnapshot | None:
    """Free official API. Fuzzy-match by name if direct fails."""
```

#### `sub_agents/reviews.py`

```python
async def fetch(company_name: str) -> list[ReviewExcerpt]:
    """Glassdoor via RapidAPI. Cached 24h. Returns [] on failure."""
```

#### `sub_agents/red_flags.py`

```python
async def detect(research_bundle_parts: ...) -> RedFlagsReport:
    """Opus 4.7 scan of research + CH + reviews for flags."""
```

#### `sub_agents/ghost_job_detector.py`

```python
async def score(
    jd: ExtractedJobDescription,
    company_research: CompanyResearch,
    companies_house: CompaniesHouseSnapshot | None,
) -> GhostJobAssessment:
    """Combines 4 signals per AGENTS.md §5. Calls JD scorer LLM,
    computes other signals deterministically, combines per the
    logic in the doc."""
```

#### `sub_agents/salary_data.py`

```python
async def fetch(
    role: str,
    location: str,
    company: str | None = None,
) -> SalarySignals:
    """Glassdoor + Levels.fyi via RapidAPI + posted band from JD.
    Returns empty SalarySignals with empty sources_consulted if all
    sources fail."""
```

#### `sub_agents/sponsor_register.py`

```python
async def lookup(company_name: str) -> SponsorStatus:
    """Pandas lookup against data/processed/sponsor_register.parquet.
    Fuzzy match threshold: 92% rapidfuzz ratio."""
```

#### `sub_agents/soc_check.py`

```python
async def verify(
    jd: ExtractedJobDescription,
    user: UserProfile,
) -> SocCheckResult:
    """Looks up going_rate for jd.soc_code, computes shortfall,
    checks new-entrant eligibility (Graduate visa time in UK +
    age rules per Home Office)."""
```

#### `sub_agents/verdict.py`

```python
async def generate(
    research_bundle: ResearchBundle,
    user: UserProfile,
    retrieved_entries: list[CareerEntry],
) -> Verdict:
    """The keystone agent. System prompt from AGENTS.md §6."""
```

#### `sub_agents/question_designer.py`

```python
async def generate(
    verdict: Verdict,
    research_bundle: ResearchBundle,
    user: UserProfile,
    retrieved_entries: list[CareerEntry],
) -> QuestionSet:
    ...
```

#### `sub_agents/star_polisher.py`

```python
async def polish(
    question: DesignedQuestion,
    raw_answer: str,
    jd: ExtractedJobDescription,
    style_profile: WritingStyleProfile,
) -> STARPolish:
    ...
```

#### `sub_agents/style_extractor.py`

```python
async def extract(
    samples: list[str],
    user_id: str,
) -> WritingStyleProfile:
    ...
```

#### `sub_agents/self_audit.py`

```python
async def run(
    generated_output: BaseModel,
    research_bundle: ResearchBundle | None,
    style_profile: WritingStyleProfile,
) -> SelfAuditReport:
    ...

async def apply_rewrites(
    generated_output: BaseModel,
    report: SelfAuditReport,
) -> BaseModel:
    """Apply proposed_rewrite for each flag."""
```

#### `sub_agents/salary_strategist.py`

```python
async def generate(
    jd: ExtractedJobDescription,
    research_bundle: ResearchBundle,
    user: UserProfile,
    context: JobSearchContext,
    style_profile: WritingStyleProfile,
) -> SalaryRecommendation:
    ...
```

#### `sub_agents/intent_router.py`

```python
async def route(
    user_message: str,
    recent_messages: list[str],
    last_session: Session | None,
) -> IntentRouterOutput:
    ...
```

#### `sub_agents/cv_tailor.py`

```python
async def generate(
    jd: ExtractedJobDescription,
    research_bundle: ResearchBundle,
    user: UserProfile,
    retrieved_entries: list[CareerEntry],
    style_profile: WritingStyleProfile,
    star_material: list[STARPolish] | None = None,
) -> CVOutput:
    ...
```

#### `sub_agents/cover_letter.py`

```python
async def generate(...) -> CoverLetterOutput:
    ...
```

Same input signature as cv_tailor, different output.

#### `sub_agents/likely_questions.py`

```python
async def generate(...) -> LikelyQuestionsOutput:
    ...
```

Same input signature, different output.

#### `sub_agents/draft_reply.py`

```python
async def generate(
    incoming_message: str,
    user_intent_hint: str,
    user: UserProfile,
    style_profile: WritingStyleProfile,
    relevant_entries: list[CareerEntry] | None = None,
) -> DraftReplyOutput:
    ...
```

---

## `src/trajectory/bot/`

### `bot/app.py`

Entry point:

```python
async def main():
    application = (
        ApplicationBuilder()
        .token(settings.telegram_bot_token)
        .build()
    )
    application.add_handler(CommandHandler("start", handlers.on_start))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.on_message)
    )
    await application.run_polling()
```

### `bot/handlers.py`

Per-update handlers:

```python
async def on_start(update, context):
    """Entry for new users — starts onboarding."""

async def on_message(update, context):
    """Main dispatcher:
    - Check onboarding completion. If incomplete → continue onboarding.
    - Else: intent_router → handler per intent → render result."""
```

### `bot/onboarding.py`

The conversational 6-topic flow:

```python
class OnboardingState(Enum):
    GREETING = 0
    CAREER_NARRATIVE = 1
    MOTIVATIONS = 2
    MONEY = 3
    DEAL_BREAKERS_AND_GOOD_SIGNALS = 4
    VISA_LOCATION = 5
    LIFE_URGENCY = 6
    WRITING_SAMPLES = 7
    CONFIRMATION = 8
    COMPLETE = 9

async def advance(user_id: str, message: str) -> tuple[str, OnboardingState]:
    """Takes current state + user message, returns bot reply + new state."""
```

### `bot/formatting.py`

Render structured outputs as Telegram messages:

```python
def format_verdict(v: Verdict) -> list[str]:
    """Telegram has 4096-char limit per message; split if needed."""

def format_cv_output(cv: CVOutput) -> list[str]:
    """Render as inline Markdown (Telegram supports)."""

def format_cover_letter(cl: CoverLetterOutput) -> list[str]: ...
def format_likely_questions(lq: LikelyQuestionsOutput) -> list[str]: ...
def format_salary_recommendation(s: SalaryRecommendation) -> list[str]: ...
def format_citation(c: Citation) -> str: ...
```

---

## `src/trajectory/validators/`

### `validators/citations.py`

```python
class ValidationContext(BaseModel):
    research_bundle: ResearchBundle | None
    career_store_entries: dict[str, CareerEntry]

def extract_all_citations(output: BaseModel) -> list[Citation]: ...
def validate_citation(c: Citation, ctx: ValidationContext) -> tuple[bool, str]: ...
def validate_output(output: BaseModel, ctx: ValidationContext) -> list[str]:
    """Returns list of human-readable failure descriptions."""
```

### `validators/banned_phrases.py`

```python
BANNED_PHRASES: set[str] = {...}  # see CLAUDE.md

def contains_banned(text: str) -> list[str]:
    """Returns banned phrases found."""

def run_company_swap_test(text: str, company_name: str) -> list[str]:
    """Returns sentences that pass the swap test (i.e., they're generic)."""
```

### `validators/schema_retry.py`

```python
async def with_retry_on_invalid(
    agent_call: Callable,
    input_data: dict,
    expected_schema: type[BaseModel],
    max_retries: int = 2,
) -> BaseModel:
    """Generic retry-with-feedback wrapper used by llm.call_agent."""
```

---

## `src/trajectory/dashboard/`

### `dashboard/app.py`

Streamlit single-page app. Shows:
- List of recent sessions for the current user
- Click a session → view ResearchBundle, Verdict, Pack components
- Every citation is clickable (opens URL in new tab, or shows the gov data field)
- Self-audit reports visible as "warnings" per session

Deployment: `streamlit run src/trajectory/dashboard/app.py`.

---

## `tests/`

Minimal set. Demo quality outranks coverage.

### `tests/test_citations.py`

- verbatim matching tolerates whitespace differences
- URL mismatch rejected
- gov data field path resolution
- career_entry existence check

### `tests/test_ghost_job_combination.py`

- 2 HARD signals → LIKELY_GHOST HIGH
- 1 HARD + 1 SOFT → LIKELY_GHOST MEDIUM
- only soft signals → POSSIBLE_GHOST or LIKELY_REAL
- 0 signals → LIKELY_REAL HIGH

### `tests/test_verdict_branching.py`

- visa_holder + NOT_LISTED → NO_GO hard blocker
- uk_resident + NOT_LISTED → no hard blocker (bypasses sponsor check)
- uk_resident + ghost_job LIKELY + HIGH → NO_GO
- visa_holder + soc_shortfall > 0 + not new-entrant → NO_GO

### `tests/fixtures/`

`sample_research_bundle.json` — a hand-crafted valid ResearchBundle fixture covering both user types.

---

## `.claude/agents/` (optional)

If using Claude Code's subagent feature, one markdown file per agent with YAML frontmatter. Otherwise skip this — the agent prompts in `sub_agents/*.py` as module constants are enough.

---

## `pyproject.toml` shape

```toml
[project]
name = "trajectory"
version = "0.1.0"
description = "UK job search personal assistant"
requires-python = ">=3.11"
dependencies = [
    "anthropic>=0.45.0",
    "python-telegram-bot>=21.0",
    "fastapi>=0.110.0",
    "httpx>=0.27.0",
    "playwright>=1.40.0",
    "trafilatura>=1.8.0",
    "dateparser>=1.2.0",
    "rapidfuzz>=3.6.0",
    "tldextract>=5.1.0",
    "pandas>=2.2.0",
    "pyarrow>=15.0.0",
    "sqlalchemy>=2.0.0",
    "aiosqlite>=0.20.0",
    "sentence-transformers>=3.0.0",
    "faiss-cpu>=1.8.0",
    "pydantic>=2.6.0",
    "pydantic-settings>=2.2.0",
    "streamlit>=1.35.0",
    "python-jobspy>=1.1.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.23.0",
    "ruff>=0.5.0",
]
```

## `.env.example`

```
ANTHROPIC_API_KEY=
TELEGRAM_BOT_TOKEN=
COMPANIES_HOUSE_API_KEY=
RAPIDAPI_KEY=
USE_MANAGED_AGENTS=true
```

## `.gitignore`

```
.env
.venv/
__pycache__/
*.pyc
data/raw/
data/processed/
data/trajectory.db
data/embeddings.faiss
*.log
.pytest_cache/
.ruff_cache/
```
