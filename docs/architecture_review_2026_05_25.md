# AskPicky Architecture Review — 2026-05-25

> Follow-on from the [2026-05-17 review](./architecture_review_2026_05_17.md). Evaluates system design quality across module boundaries, data model, orchestration, scalability, observability, and production readiness.

## 1. Current Architecture Summary

AskPicky (code name "Trajectory") is a UK job-search personal assistant with 24 LLM-powered agents spanning 5 phases. It operates via a **FastAPI web app** backed by **SQLite** via WAL mode. Deployment is **Docker Compose** with 2 containers (backend API, Nginx-fronted React SPA).

**Pipeline:** User message → Content Shield (Tier 1 regex) → Intent Router (tier-0 rules + DeepSeek Flash fallback) → Phase 1A company scraping (Playwright + JD extract + company summariser) → Phase 0 triage (DeepSeek Flash) → Phase 1A.5 entity resolution (5-layer CRN pipeline) → Phase 1B Companies House → Phase 1C fan-out (6 agents in parallel via `asyncio.gather`) → Quality gate (deterministic, <1ms) → Content Shield (Tier 2 if flagged) → Phase 2 Verdict (GPT-5.4 primary, DeepSeek Pro fallback) → Phase 4 generators (CV, cover letter, questions, salary) + Phase 4.5 self-audit.

**LLM abstraction:** Backend Protocol with 3 providers (Anthropic native, DeepSeek via OpenAI-compat, OpenAI native). Per-agent model routing in `config.py::agent_model_map`. Max 2 retries with validation feedback on JSON/Pydantic failures.

**Storage:** Handwritten SQL against aiosqlite (14 tables) + FAISS IndexFlatIP for career entry retrieval. Additive column migrations applied via PRAGMA table_info idempotency. No ORM.

**Observability:** Contextvars-based correlation filter (request_id + session_id in every log line). LLM cost tracking in `llm_cost_log`. Credit budget with $500 cap, $20 warn threshold.

---

## 2. Findings

### Finding 1: SQLite as Sole Persistence with Multi-Process Access

**Severity:** Critical
**Affected components:** `storage.py`, `docker-compose.yml`, API + Bot processes

**Current design:** The FastAPI uvicorn process uses SQLite on a Docker named volume. WAL mode + `synchronous=NORMAL` enables concurrent reads. `busy_timeout=5000` handles write contention. No connection pool — every query opens a fresh aiosqlite connection.

**Why risky:** WAL handles concurrent readers, but SQLite serialises all writers. A long-running LLM call that finishes with a `save_phase1_output` write blocks other writes. At 10+ concurrent users, write contention becomes the dominant latency source. A forward_job session does ~10 writes — at 10 concurrent sessions, that's 100 writes serialised through a single mutex.

**Failure scenario:** User A's verdict completes and attempts to save while User B's onboarding parser is writing career entries. SQLite writer lock serialises them. If User C forwards a job during a write spike, the 5-second busy timeout may be exceeded and the write fails silently (the orchestrator's `except Exception` catches it, but no retry is attempted on storage operations).

**Recommended architecture change:** Migrate to PostgreSQL with connection pooling (asyncpg + pool_size=5). Use pgvector for embeddings (canonical vector store). Keep FAISS as an optional in-process acceleration layer. Use Alembic for migrations.

**Short-term fix:** Add a `sqlite_write_semaphore = asyncio.Semaphore(1)` wrapping all `db.commit()` calls to prevent cascading busy-timeout failures. Add write retry with exponential backoff (3 attempts, 100ms/200ms/400ms). Log write latency percentiles.

**Long-term target:** PostgreSQL with SQLAlchemy async engine. pgvector for embeddings. Alembic migrations. FAISS rebuilt from canonical vector store on restart, retained as optional acceleration.

---

### Finding 2: No Authentication or Multi-Tenancy Boundary

**Severity:** Critical
**Affected components:** `api/dependencies.py`, all API routes, `config.py`

**Current design:** ADR-0001 documents `get_current_user_id` as the single seam for identity. Today it reads `settings.demo_user_id`. No session tokens, no CSRF protection, no auth middleware. The `ENFORCE_RATE_LIMIT` feature flag defaults to `False`. Every endpoint accepts any request with a matching Origin header. The `Storage` class has no per-user data isolation checks at the data layer — it trusts the caller to pass the correct `user_id`.

**Why risky:** The system is architecturally single-user but described as "multi-user capable via a seam." The seam is a single function — there is no session management, no authorization model (can user A see user B's verdicts?), no tenant isolation. Moving to multi-user requires changes far beyond ADR-0001's one-function promise: every Storage method needs auditable user_id filtering, the rate limiter needs per-user state, and the notification scheduler needs per-user delivery.

**Failure scenario:** Deploying the web surface publicly with `demo_user_id` hardcoded means every visitor shares one identity. All career entries, verdicts, and writing style samples are cross-contaminated. The first real user to onboard overwrites the demo data. There's no way to distinguish users without a full redeploy.

**Recommended architecture change:** Implement OAuth 2.0 / OIDC with session cookies. All `Storage` methods accept and validate `user_id` at the data layer (not just trust the caller). Add a `user_id` WHERE clause to every SQL query — today most retrieval calls filter by user_id, but a missing clause on one method would leak cross-tenant data silently.

**Short-term fix:** Add a `_REQUIRE_USER_ID = True` guard in `Storage.__init__` that is `False` in test mode but `True` in production. Assert `user_id is not None` on every write path. Add an API key header check (`X-AskPicky-User-ID`) as a stop-gap until OAuth lands. Document that this is NOT a security boundary — it's a data-isolation guardrail.

**Long-term target:** OAuth 2.0 with refresh tokens, session cookies, and CSRF protection. Per-user database row-level isolation enforced at the data layer. Rate limiting keyed per authenticated user. Audit log for cross-user data access attempts.

---

### Finding 3: In-Process Notification Scheduler with No At-Least-Once Guarantee

**Severity:** Critical
**Affected components:** `notifications/scheduler.py`, `notifications/store.py`, `notifications/dispatcher.py`

**Current design:** An `asyncio.create_task` loop polls `list_due_notifications(limit=50)` every 60s, dispatches each notification, then marks them sent. A single `_stop_event` gate controls lifecycle. No persistence of dispatch state between "dispatch started" and "mark sent." No dead-letter queue. No retry. If the process crashes between dispatch and mark-sent, the notification is silently lost (or delivered twice if the side-effect completed but the status update didn't).

**Why risky:** Outcome nudges are the primary re-engagement mechanism that keeps users in the application loop after forwarding a job. A crash at the wrong moment means the Day 7 "did you apply?" nudge never fires. This is a silent data loss mode — no alert, no retry, no operator visibility. The 60s poll interval means worst-case 60s+ scheduling delay, which is acceptable for day-granularity nudges but not for any future sub-minute notification use case.

**Failure scenario:** Scheduler dispatches a notification for user A's Day 7 nudge. The notification delivery succeeds. Before `store.mark_sent` executes, the process is killed (OOM, Docker restart). On restart, the same notification is picked up as `pending` and dispatched again — user A receives a duplicate nudge. The reverse failure: the process dies before the delivery completes. The notification stays `pending`, no retry logic exists, and the nudge is never delivered.

**Recommended architecture change:** Two-phase dispatch: (1) mark as `sending` with a `dispatch_started_at` timestamp, (2) execute dispatch, (3) mark as `sent`. On scheduler startup, requery all rows with `status='sending' AND dispatch_started_at < now() - 120s` — these are orphaned dispatches; reset them to `pending` for retry. Add a `max_attempts` column (default 3); after exceeding, move to a `failed` status with an error log.

**Short-term fix:** Add `dispatch_started_at` and `attempts` columns to the `notifications` table via additive migration. Before dispatch: `UPDATE SET status='sending', dispatch_started_at=now(), attempts=attempts+1`. After dispatch: `UPDATE SET status='sent', sent_at=now()`. On scheduler startup: reset orphaned `sending` rows older than 120s back to `pending`. Log failures after 3 attempts as warnings with the notification payload.

**Long-term target:** Replace the in-process scheduler with a proper task queue (Celery with Redis broker for simplicity; Temporal for stronger durability guarantees). Notifications become idempotent via an `idempotency_key`. Separate the scheduler (marks rows as ready) from the worker (dispatches, handles retries, manages dead letters). The worker pool scales independently of the API processes.

---

### Finding 4: FAISS Index Per-Process with No Inter-Process Visibility

**Severity:** High
**Affected components:** `storage.py` (FAISS section, lines 394-560), `docker-compose.yml`

**Current design:** The FAISS index (`IndexFlatIP`, inner product, 384-dim all-MiniLM-L6-v2) is loaded into memory at startup (`_lazy_init_faiss`). `insert_career_entry` updates the in-memory index and flushes to disk (`embeddings.faiss` + `embeddings.faiss.ids.json`).

**Why risky:** With a single process model, FAISS is only loaded once, avoiding the cross-process staleness issues. However, restarts still require a full index rebuild from the DB which is sequential and blocks startup.

**Failure scenario:** After a restart, the FAISS index must be rebuilt from all career entries. For a user with 1,000+ entries, this takes 10+ seconds during which any retrieval request will fail or return empty results.

**Recommended architecture change:** Move to a client-server vector store. pgvector in PostgreSQL (see Finding 1) is the simplest path — it's a native PG extension with HNSW indexing, no separate service to manage. Embedding generation becomes an async task rather than blocking the write path. FAISS retained as an optional in-process cache layer rebuilt from the canonical pgvector store on restart.

**Short-term fix:** Add a `_faiss_version` counter in SQLite (incremented atomically on every career entry insert). The retrieving process checks the version before each retrieval call. If the process's local version is behind the DB version, reload the FAISS index from disk before serving the query. Accept a brief latency spike (~100ms for reload) on the first stale query rather than returning silently wrong results. Cache the last-checked timestamp to avoid checking on every query.

**Long-term target:** pgvector index alongside the PostgreSQL migration. Embedding generation runs in a background queue (not blocking the HTTP request). FAISS becomes an optional acceleration layer that can be disabled. The vector store is the canonical source; FAISS is a read replica.

---

### Finding 5: orchestrator.py is a 1685-Line Monolith with Mixed Concerns

**Severity:** High
**Affected components:** `orchestrator.py`

**Current design:** A single file containing all of: Phase 1 pipeline orchestration (lines 79-665), 6 `run_*` coroutine closures defined inline inside `handle_forward_job`, parent/subsidiary walk, content shield bundle wrapper, shielded fallback verdict builder, Phase 2.5 comparison (`handle_compare_verdicts`) and challenge (`handle_challenge_verdict`), job search context computation (`compute_job_search_context`), fallback style profile builder, and all Phase 4 generator wrappers (CV, cover letter, questions, salary, full prep, draft reply, offer analysis). The `handle_forward_job` function alone is ~600 lines with inline closures, inline imports, and multi-level nested try/except blocks.

**Why risky:** Adding a new intent requires editing this file. Understanding the Phase 1 lifecycle requires scrolling through 600 lines of inline closures whose variable capture is non-obvious. The `handle_full_prep` function fans out to 4 generators in `asyncio.gather` — adding a fifth generator is a copy-paste exercise across 3 places (import, call, response assembly). Testing individual handlers requires constructing a full orchestrator import chain. The inline `run_*` closures cannot be unit-tested in isolation; they depend on captured variables from the enclosing `handle_forward_job` scope.

**Failure scenario:** A new Phase 1 agent is added. The developer must: (1) add it to `PHASE_1_AGENTS` list (line 58), (2) add a new `run_*` closure inside `handle_forward_job` (~30 lines), (3) add it to the `asyncio.gather` unpacking (line 487), (4) add it to the `ResearchBundle` constructor (line 514). Missing step 3: the agent runs but its output is silently discarded. Missing step 4: the agent's output is collected but never reaches the verdict prompt. Missing step 2 but present in step 3: `NameError` at runtime. No compile-time or static analysis guarantee that the gather unpacking count matches the closure count.

**Recommended architecture change:** Extract a plugin-style agent registry. Define a `Phase1Agent` protocol: `(name: str, run: Callable, requires_visa: bool, depends_on: list[str])`. Each Phase 1 agent registers itself. The orchestrator reads the registry, builds a dependency DAG, and fans out automatically. Adding a new Phase 1 agent becomes a one-file change: implement the agent module, register it. The orchestrator picks it up without modification.

The same pattern applies to Phase 4 generators: a `Phase4Generator` protocol that registers itself with an intent name, accepts the standard input bundle (user, session, storage, retrieved entries, style profile), and returns its typed output.

**Short-term fix:** Extract the Phase 1C fan-out into its own module (`pipeline/phase1_fanout.py`). Convert the `run_*` closures to free functions that accept explicit parameters (no captured variables). Extract the content shield bundle wrapper and fallback verdict builder into their own module (`pipeline/shield.py`). Extract Phase 4 handlers into `pipeline/phase4_handlers.py`. The orchestrator becomes a thin dispatch layer that imports and delegates.

**Long-term target:** Full plugin registry. Agent DAG with topological sort for dependency ordering. Conditional edges (skip SOC for non-visa-holders as a graph decision, not an if-statement). Each agent module is independently testable. Adding a new agent is a single-file PR.

---

### Finding 6: Prompt Versioning is Implicit — No Runtime Audit Trail

**Severity:** High
**Affected components:** `prompts/*.md`, `llm.py`, `sub_agents/verdict.py`, `storage.py` (`llm_cost_log` table)

**Current design:** Prompts are stored as Markdown files in `prompts/`, loaded via `@lru_cache` at import time by each sub-agent module. Git provides version history. But the `llm_cost_log` and `sessions` tables record only agent_name, model, token counts, and cost. There is no hash of the exact system prompt text that was used to produce a given LLM output. The Prompt Auditor (agent #17) audits prompts at build time, but the audit report is not stored at call time.

**Why risky:** If a prompt is changed and the verdict quality degrades, there's no way to correlate "this batch of bad verdicts" with "this specific prompt change" without cross-referencing timestamps against `git log`. During prompt iteration or A/B testing, you cannot distinguish outputs by prompt version. If a prompt injection vulnerability is found post-deployment, you cannot identify which sessions were affected without timestamp correlation — which fails if multiple prompt versions were deployed in the same hour.

**Failure scenario:** A prompt change on Monday accidentally weakens the citation grounding rules in the verdict prompt. Verdicts from Monday onward produce structurally valid JSON (passing Pydantic validation) but with invented citations. The post-validation citation resolver catches some fabrications, but not all (some invented citations happen to collide with real bundle fields). Without a prompt hash in the cost log, identifying which sessions were affected requires: (1) know the exact timestamp of the deploy, (2) query all sessions after that timestamp, (3) manually re-audit each. At 50+ sessions per day, this is operationally infeasible.

**Recommended architecture change:** Compute a SHA-256 digest of the full system prompt text at call time. Log it in `llm_cost_log.prompt_hash` (12-char hex prefix is sufficient for uniqueness within a deployment). Store the hash alongside the session's verdict so the audit trail joins cleanly. Add a `prompt_version` metadata field to every agent output schema (non-functional, stamped by `call_agent`, validated but unused by downstream logic).

**Short-term fix:** Add a `prompt_hash TEXT` column to `llm_cost_log` via additive migration. `call_agent` computes `hashlib.sha256(system_prompt.encode()).hexdigest()[:12]` and passes it to `log_llm_cost`. Zero meaningful runtime cost (SHA-256 of ~3KB is <1µs). Ship this in a single commit.

**Long-term target:** Semantic prompt versioning — each prompt file has a `version: "1.2.0"` frontmatter field. The CI pipeline bumps it on merge. The stored `prompt_hash` is the canonical audit key. A dashboard query shows "verdict quality metrics by prompt version" across the benchmark history. Prompt A/B testing infrastructure uses the hash to route and measure.

---

### Finding 7: No Structured Retry or Circuit Breaking on External APIs

**Severity:** High
**Affected components:** `orchestrator.py` (Phase 1C fan-out), `sub_agents/companies_house.py`, `sub_agents/sponsor_register.py`, `sub_agents/gazette_check.py`, `sub_agents/company_scraper.py`

**Current design:** Each Phase 1C agent is wrapped in `asyncio.wait_for(timeout=45s)` with a try/except that returns a conservative fallback on failure. Companies House, Sponsor Register parquet, Gazette HTTP — all called directly with no retry, no backoff, no circuit breaking. The Playwright scraper in `company_scraper.py` has no retry on transient network errors. A single `httpx.TimeoutException` causes the agent to return `source_status=UNREACHABLE` with no attempt to retry.

**Why risky:** A single degraded external API (Companies House returning 503s) causes every concurrent forward_job session to wait the full 45s timeout before getting a fallback. At 10 concurrent requests, that's 450 seconds of cumulative wasted wall-clock time — all waiting for a service that's already known to be down. With no circuit breaker, the system keeps hammering the degraded service, potentially extending the outage (thundering herd on recovery).

**Failure scenario:** Companies House API starts returning 503s at 10:00 AM. Every forward_job from 10:00-10:30 times out after 45s. All 30 sessions produce verdicts with `companies_house: source_status=UNREACHABLE`. The ghost_job_detector (which depends on CH data for temporal signals) defaults to `LIKELY_REAL` with `LOW` confidence. Ghost jobs pass undetected. The system silently degrades for 30 minutes — no operator alert, no automatic backoff, no user-visible warning that the verdict is based on incomplete data.

**Recommended architecture change:** Implement a circuit breaker pattern. Track consecutive failures per external API. After N consecutive failures, open the circuit for M seconds. During open state, skip the API call immediately (not after a 45s timeout) and return the UNREACHABLE fallback. Half-open state: allow one probe request after the cooldown period to test if the service has recovered. Use shared state (in SQLite for the single-machine deploy; Redis for distributed).

**Short-term fix:** Add an in-memory `_circuit_state: dict[str, tuple[int, float]]` in the orchestrator — keyed by API name, value is `(consecutive_failures, last_failure_timestamp)`. On failure: increment counter. Before call: if counter >= 3 and `now - last_failure < 120s`, skip the call and return UNREACHABLE immediately. On success: reset counter to 0. Log every circuit open/close event. This is ~30 lines of Python per API and saves N × 45s of cumulative latency during every outage.

**Long-term target:** A proper resilience library from the Python ecosystem (`tenacity` for retry with jitter + exponential backoff, `pybreaker` or a purpose-built module for circuit breaking). Per-API configuration: max_retries, backoff_base, circuit_open_duration, half_open_probe_count. Expose circuit state via a `/health/dependencies` endpoint for operational visibility and alerting integration.

---

### Finding 8: LangGraph Orchestrator is a Stub, Not a Functional Decomposition

**Severity:** High
**Affected components:** `langgraph_orchestrator.py`, `config.py`

**Current design:** `langgraph_orchestrator.py` defines a `StateGraph` with 4 nodes (scrape, triage, fanout, verdict) connected sequentially via `add_edge`. But `_node_fanout` (lines 105-123) and `_node_verdict` (lines 126-162) are empty shells — `_node_fanout` contains only a log line and the comment `# Re-use the orchestrator's fan-out logic verbatim` followed by an `except Exception` block. `_node_verdict` logs `"delegating full pipeline to handle_forward_job"` and does nothing. The compiled graph uses `MemorySaver` for checkpointing, but since only 2 of 4 nodes are functional, the graph cannot produce a complete research bundle or verdict independently. The public entrypoint `run_forward_job_graph` falls back to the imperative orchestrator when `enable_langgraph_orchestrator=False` (the default).

**Why risky:** The wrapper is presented as providing "built-in retry/fallback per node, durable state persistence, structured error handling" but it doesn't actually decompose the pipeline into independently retryable steps. It's dead code that creates a false sense of progress toward production-grade orchestration. If an operator enables `ENABLE_LANGGRAPH_ORCHESTRATOR=true` expecting durable execution, the system runs the broken graph and produces a `PASS` verdict with 0% confidence (the fallback at lines 233-263).

**Failure scenario:** Developer enables `ENABLE_LANGGRAPH_ORCHESTRATOR=true` in production expecting checkpointed state and per-node retry. The graph runs `_node_scrape` (works, produces company_research and extracted_jd). Then `_node_fanout` (does nothing, transitions state to `verdicting`). Then `_node_verdict` (does nothing, transitions state to `complete`). The graph completes with `phase=complete` but `research_bundle=None` and `verdict=None`. The fallback at line 233 returns a `PASS` verdict with 0% confidence. Every user who forwards a job gets "Apply — LangGraph pipeline produced no verdict." This is a silent production incident with no error log.

**Recommended architecture change:** Either (a) fully implement each LangGraph node by extracting the corresponding phase logic from the imperative orchestrator into independent, testable functions, or (b) remove the wrapper and the feature flag until it's ready to ship. Half-implemented orchestration abstractions are strictly worse than no abstraction — they mislead operators and create false confidence.

**Short-term fix:** Remove the `ENABLE_LANGGRAPH_ORCHESTRATOR` feature flag and the `langgraph_orchestrator.py` import from the `api/app.py` startup path. Keep the module on a feature branch. The imperative orchestrator is the only code path. Ship the LangGraph wrapper when all 4 nodes are implemented and pass the same integration tests as the imperative path.

**Long-term target:** Full LangGraph implementation. Each Phase 1 agent is its own graph node with configurable retry policy. Conditional edges replace if-statements (e.g., skip SOC check for non-visa-holders as a graph edge). Checkpoint to SQLite/PostgreSQL (not MemorySaver) for durable state across process restarts. The graph is visualizable via LangGraph's built-in export, enabling operator understanding of the pipeline topology.

---

### Finding 9: No Content Versioning for Scraped Pages

**Severity:** Medium
**Affected components:** `storage.py` (`scraped_pages` table), `sub_agents/company_scraper.py`

**Current design:** Scraped pages are cached in the `scraped_pages` table keyed by URL. TTL is 24 hours, checked in `get_cached_page()`. The scraper checks the cache first, fetches with Playwright on miss. No content hash is stored alongside the cached page — the cache freshness decision is purely temporal. If a JD page changes (e.g., salary band added, requirement changed, role filled and posting removed) within the 24-hour window, the cached version is served silently with no indication that the content may have changed.

**Why risky:** Job postings change frequently. A company might add a salary band, remove a degree requirement, or fill the role. The user forwards a job at 9 AM, gets a GO verdict based on the cached 9 AM scrape. At 2 PM the JD is updated (role filled). The user forwards again at 3 PM — cache TTL is 24 hours, so they get the same cached content and the same GO verdict. They spend 4 hours preparing an application for a closed role with outdated information.

**Failure scenario:** User forwards a job. Scraper fetches and caches. Salary: "competitive" (no explicit band). Verdict: GO with a stretch concern about unknown salary. 6 hours later, the company updates the JD to include "£45,000-£55,000." User re-forwards. Cache hit (within 24h TTL). Same verdict, same stretch concern. User's salary floor is £50,000. They apply. Offer arrives at £47,000. The user wasted 2 weeks on an application they would have rejected if they'd seen the updated salary band. The system had the knowledge (it was on the page) but served stale data.

**Recommended architecture change:** Store a `content_hash` (SHA-256 of page text) alongside each cached page. On cache hit, compare the stored hash against the current page content via a lightweight HTTP HEAD + `If-None-Match` / `If-Modified-Since` conditional request. If the server returns 304, serve the cache. If 200, compute the hash of the new content. If hashes differ, invalidate the cache entry, log the change, and re-scrape. This is standard HTTP caching semantics applied to the scraper.

**Short-term fix:** Distinguish JD pages from company pages in the cache. Add a `page_kind` column to `scraped_pages` (`'jd'` vs `'company'`). Reduce the TTL for JD pages to 1 hour (company about/values/blog pages keep the 24h TTL since they change infrequently). The scraper already distinguishes the JD URL from discovered company page URLs — tag them accordingly at insert time.

**Long-term target:** Two-tier cache with content-hash validation. JD pages: 1h TTL, content-hash validated on every cache hit. Company pages: 24h TTL, validated every 6h (background refresh). Store the `ETag` and `Last-Modified` response headers from the initial fetch for efficient conditional re-fetch. Append old page versions to a `scraped_pages_history` table for auditing (when did this JD change? what did the old version say?). This feeds into the ghost_job_detector's temporal signals — a JD that changes frequently may indicate a role that's being actively managed rather than stale.

---

### Finding 10: Monolithic schemas.py (1344 Lines) with All Model Definitions

**Severity:** Medium
**Affected components:** `schemas.py`, all sub_agents, all API routes

**Current design:** All Pydantic models live in one file: 24 agents' input/output schemas, API request/response models, database row shapes (Session, QueuedJob), internal pipeline types (ResearchBundle, Verdict, all HardBlocker variants), cross-cutting primitives (Citation, SourceStatus, MatchPath), and utility models (ReviewExcerpt, SponsorAlternativeMatch, GhostSignal). At 1344 lines, it's the most frequently edited file in the codebase.

**Why risky:** Every new agent adds ~5 models to this file. Every Phase 1 extension modifies ResearchBundle (adds a field for the new sub-agent's output). Merge conflicts are guaranteed when multiple developers add agents in parallel. Importing `schemas` pulls in every model regardless of what the importing module needs — `sub_agents/ghost_job_detector.py` gets `Verdict`, `CoverLetterOutput`, and `SalaryRecommendation` in its namespace even though it never uses them.

**Failure scenario:** Alice adds a new Phase 4 generator with output schema `MockInterviewOutput` at the bottom of schemas.py. Bob adds a new field `industry_sector` to `ExtractedJobDescription` at line 200. Both merge to main. Merge conflict at the file level. Alice resolves the conflict manually but accidentally drops Bob's `ForwardRef` update for the new field (it referenced a type defined later in the file). Bob's field is valid Pydantic but forward reference resolution is silently broken. The field never appears in `model_dump()`. Silent schema drift with no test catching it.

**Recommended architecture change:** Split `schemas.py` into a package:
```
src/askpicky/schemas/
├── __init__.py        # Re-exports everything (backward-compatible imports)
├── primitives.py      # Citation, SourceStatus, MatchPath, ReviewExcerpt
├── phase1.py          # ResearchBundle, all Phase 1 sub-agent outputs
├── phase2.py          # Verdict, ReasoningPoint, HardBlocker, StretchConcern
├── phase4.py          # CVOutput, CoverLetterOutput, LikelyQuestionsOutput, etc.
├── api.py             # API request/response models
└── storage.py         # Session, QueuedJob, CareerEntry (row shapes)
```

Keep the top-level `__init__.py` re-exporting everything so `from askpicky.schemas import Verdict` continues to work. Existing import paths don't break.

**Short-term fix:** Extract `primitives.py` first — Citation, SourceStatus, MatchPath, and ReviewExcerpt. These are the types that every other module depends on. This removes ~100 lines from schemas.py and gives a natural home for shared types that doesn't create circular imports. The remaining models stay in schemas.py for now.

**Long-term target:** Full split as described. Each sub-agent module owns its output schema (e.g., `sub_agents/verdict.py` defines `Verdict`, not `schemas.py`). Cross-agent types (ResearchBundle) live in a shared package. The "schemas co-located with their owner" pattern means deleting an agent removes its schemas automatically.

---

### Finding 11: No Distributed Tracing Across Async Boundaries

**Severity:** Medium
**Affected components:** `observability/logging_context.py`, `llm.py`, `llm_backends/`, `orchestrator.py`

**Current design:** A `contextvars`-based `CorrelationFilter` injects `request_id` and `session_id` into every log record. `bind_request_id()` sets the context var at request entry; the middleware resets it on exit. Context vars propagate through `asyncio.create_task` correctly (they're task-local in Python 3.11+). But LLM calls to 4 different providers are logged as independent log lines with no shared span context. There's no concept of a "forward_job operation" spanning Phase 1A → Phase 1C → Phase 2 as a single trace. No span start/end events. No latency attribution per phase.

**Why risky:** When a forward_job takes 120 seconds wall-clock time, debugging where the time went requires manually correlating 10-15 log lines by session_id and mentally computing deltas between adjacent timestamps. Cost attribution per pipeline phase is manual — you cannot query "how much did Phase 1C cost vs. Phase 2 for session X" without joining `llm_cost_log` on session_id and summing per agent_name. The `llm_cost_log` has no `phase` column, so grouping by pipeline phase requires external knowledge of which agent runs in which phase.

**Failure scenario:** Performance regression: forward_job latency increased from 60s to 90s. Which phase regressed? You grep logs for a specific session_id, manually compute timestamps between adjacent log lines. It takes 10 minutes per session. At 50 sessions/day, performance debugging is operationally impossible at scale. You cannot answer "what's the p95 latency of the verdict call vs. the company scraper call" without building custom log parsing.

**Recommended architecture change:** Integrate OpenTelemetry. Add `@traced` decorators at key orchestration boundaries: `@traced("phase_1a_scrape")`, `@traced("phase_1c_fanout")`, `@traced("phase_2_verdict")`. The `call_agent` function creates a child span with attributes: `agent_name`, `model`, `provider`, `effort`, `prompt_hash`. The OTel SDK auto-exports to the observability backend (Jaeger, Honeycomb, Datadog — configurable via env vars). No vendor lock-in — OTel is the industry standard.

**Short-term fix:** Add structured timing logs to the orchestrator. At each phase boundary: `log.info("phase_1c_start", extra={"phase": "1c", "session_id": x, "monotonic_ns": time.monotonic_ns()})` and `log.info("phase_1c_end", extra={"phase": "1c", "duration_ms": delta})`. Cheap to add (one log line per phase), queryable with JSON log parsers (jq, Grafana Loki). Add a `phase` column to `llm_cost_log` so cost queries can GROUP BY pipeline phase. This gives 80% of the value of full tracing for <5% of the effort.

**Long-term target:** Full OpenTelemetry integration. Distributed tracing from the API request entry → LLM backend HTTP calls → external API calls → response. A trace for each forward_job has child spans for each Phase 1C agent (showing their individual latency, whether they hit a cache, whether they fell back). Cost and token usage are span attributes. The benchmark harness produces traces that can be compared across benchmark runs to detect performance regressions automatically.

---

### Finding 12: No Structured Error Taxonomy

**Severity:** Low
**Affected components:** All modules, `api/routes/`

**Current design:** Errors are Python exceptions (`BackendError`, `AgentCallFailed`, `CreditBudgetExceeded`, generic `Exception`) or plain strings. The orchestrator wraps almost everything in `except Exception as exc: log.warning(...)` and returns conservative fallback objects. The API returns HTTP 500 with a generic error body. There is no error code system — the frontend receives a string and has no structured way to determine what went wrong or what the user should do about it.

**Why risky:** Low for the demo where a human operator reads logs. Blocks production-quality error handling: when a user sees "Something went wrong," they cannot self-diagnose. Support cannot query "how many users hit the Sponsor Register timeout today" without grep + regex. The frontend cannot display contextual error messages ("The company database is temporarily unavailable — your verdict may have lower confidence" vs. "An unexpected error occurred") without fragile string-matching.

**Failure scenario:** User forwards a job. Companies House returns 503. Phase 1C `run_ch` catches the exception, returns `source_status=UNREACHABLE`. The verdict produces GO with reduced confidence. But the user has no visibility into this degradation. If they later have a bad experience (ghost job, below-market salary), they attribute it to the product, not to the unavailable data source. There's no error surfaced to the user — just a slightly lower confidence number they might not notice.

**Recommended architecture change:** Define a structured error catalog as a Python enum. `ErrorCode.SPONSOR_REGISTER_TIMEOUT`, `ErrorCode.COMPANIES_HOUSE_503`, `ErrorCode.SCRAPER_BLOCKED_BY_ROBOTS_TXT`, `ErrorCode.CONTENT_SHIELD_REJECTED`. Every exception carries an `error_code` and `user_message` (human-readable, safe for display). The API response includes the error code in a structured JSON field. The frontend maps error codes to localized, contextual messages. The `source_status` field on each Phase 1 output already does part of this — extend it to the API response layer.

**Short-term fix:** Add a `user_message` field to `BackendError` and `AgentCallFailed`. The API exception handler reads it and returns it in the 500 response body's `detail` field. At minimum, users see "The Sponsor Register lookup timed out — your verdict will be less confident than usual" instead of "Internal server error." Add a `warnings` list to the API response envelope — non-fatal degradation events (source_status=UNREACHABLE) are surfaced as warnings the frontend can render as info toasts.

**Long-term target:** Full error catalog with numeric codes, categorization (TRANSIENT, PERMANENT, CONFIGURATION, UPSTREAM_DEGRADED), and recommended user actions. Structured error logging where every error line has a `code` field (not just a message string). An error rate dashboard in the observability stack. Per-error-code cost tracking (how many LLM credits were wasted because a dependent Phase 1 check failed?).

---

### Finding 13: Test Infrastructure is Minimal — No DB Isolation, No LLM Mocks

**Severity:** Medium
**Affected components:** `tests/` directory (24 files), `conftest.py`

**Current design:** 24 test files. `conftest.py` is 7 lines — only adds `src/` to `sys.path`. No shared fixtures. No fixture for a `Storage` instance with an isolated in-memory database. No mock for `call_agent`. Tests that exercise real LLM calls check for the `SMOKE_TEST_MOCK=1` environment variable before making live calls. Integration tests appear to use the default SQLite path (`./data/askpicky.db`) which means they can interfere with each other and with a running development instance.

**Why risky:** Tests that touch the real database can interfere with each other if run in parallel (`pytest -n auto`). Tests that call real LLM APIs burn credits (~$0.02-$1.50 per call depending on the agent). Without mock infrastructure, developers are incentivized to skip running tests before pushing. CI costs accumulate linearly with every new test that makes a live LLM call. New contributors cannot run the full test suite without API keys configured.

**Failure scenario:** Developer runs `pytest` locally. 24 tests run — 8 make real LLM calls. Burns $5 in credits. Gets rate-limited by the API provider on test #17. Remaining 7 tests fail with HTTP 429 errors. Developer cannot distinguish "my change broke something" from "the API rate-limited me." Developer stops running tests before pushing. A regression in the citation validator (which has no mock) slips through to production.

**Recommended architecture change:** Build a proper test fixture layer in `conftest.py`:
- `in_memory_storage` fixture: `Storage(db_path=":memory:")` with WAL mode, all tables created
- `mock_call_agent` fixture: monkeypatches `llm.call_agent` to return pre-built fixture responses from `tests/fixtures/<agent_name>.json` files
- `mock_httpx` fixture: monkeypatches `httpx.AsyncClient` for external API calls (Companies House, Gazette)
- Test data factory functions: `make_user(user_type="uk_resident")`, `make_session(intent="forward_job")`, `make_verdict(decision="GO")`
- A `live_llm` marker for tests that should only run with real API keys and `--run-live` flag

**Short-term fix:** Add the `in_memory_storage` fixture and the `mock_call_agent` fixture to `conftest.py`. The Storage class already supports configurable `sqlite_db_path` — passing `:memory:` is natively supported by aiosqlite. Create 5-7 fixture JSON files for the most frequently called agents (verdict, jd_extractor, ghost_job_jd_scorer, triage, intent_router). Convert the top 10 most-edited tests to use these fixtures. Add `pytest.mark.live_llm` to tests that need real API access; CI skips those by default and runs them nightly.

**Long-term target:** Full test infrastructure. All LLM calls are mocked in unit tests by default. Integration tests use a real database but with seeded fixture data loaded from JSON. Contract tests validate that fixture files match the current Pydantic output schemas (CI catches fixture drift). CI runs `pytest -m "not live_llm"` on every push and `pytest -m live_llm` nightly. Minimum 80% line coverage on critical paths (orchestrator, verdict agent, content shield, citation validator).

---

### Finding 14: No Database Connection Pooling (Low Priority)

**Severity:** Low
**Affected components:** `storage.py` (`_connect` + `_ConnectionWithPragmas`)

**Current design:** Every database operation opens a fresh aiosqlite connection via `_connect()`, executes queries, and closes. The `_ConnectionWithPragmas` class applies `busy_timeout=5000` on each open. No connection reuse across multiple queries within the same HTTP request or session pipeline. A single `handle_forward_job` call opens and closes ~10 separate connections (one per storage operation).

**Why risky:** Low impact at single-user scale. SQLite file open is cheap (~1-2ms on SSD). At 10+ concurrent users with ~10 operations per session, the connection overhead is measurable but unlikely to be the bottleneck compared to LLM latency (which is seconds, not milliseconds). Queue behind Finding 1 — if migrating to PostgreSQL, connection pooling is built into SQLAlchemy's async engine.

**Short-term fix:** None needed for the current single-user demo. The `_connect` pattern is clean and correct for SQLite's concurrency model. Each connection gets its own busy_timeout, which is the recommended pattern.

**Long-term target:** SQLAlchemy async engine with connection pooling (pool_size=5, max_overflow=10). All queries within a single request share one connection from the pool. The pool handles lifecycle: checkout → use → return. This is the standard pattern for async web frameworks.

---

### Finding 15: Frontend and Backend Docker Images Versioned Independently

**Severity:** Low
**Affected components:** `docker-compose.yml`, `frontend/Dockerfile`

**Current design:** The `docker-compose.yml` builds two separate Docker images from independent Dockerfiles: `askpicky:latest` (backend, built from root Dockerfile) and `askpicky-frontend:latest` (Nginx + Vite build, built from `frontend/Dockerfile`). There is no mechanism to ensure API contract compatibility between the two images — they are tagged independently. An operator can deploy backend from commit `abc123` with frontend from commit `def456`, and nothing prevents or detects this mismatch.

**Why risky:** Low for the demo where both images are built from the same commit. In production, a CI pipeline that builds and deploys images independently could deploy frontend before backend (or vice versa). If the frontend expects a new API field that doesn't exist in the deployed backend version, the UI shows `undefined` or crashes. The window of incompatibility is typically 1-2 minutes during deploy, but it's a source of flaky UI errors.

**Recommended architecture change:** Tag both Docker images with the same git SHA or CI build number (e.g., `askpicky:sha-abc123`, `askpicky-frontend:sha-abc123`). The `docker-compose.yml` references the SHA-tagged images, not `:latest`. This guarantees frontend and backend are always deployed as an atomic unit from the same commit. Add a `/api/version` endpoint that returns the git SHA — the frontend fetches it on load and can detect version skew.

**Short-term fix:** In the CI pipeline: build both images, tag both with `$CI_COMMIT_SHA`, push both. The docker-compose uses `${CI_COMMIT_SHA:-latest}` as the tag. In development, `latest` is fine. In production, the SHA tag ensures atomicity. Add the `/api/version` endpoint (returns `{"version": "1.0.0", "commit": "abc123"}`) — 10 lines of code.

**Long-term target:** API versioning with deprecation headers (`/api/v1/` prefix). Contract testing between frontend and backend with generated TypeScript types from Pydantic schemas. A `schemas.py` → `frontend/src/types.ts` code generation step in CI ensures type safety across the boundary. The frontend build fails if it references an API field that doesn't exist in the backend's current schemas.

---

## 3. Target Architecture Proposal

```
                        ┌──────────────────────┐
                        │   Load Balancer       │
                        │   (nginx / Traefik)   │
                        └──────┬───────────────┘
                               │
              ┌────────────────┼──────────────────┐
              │                │                  │
    ┌─────────▼─────┐  ┌──────▼──────┐  ┌───────▼──────┐
    │  API Workers  │  │  API Workers │  │ Bot Long-Poll│
    │  (uvicorn × N)│  │  (uvicorn × N)│ │ (1 process)  │
    └───────┬───────┘  └──────┬───────┘  └──────┬───────┘
            │                 │                  │
            └────────┬────────┴──────────────────┘
                     │
        ┌────────────▼─────────────┐
        │    PostgreSQL + pgvector  │  ← Shared persistence + vector store
        │    (or managed PG)       │
        └────────────┬─────────────┘
                     │
        ┌────────────▼─────────────┐
        │   Redis (optional)       │  ← Session store + cache + Celery broker
        └────────────┬─────────────┘
                     │
        ┌────────────▼─────────────┐
        │   Celery / Temporal      │  ← Background workers
        │   (notification worker,  │     (notifications, FAISS rebuild,
        │    scheduled tasks)      │      outcome nudge scheduling)
        └────────────┬─────────────┘
                     │
        ┌────────────▼─────────────┐
        │   OTel Collector          │  ← Distributed tracing
        │   (Jaeger / Honeycomb)    │     (every LLM call = span)
        └──────────────────────────┘
```

**Key changes from current architecture:**
1. **PostgreSQL + pgvector** replaces SQLite + FAISS-in-memory for structured data and embeddings. FAISS retained as optional in-process acceleration cache, rebuilt from pgvector on restart.
2. **OAuth 2.0 auth layer** between all surfaces and the API. Rate limiting keyed per authenticated user. Row-level user_id isolation enforced at the Storage layer.
3. **Celery/Temporal workers** replace the in-process notification scheduler. At-least-once delivery with idempotency keys. Worker pool scales independently.
4. **OpenTelemetry** integrated at the `call_agent` and orchestrator level. Every LLM call is a span. Distributed tracing from API entry to provider response.
5. **Plugin-style agent registry** replaces the monolithic orchestrator. New agents self-register with a protocol. The orchestrator builds a DAG.
6. **Prompt hashing** in every `llm_cost_log` row for audit trails. Schema split into a package co-located with owning modules.
7. **CI-tagged Docker images** with matching SHA tags. `:latest` only in development.

---

## 4. Major Design Risks

| Risk | Likelihood | Impact | Mitigation Status |
|------|-----------|--------|-------------------|
| **SQLite write contention at >5 concurrent users** | High | High | Short-term: write semaphore + retry. Long-term: PostgreSQL migration |
| **No auth — data cross-contamination on multi-user deploy** | Certain | Critical | Short-term: user_id guardrails in Storage. Long-term: OAuth 2.0 |
| **Notification scheduler silent data loss on crash** | Medium | Critical | Short-term: two-phase dispatch. Long-term: Celery/Temporal |
| **LangGraph orchestrator stub gives false confidence** | Low (disabled) | High | Short-term: remove feature flag. Long-term: full implementation |
| **Prompt injection via scraped JD content** | Medium | High | Mitigated: Content Shield Tier 1+2 active. Add: prompt hash auditing |
| **GPT-5.4 primary provider outage** | Low | High | Mitigated: DeepSeek Pro fallback implemented in verdict agent |
| **Playwright blocked by anti-bot detection** | Medium | Medium | Mitigated: Firecrawl API fallback implemented in company_scraper |
| **FAISS index silently stale across surfaces** | High | Medium | Short-term: version-check-and-reload. Long-term: pgvector eliminates |
| **DeepSeek API key missing — silent Anthropic fallback at 10x cost** | Medium | High | Mitigated: startup warning. Add: CI check for production config |
| **Cost overrun — budget enforcement disabled in test mode** | Medium | Medium | Mitigated: budget check in llm.py. Add: pre-commit hook for high-cost changes |

---

## 5. Refactoring Roadmap

### Phase 1: Production Hardening (Weeks 1-2)

| # | Item | Finding | Effort | Dependency |
|---|------|---------|--------|------------|
| 1 | Add `prompt_hash` to `llm_cost_log` | F6 | 2h | None |
| 2 | Add per-API circuit breaker with cooldown | F7 | 4h | None |
| 3 | FAISS version check + reload on staleness | F4 | 2h | None |
| 4 | Two-phase notification dispatch (at-least-once) | F3 | 4h | None |
| 5 | SQLite write semaphore + retry on `save_*` ops | F1 | 2h | None |
| 6 | Extract Phase 1C fan-out to `pipeline/phase1_fanout.py` | F5 | 4h | None |
| 7 | Add test fixtures: `in_memory_storage`, `mock_call_agent`, 5-7 fixture JSONs | F13 | 8h | None |
| 8 | Remove `ENABLE_LANGGRAPH_ORCHESTRATOR` feature flag | F8 | 1h | None |
| 9 | Add `/api/version` endpoint with git SHA | F15 | 0.5h | None |

**Phase 1 total: ~27.5 hours**

### Phase 2: Multi-User Readiness (Weeks 3-4)

| # | Item | Finding | Effort | Dependency |
|---|------|---------|--------|------------|
| 1 | Implement OAuth 2.0 with session cookies | F2 | 16h | None |
| 2 | Add user_id validation guards at Storage layer | F2 | 4h | #1 |
| 3 | Migrate SQLite → PostgreSQL with SQLAlchemy async | F1 | 16h | #1 |
| 4 | Migrate FAISS → pgvector (canonical store) | F4 | 8h | #3 |
| 5 | Implement Alembic migration chain | F1 | 4h | #3 |
| 6 | Add structured error codes to all API responses | F12 | 4h | None |
| 7 | Add `warnings` field to API response envelope | F12 | 2h | #6 |

**Phase 2 total: ~54 hours**

### Phase 3: Observability (Weeks 5-6)

| # | Item | Finding | Effort | Dependency |
|---|------|---------|--------|------------|
| 1 | Integrate OpenTelemetry SDK | F11 | 8h | None |
| 2 | Add `@traced` decorators at phase boundaries | F11 | 4h | #1 |
| 3 | Add `phase` column to `llm_cost_log` | F11 | 1h | None |
| 4 | Structured phase timing logs (short-term alternative) | F11 | 2h | None |
| 5 | CI-tagged Docker images with matching SHA | F15 | 2h | None |
| 6 | Add `content_hash` to `scraped_pages` | F9 | 4h | None |
| 7 | JD page TTL reduction (24h → 1h) | F9 | 1h | #6 |

**Phase 3 total: ~22 hours**

### Phase 4: Architecture Cleanup (Weeks 7-8)

| # | Item | Finding | Effort | Dependency |
|---|------|---------|--------|------------|
| 1 | Full LangGraph orchestrator implementation | F8 | 24h | Phase 2 |
| 2 | Plugin-style agent registry (Phase 1 + Phase 4) | F5 | 16h | Phase 1 #6 |
| 3 | Split `schemas.py` into package | F10 | 8h | None |
| 4 | Replace in-process scheduler with Celery worker | F3 | 12h | Phase 2 #3 |
| 5 | Content-hash-based conditional re-fetch for scraper | F9 | 8h | Phase 3 #6 |
| 6 | Generate TypeScript types from Pydantic schemas | F15 | 4h | Phase 2 #5 |

**Phase 4 total: ~72 hours**

### Phase 5: Polish (Ongoing)

- A/B testing infrastructure for prompt variant comparison
- Learned signal weights from outcome data (original architecture gap #7)
- Frontend-backend contract test suite
- Cost-per-intent dashboard (user-facing credit transparency)
- Error rate dashboard in observability stack
- Automated prompt version bumping in CI

---

## 6. Open Architectural Decisions

1. **PostgreSQL vs. tuned SQLite for multi-user:** PostgreSQL is the low-risk standard choice — it solves FAISS sharing, concurrent writes, connection pooling, and gives us Alembic migrations. But it adds operational surface area (require a managed PG service or a Docker container with persistent volume). For a single-machine deploy with <50 concurrent users, a tuned SQLite with WAL mode + write semaphore may suffice. **Decision deferred to multi-user sizing requirements and deploy environment constraints.**

2. **OAuth provider selection:** Options in increasing order of implementation complexity: (a) Google OAuth — one button, zero password management, covers most users; (b) GitHub OAuth — targets the developer audience specifically; (c) email magic link — lowest friction for non-technical users, no third-party dependency. **Decision depends on target user demographic research.**

3. **Celery vs. Temporal for durable execution:** Celery (Redis + Python workers) is simpler to operate but offers weaker guarantees (at-least-once delivery, no native retry policy per task type, no workflow versioning). Temporal provides exactly-once semantics, durable timers, and workflow versioning, but requires running a Temporal server (operational complexity). For notification scheduling at current scale, Celery is sufficient. For future multi-hour LLM agent workflows (multi-step CV tailoring with user input), Temporal's durability is compelling. **Decision: start with Celery; evaluate Temporal when agent workflows exceed 5 minutes.**

4. **Prompt versioning strategy:** (a) Runtime hashing (SHA-256 of prompt text, stored in cost log) — simple, zero-process, already specified as short-term fix. (b) Semantic versioning in frontmatter (`version: "1.2.0"`) — human-readable, allows semver-style breaking change detection. (c) Both: semver frontmatter for human authors, runtime hash for machine audit. **Decision: implement (a) immediately; add (c) as the long-term target when the prompt iteration cadence justifies frontmatter overhead.**

5. **Monorepo vs. multi-repo for frontend:** Currently a monorepo with `frontend/` as a subdirectory. For the 1.0 release, evaluate whether the frontend should be extracted to a separate repository with independent release cadence. Arguments for staying monorepo: atomic commits across frontend + backend, simpler CI, single version number. Arguments for multi-repo: independent deploy velocity, smaller Docker images, dedicated CI. **Decision: stay monorepo through 1.0; re-evaluate if frontend deploy frequency significantly outpaces backend.**

6. **FAISS retention after pgvector migration:** pgvector's HNSW index provides comparable recall to FAISS IndexFlatIP at sub-1M vectors. FAISS's advantage is GPU-accelerated search, irrelevant at current scale. Options: (a) remove FAISS entirely, use only pgvector; (b) keep FAISS as an in-process read cache populated from pgvector on startup (reduces DB load for repeated queries). **Decision: (b) — keep FAISS as an optional read cache, default to pgvector as canonical. This preserves the low-latency retrieval path without requiring an additional service.**
