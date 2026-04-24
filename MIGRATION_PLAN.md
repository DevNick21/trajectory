# Trajectory — Dual-Surface Migration Plan

**Status:** Approved, ready to execute
**Author:** Kene (with AI assistance)
**Last updated:** 2026-04-24
**Target:** Hackathon submission + portfolio piece

---

## Table of contents

1. [Decisions](#1-decisions)
2. [Scope: what "web-primary + Telegram cameo" means](#2-scope-what-web-primary--telegram-cameo-means)
3. [Architecture](#3-architecture)
4. [Pre-migration bug fixes](#4-pre-migration-bug-fixes)
5. [File-by-file work plan](#5-file-by-file-work-plan)
6. [Known dual-surface risks](#6-known-dual-surface-risks)
7. [API contract](#7-api-contract)
8. [Onboarding wizard redesign](#8-onboarding-wizard-redesign)
9. [Frontend stack and structure](#9-frontend-stack-and-structure)
10. [Demo video script](#10-demo-video-script)
11. [Portfolio narrative](#11-portfolio-narrative)
12. [Effort estimate](#12-effort-estimate)
13. [Architecture Decision Records](#13-architecture-decision-records)
14. [Deferred items](#14-deferred-items)

---

## 1. Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Division of labour | **Web-primary + Telegram cameo** | 85% of portfolio narrative for 65% of work; demo video identical to full-parity |
| User identity | **Same single user ID in both surfaces** | Hardcode `DEMO_USER_ID` env var; single-user localhost only |
| Onboarding sync | **Not needed cross-surface** (web-only wizard) | Telegram users redirected to web for onboarding; simplifies state management |
| Full-prep SSE | **Build it** | Demo video money shot — all four generators streaming in parallel |
| Onboarding wizard | **Web only** | Telegram's `/start` redirects un-onboarded users to web |
| Frontend stack | **Vite + React 18 + TS + Tailwind + shadcn/ui** | Single-page localhost tool; Next.js overkill |
| State management | **TanStack Query** (server) + **Zustand** if needed (client) | Server state dominates; most client state lives in URL or forms |
| Forms | **React Hook Form + Zod** | Tight Pydantic-parity schemas |
| SSE | **Native EventSource** | No dependency needed; simple push from queue |

---

## 2. Scope: what "web-primary + Telegram cameo" means

### Telegram keeps (unchanged code)

- `/start` — welcome message, directs un-onboarded users to web
- `forward_job` URL paste → Phase 1 pipeline → verdict
- `full_prep` command after a verdict → generates all 4 packs, sends as documents
- `/help`, `/status`, existing rate limiting

### Telegram explicitly does NOT get

- Onboarding (web only)
- Profile editing (web only)
- Session browsing / history UI (chat log is the history)
- File preview (just `send_document` as today)

### Web gets everything

- Onboarding wizard (redesigned — tap options, typed forms, progressive narrowing)
- Dashboard (forward job → live Phase 1 stream → verdict → pack generation)
- Session browser + detail pages
- Profile view + edit
- File viewing/download
- Parallel `full_prep` with live SSE progress

### Cross-surface contract

- **Single `user_profiles` row** keyed by `DEMO_USER_ID` env var
- Both surfaces read same profile, career entries, FAISS index, scraped_pages, generated files
- Onboarding state ephemeral on web (wizard session), not persisted cross-process
- Un-onboarded Telegram users redirected to web with link

### Out of scope (deferred)

- Cross-surface in-flight session visibility (start Phase 1 on Telegram, see it complete on web)
- FAISS staleness fix (both processes cache their own index — known limitation)
- Multi-user auth
- Web mobile optimisation (desktop-first for demo)

---

## 3. Architecture

### System diagram

```
┌──────────────────┐         ┌──────────────────┐
│  Telegram client │         │  Web (Vite+React)│
│   (mobile, you)  │         │  (desktop, you)  │
└────────┬─────────┘         └────────┬─────────┘
         │ long-poll                  │ HTTP + SSE
         │                            │
┌────────▼─────────┐         ┌────────▼─────────┐
│   bot/app.py     │         │   api/app.py     │
│   handlers       │         │   routes         │
└────────┬─────────┘         └────────┬─────────┘
         │                            │
         └────────────┬───────────────┘
                      │
        ┌─────────────▼──────────────┐
        │  orchestrator.py           │
        │  sub_agents/               │
        │  validators/               │
        │  renderers/                │
        └─────────────┬──────────────┘
                      │
        ┌─────────────▼──────────────┐
        │  SQLite (single DB)        │
        │  - user_profiles           │
        │  - career_entries          │
        │  - writing_style_profiles  │
        │  - sessions                │
        │  - scraped_pages           │
        │  - llm_cost_log            │
        │  FAISS index (single file) │
        │  data/generated/ (files)   │
        └────────────────────────────┘
```

**Two processes, one database, one identity.**

### Directory structure (post-migration)

```
trajectory/
├── src/trajectory/
│   ├── api/                    ← NEW
│   │   ├── __init__.py
│   │   ├── app.py              ← FastAPI instance
│   │   ├── dependencies.py     ← get_storage, get_current_user
│   │   ├── schemas.py          ← Pydantic request/response
│   │   ├── sse.py              ← SSE formatting helper
│   │   └── routes/
│   │       ├── __init__.py
│   │       ├── health.py
│   │       ├── profile.py
│   │       ├── onboarding.py
│   │       ├── sessions.py     ← forward_job SSE + session CRUD
│   │       ├── pack.py         ← 4 generators + full_prep SSE
│   │       └── files.py
│   │
│   ├── bot/                    ← KEEP (minor emitter wiring)
│   │   └── ... (unchanged structure)
│   │
│   ├── progress/               ← NEW
│   │   ├── __init__.py
│   │   ├── emitter.py          ← ProgressEmitter Protocol + NoOpEmitter
│   │   ├── telegram_emitter.py ← wraps PhaseOneProgressStreamer
│   │   └── sse_emitter.py      ← pushes events to asyncio.Queue
│   │
│   ├── orchestrator.py         ← SMALL REFACTOR (accept emitter param)
│   ├── schemas.py              ← SMALL FIX (good_role_signal literal)
│   ├── sub_agents/             ← UNCHANGED
│   ├── validators/             ← UNCHANGED
│   ├── storage.py              ← UNCHANGED
│   ├── renderers/              ← UNCHANGED
│   └── llm.py                  ← UNCHANGED
│
├── frontend/                   ← NEW (sibling to src/)
│   ├── package.json
│   ├── vite.config.ts
│   ├── tailwind.config.ts
│   ├── tsconfig.json
│   ├── index.html
│   └── src/
│       ├── main.tsx
│       ├── App.tsx
│       ├── lib/
│       │   ├── api.ts          ← typed fetch wrappers
│       │   ├── sse.ts          ← EventSource wrapper
│       │   └── types.ts        ← shared types with backend
│       ├── pages/
│       │   ├── Dashboard.tsx
│       │   ├── SessionDetail.tsx
│       │   └── Onboarding.tsx
│       └── components/
│           ├── ui/             ← shadcn primitives
│           ├── ForwardJobForm.tsx
│           ├── Phase1Stream.tsx
│           ├── VerdictCard.tsx
│           ├── SessionList.tsx
│           └── PackGenerator.tsx
│
├── scripts/
│   ├── run_bot.sh
│   ├── run_api.sh              ← NEW
│   ├── run_web.sh              ← NEW
│   └── smoke_tests/
│       ├── bot_boot.py
│       └── api_boot.py         ← NEW
│
├── data/generated/{session_id}/
├── .env.example                ← UPDATED (DEMO_USER_ID, API_PORT, WEB_ORIGIN)
├── PROCESS.md                  ← UPDATED (ADRs 001-003)
└── MIGRATION_PLAN.md           ← THIS FILE
```

### Running both surfaces

```bash
# Terminal 1
python -m trajectory.bot.app

# Terminal 2
./scripts/run_api.sh  # uvicorn on :8000

# Terminal 3
cd frontend && npm run dev  # Vite on :5173
```

Both Python processes connect to same SQLite file. aiosqlite serialises writes.

### Identity

```bash
# .env
DEMO_USER_ID=<your_telegram_user_id>
TELEGRAM_BOT_TOKEN=...
ANTHROPIC_API_KEY=...
API_PORT=8000
WEB_ORIGIN=http://localhost:5173
```

**Telegram adapter:**
```python
user_id = str(update.effective_user.id)
# (will match DEMO_USER_ID since you're the only user)
```

**Web adapter:**
```python
# api/dependencies.py
async def get_current_user_id() -> str:
    return settings.demo_user_id

async def get_current_user(
    user_id: str = Depends(get_current_user_id),
    storage: Storage = Depends(get_storage),
) -> UserProfile:
    profile = await storage.get_user_profile(user_id)
    if profile is None:
        raise HTTPException(404, "Profile not found — complete onboarding first")
    return profile
```

Both land in the same `user_profiles` row. No auth, no linking. Correct for single-user.

---

## 4. Pre-migration bug fixes

These block migration work — fix before Wave 1.

### Bug 1: `good_role_signal` CareerEntry kind not in Literal (95% confidence)

**Location:** `src/trajectory/schemas.py` + `src/trajectory/bot/onboarding.py::finalise_onboarding`

**Symptom:** Pydantic ValidationError on insert when onboarding completes.

**Fix:** Add `"good_role_signal"` to the `kind` Literal in `CareerEntry`:

```python
# src/trajectory/schemas.py
class CareerEntry(BaseModel):
    kind: Literal[
        "cv_bullet", "qa_answer", "star_polish", "project_note",
        "preference", "motivation", "deal_breaker", "good_role_signal",  # ← add
        "writing_sample", "conversation",
    ]
    ...
```

### Bug 2: Ghost detector failure kills all Phase 1 (80% confidence)

**Location:** `src/trajectory/orchestrator.py::handle_forward_job`

**Symptom:** `run_ghost` closure re-raises inside `asyncio.gather(..., return_exceptions=False)`, unlike other Phase 1C agents which catch and fall back. Single-point-of-failure for entire verdict.

**Fix:** Wrap in try/except with fallback, matching pattern of sibling agents:

```python
async def run_ghost():
    try:
        return await ghost_detector.detect(...)
    except Exception as e:
        logger.warning("ghost_detector_failed", error=str(e))
        return GhostDetectionResult(is_ghost=False, confidence=0.0, reasoning="detector failed, defaulted to not-ghost")
```

### Grep check before starting

```bash
rg "from telegram" src/ --files-with-matches
```

Should return **only** files under `src/trajectory/bot/`. If any other module imports from `telegram`, that's a seam violation to fix first.

---

## 5. File-by-file work plan

Organised as dependency waves. Execute sequentially; each wave ends in a commit.

### Wave 0 — Prep (0.5 days)

| File | Action | Why |
|---|---|---|
| `src/trajectory/schemas.py` | Add `"good_role_signal"` to `CareerEntry.kind` Literal | Bug 1 |
| `src/trajectory/orchestrator.py` | Wrap `run_ghost` in try/except | Bug 2 |
| Grep `rg "from telegram" src/` | Confirm only `bot/` imports from telegram | Seam check |
| `PROCESS.md` | Write ADR-001: "Dual surface, web-primary" | Capture decision |
| `MIGRATION_PLAN.md` | This file, committed to repo | Reference during work |

**Commit:** `fix: pre-migration cleanup — schema literal + ghost fallback`

### Wave 1 — Progress abstraction (1 day)

| File | Action |
|---|---|
| `src/trajectory/progress/__init__.py` | New package |
| `src/trajectory/progress/emitter.py` | `ProgressEmitter` Protocol + `NoOpEmitter` |
| `src/trajectory/progress/telegram_emitter.py` | Wraps existing `PhaseOneProgressStreamer` |
| `src/trajectory/progress/sse_emitter.py` | Pushes events to `asyncio.Queue` |
| `src/trajectory/orchestrator.py` | `handle_forward_job` accepts `emitter: ProgressEmitter = NoOpEmitter()`, replaces `bot/chat_id/message_id` params |
| `src/trajectory/bot/handlers.py` | Construct `TelegramEmitter`, pass to orchestrator |
| `scripts/smoke_tests/bot_boot.py` | Re-verify Telegram flow with emitter refactor |

**Commit:** `refactor: extract ProgressEmitter protocol for transport-agnostic progress`

### Wave 2 — FastAPI skeleton (1 day)

| File | Action |
|---|---|
| `src/trajectory/api/__init__.py` | New package |
| `src/trajectory/api/app.py` | FastAPI instance, CORS (allow `WEB_ORIGIN`), lifespan hook for storage init |
| `src/trajectory/api/dependencies.py` | `get_storage`, `get_current_user_id`, `get_current_user` |
| `src/trajectory/api/routes/__init__.py` | Router registration |
| `src/trajectory/api/routes/health.py` | `GET /health` for sanity |
| `pyproject.toml` | Add `fastapi`, `uvicorn[standard]`, `python-multipart`, `sse-starlette` |
| `.env.example` | Add `DEMO_USER_ID`, `API_PORT=8000`, `WEB_ORIGIN=http://localhost:5173` |
| `scripts/run_api.sh` | `uvicorn trajectory.api.app:app --reload --port ${API_PORT}` |
| `scripts/smoke_tests/api_boot.py` | Start API, hit `/health`, assert 200 |

**Commit:** `feat: FastAPI skeleton with health endpoint`

### Wave 3 — Read routes (1 day)

Lowest-risk endpoints first. Proves the glue works.

| File | Endpoints |
|---|---|
| `src/trajectory/api/schemas.py` | Pydantic request/response models |
| `src/trajectory/api/routes/profile.py` | `GET /api/profile` |
| `src/trajectory/api/routes/sessions.py` | `GET /api/sessions`, `GET /api/sessions/{id}` |
| `src/trajectory/api/routes/files.py` | `GET /api/files/{session_id}/{filename}` with path-traversal guard |

**Commit:** `feat: read-only API endpoints (profile, sessions, files)`

### Wave 4 — Forward job + SSE (2 days)

The interesting one. Money-shot demo endpoint.

| File | Action |
|---|---|
| `src/trajectory/api/sse.py` | SSE helper: formats `{event, data}` → `data: <json>\n\n` |
| `src/trajectory/api/routes/sessions.py` | Add `POST /api/sessions/forward_job` returning SSE stream |

**Pattern:**

```python
@router.post("/sessions/forward_job")
async def forward_job(
    req: ForwardJobRequest,
    user: UserProfile = Depends(get_current_user),
    storage: Storage = Depends(get_storage),
):
    queue: asyncio.Queue = asyncio.Queue()
    emitter = SSEEmitter(queue)

    async def runner():
        try:
            session = Session.new(user_id=user.user_id, job_url=req.job_url)
            await storage.save_session(session)
            bundle, verdict = await handle_forward_job(
                job_url=req.job_url, user=user, session=session,
                storage=storage, emitter=emitter,
            )
            await queue.put({"type": "verdict", "data": verdict.model_dump()})
        except Exception as e:
            logger.exception("forward_job_failed")
            await queue.put({"type": "error", "data": {"message": str(e)}})
        finally:
            await emitter.close()

    asyncio.create_task(runner())
    return EventSourceResponse(event_stream(queue))
```

**Commit:** `feat: SSE forward_job endpoint with live Phase 1 progress`

### Wave 5 — Pack generators + full_prep SSE (1.5 days)

Four individual generator endpoints + parallel full_prep SSE (the demo video money shot #2).

| File | Endpoints |
|---|---|
| `src/trajectory/api/routes/pack.py` | `POST /api/sessions/{id}/cv`, `/cover_letter`, `/questions`, `/salary`, `/full_prep` |

Individual endpoints are simple async responses (10-30s each, loading spinner OK).

`POST /api/sessions/{id}/full_prep` is the fancy one: SSE stream fanning out `asyncio.gather(cv, cover_letter, questions, salary)` with events for each completing.

```python
@router.post("/sessions/{id}/full_prep")
async def full_prep(
    id: str,
    user: UserProfile = Depends(get_current_user),
    storage: Storage = Depends(get_storage),
):
    session = await storage.get_session(id)
    # ... authz check ...
    queue: asyncio.Queue = asyncio.Queue()

    async def generate(name: str, generator_fn):
        await queue.put({"type": "started", "generator": name})
        try:
            result = await generator_fn(session, user, storage)
            await queue.put({"type": "completed", "generator": name, "data": result.model_dump()})
        except Exception as e:
            await queue.put({"type": "failed", "generator": name, "error": str(e)})

    async def runner():
        await asyncio.gather(
            generate("cv", generate_cv),
            generate("cover_letter", generate_cover_letter),
            generate("questions", generate_questions),
            generate("salary", generate_salary),
        )
        await queue.put({"type": "done"})

    asyncio.create_task(runner())
    return EventSourceResponse(event_stream(queue))
```

**Commit:** `feat: pack generator endpoints + parallel full_prep SSE`

### Wave 6 — Frontend scaffold (1 day)

| Item | Details |
|---|---|
| `frontend/package.json` | Vite + React 18 + TS + Tailwind + shadcn/ui + TanStack Query + React Hook Form + Zod + react-router-dom |
| `frontend/vite.config.ts` | Proxy `/api/*` to `http://localhost:8000`, proxy SSE correctly |
| `frontend/tailwind.config.ts` | shadcn defaults |
| `frontend/src/App.tsx` | React Router: `/`, `/sessions/:id`, `/onboarding` |
| `frontend/src/lib/api.ts` | Typed fetch wrappers — one per endpoint |
| `frontend/src/lib/sse.ts` | EventSource wrapper with typed event handlers |
| `frontend/src/lib/types.ts` | TypeScript types mirroring Pydantic responses |
| `frontend/src/components/ui/` | shadcn Button, Card, Input, Dialog, Progress, Badge, Skeleton |

**Commit:** `feat: frontend scaffold (Vite + React + Tailwind + shadcn)`

### Wave 7 — Dashboard page (2 days) — DEMO CENTREPIECE

The page that sells the whole project in 15 seconds of video.

**Layout:**

```
┌────────────────────────────────────────────────────────┐
│ Trajectory                                       [you] │
├────────────────────────────────────────────────────────┤
│  ┌──────────────────────────────────────────────────┐ │
│  │  Paste a job URL                                 │ │
│  │  [https://...                        ] [Check]   │ │
│  └──────────────────────────────────────────────────┘ │
│                                                        │
│  When Phase 1 is running:                             │
│  ┌──────────────────────────────────────────────────┐ │
│  │  ✓ Role parser                          0.8s     │ │
│  │  ✓ Company resolver                     1.2s     │ │
│  │  ✓ SOC guess                            0.6s     │ │
│  │  ⟳ Salary threshold...                           │ │
│  │  ⟳ Sponsor register...                           │ │
│  │  ○ Ghost detector                                │ │
│  │  ○ Content shield                                │ │
│  └──────────────────────────────────────────────────┘ │
│                                                        │
│  When verdict lands:                                  │
│  ┌──────────────────────────────────────────────────┐ │
│  │  [GO]  Senior Data Scientist · AstraZeneca       │ │
│  │  £75k · Sponsor confirmed · SOC 2433 threshold ✓ │ │
│  │  [Generate pack ▸]                               │ │
│  └──────────────────────────────────────────────────┘ │
│                                                        │
│  Recent sessions                                      │
│  ... list ...                                         │
└────────────────────────────────────────────────────────┘
```

| Component | Purpose |
|---|---|
| `<ForwardJobForm />` | URL input + submit |
| `<Phase1Stream />` | Consumes SSE, renders agent list with tick states |
| `<VerdictCard />` | GO / CAUTION / NO_GO badge + evidence summary |
| `<SessionList />` | Recent sessions table |

**Commit:** `feat: dashboard page with live Phase 1 streaming`

### Wave 8 — Session detail + pack generation (1.5 days)

Navigate to `/sessions/:id` from dashboard. Shows:

- Full verdict with expandable evidence per agent
- "Generate pack" buttons for each of the 4 generators OR "Full Prep" for all four in parallel
- When a pack generates: file links appear
- Cost breakdown from `llm_cost_log`

| Component | Purpose |
|---|---|
| `<SessionDetail />` | Page-level component |
| `<VerdictEvidence />` | Expandable per-agent evidence |
| `<PackGenerator />` | 4 individual buttons + 1 full_prep SSE button |
| `<FileList />` | Generated files with download links |
| `<CostBreakdown />` | LLM cost summary |

**Commit:** `feat: session detail page with pack generators`

### Wave 9 — Onboarding wizard (3 days) — UX UPGRADE

Web only. Telegram redirects un-onboarded users here. See [Section 8](#8-onboarding-wizard-redesign).

**Commit:** `feat: web onboarding wizard with tap options + typed forms`

### Wave 10 — Telegram redirect (0.25 days)

Small addition to `bot/handlers.py`:

```python
async def start(update, context):
    user_id = str(update.effective_user.id)
    storage = context.bot_data["storage"]
    profile = await storage.get_user_profile(user_id)
    if profile is None:
        await update.message.reply_text(
            "👋 Welcome to Trajectory.\n\n"
            "Set up your profile on the web app first:\n"
            f"{settings.web_url}\n\n"
            "Takes ~10 minutes. Come back here to forward job URLs."
        )
        return
    # existing welcome flow

async def _handle_forward_job(update, context):
    user_id = str(update.effective_user.id)
    storage = context.bot_data["storage"]
    profile = await storage.get_user_profile(user_id)
    if profile is None:
        await update.message.reply_text(
            f"Please complete onboarding on the web app first: {settings.web_url}"
        )
        return
    # existing forward_job flow
```

**Commit:** `feat: telegram redirects un-onboarded users to web`

### Wave 11 — Testing both surfaces (0.75 days)

| Test | How |
|---|---|
| Onboard on web, forward job on Telegram | Manual — should work out of the box |
| Forward job on web, generate full_prep, download files | Manual + automated smoke test |
| Forward job on Telegram, check session appears in web `/sessions` | Manual |
| FAISS staleness | Add career entry via web, restart bot, confirm Telegram sees it |
| Path traversal attempt on file endpoint | Unit test |
| Parallel full_prep — all 4 generators complete | Integration test |

**Commit:** `test: cross-surface integration smoke tests`

### Wave 12 — Demo video + polish (1 day)

Record per script in [Section 10](#10-demo-video-script). Polish pass on CSS, loading states, error boundaries.

**Commit:** `docs: demo video + final polish`

---

## 6. Known dual-surface risks

Listed because "buffer for bugs" is where estimates die.

| # | Risk | Severity | Mitigation |
|---|---|---|---|
| 1 | State drift between surfaces | Low | Nothing cached cross-request; fresh loads every handler |
| 2 | FAISS index concurrent write — each process has own in-memory instance | Medium | **Accept staleness until restart** (single-user demo); document in PROCESS.md |
| 3 | Scraped page cache hits across surfaces | None (positive) | Shared table; free cache reuse |
| 4 | Session UUID collisions | None | `uuid.uuid4()` collision probability zero |
| 5 | Phase 1 in-flight when surface switches | Low | Can't see completion cross-surface; skip for demo |
| 6 | File handles leaking | Fixed | `FileResponse` handles web side; bot already fixed |
| 7 | Onboarding parser double-charge | None (only web) | N/A — onboarding web-only |
| 8 | Path traversal via `/api/files/` | High (if exploited) | `Path(filename).name` strips `../`; authz check on session ownership |
| 9 | CORS misconfiguration leaking API | Medium | Strict `WEB_ORIGIN` allowlist; no wildcards |
| 10 | SSE connection leak on browser close | Low | `request.is_disconnected()` check; cancel task on disconnect |

---

## 7. API contract

### Endpoint reference

| Method | Path | Purpose | Response type |
|---|---|---|---|
| `GET` | `/health` | Sanity check | JSON |
| `GET` | `/api/profile` | Current user profile | JSON |
| `GET` | `/api/onboarding` | Current onboarding state + next prompt | JSON |
| `POST` | `/api/onboarding/answer` | Submit answer, advance state | JSON |
| `POST` | `/api/onboarding/finalise` | Finalise → UserProfile + WritingStyleProfile | JSON |
| `POST` | `/api/sessions/forward_job` | Phase 1 pipeline with live progress | **SSE** |
| `GET` | `/api/sessions` | List recent sessions | JSON |
| `GET` | `/api/sessions/{id}` | Full session detail including verdict | JSON |
| `POST` | `/api/sessions/{id}/cv` | Generate CV | JSON |
| `POST` | `/api/sessions/{id}/cover_letter` | Generate cover letter | JSON |
| `POST` | `/api/sessions/{id}/questions` | Interview questions | JSON |
| `POST` | `/api/sessions/{id}/salary` | Salary strategy | JSON |
| `POST` | `/api/sessions/{id}/full_prep` | All 4 generators in parallel | **SSE** |
| `GET` | `/api/files/{session_id}/{filename}` | Serve generated files | File |

### SSE event schema

Every SSE endpoint emits JSON events with a `type` discriminator:

**Phase 1 events** (`/sessions/forward_job`):

```typescript
type Phase1Event =
  | { type: "agent_started"; agent: string }
  | { type: "agent_complete"; agent: string; duration_ms: number }
  | { type: "agent_failed"; agent: string; error: string }
  | { type: "verdict"; data: Verdict }
  | { type: "error"; data: { message: string } }
  | { type: "done" };
```

**Full prep events** (`/sessions/{id}/full_prep`):

```typescript
type FullPrepEvent =
  | { type: "started"; generator: "cv" | "cover_letter" | "questions" | "salary" }
  | { type: "completed"; generator: string; data: PackResult }
  | { type: "failed"; generator: string; error: string }
  | { type: "done" };
```

### Request/response Pydantic models (abridged)

```python
# src/trajectory/api/schemas.py

class ForwardJobRequest(BaseModel):
    job_url: HttpUrl

class SessionSummary(BaseModel):
    id: str
    job_url: str
    created_at: datetime
    verdict: Literal["GO", "CAUTION", "NO_GO"] | None
    role_title: str | None
    company_name: str | None

class SessionDetailResponse(BaseModel):
    id: str
    job_url: str
    created_at: datetime
    research_bundle: ResearchBundle
    verdict: Verdict | None
    generated_files: list[GeneratedFile]
    cost_summary: CostSummary

class OnboardingStateResponse(BaseModel):
    state: str
    next_prompt: str | None
    progress: dict[str, bool]  # {stage: completed}
    done: bool

class OnboardingAnswerRequest(BaseModel):
    stage: str
    # Typed fields — backend picks what matches the stage
    text_answer: str | None = None
    structured: dict[str, Any] | None = None

class OnboardingAnswerResponse(BaseModel):
    state: str
    follow_up: str | None
    next_prompt: str | None
    done: bool

class PackResult(BaseModel):
    file_urls: list[str]
    metadata: dict[str, Any]
    cost_usd: float
    duration_ms: int
```

---

## 8. Onboarding wizard redesign

Web only. This is the biggest UX win of the migration.

### Key insight

Web transition lets you **drop the LLM parser for structured stages**. Tap options and typed forms populate fields directly. Only stages capturing voice need LLM parsing.

### Stage-by-stage

| Stage | Current (Telegram) | Web redesign | LLM needed? |
|---|---|---|---|
| Name | Free text | Single text input | No |
| Money | Free text → parser | Two numeric inputs (floor + target) + currency dropdown | No |
| Visa | Free text → parser | Radio (British / ILR / Graduate / Skilled Worker / Other) + conditional expiry date | No |
| Location | Free text → parser | Combobox (UK cities + "Other") | No |
| Life | Free text → parser | Checkboxes for common constraints + free-text "anything else" | No |
| Current employment | Free text → parser | Dropdown (employed / unemployed / student / contract) + employer field | No |
| Motivations | Free text → LLM parser | **Keep free-text** — captures voice | Yes |
| Deal breakers | Free text → LLM parser | **Keep free-text** — captures voice | Yes |
| Good role signals | Free text → LLM parser | **Keep free-text** — captures voice | Yes |
| Writing sample | Free text paste | Large textarea + optional file upload | Yes (for embedding) |

### Savings

- **Cost:** ~$0.10 per onboarding (skip 6 LLM parser calls)
- **Latency:** ~40s (no parser round-trips for structured fields)
- **Reliability:** no parser misinterpretation for typed data

### Finalisation (unchanged)

Same `finalise_onboarding` code path, same CareerEntry + WritingStyleProfile writes, same FAISS seeding. The wizard just populates the answers dict differently.

### Wizard UX pattern

```
┌─────────────────────────────────────────────────┐
│  Trajectory · Setup                       2/10  │
├─────────────────────────────────────────────────┤
│  What are you looking for?                      │
│                                                 │
│  Salary floor          Salary target            │
│  [£ 50000    ]         [£ 75000    ]            │
│                                                 │
│  Currency                                       │
│  [GBP ▾]                                        │
│                                                 │
│  ─────────────────────────────────────────────  │
│                                                 │
│  [← Back]                              [Next →] │
└─────────────────────────────────────────────────┘
```

- Progress indicator (stage N of 10)
- Back button (revise previous answers)
- Keyboard-first (Tab through fields, Enter submits)
- Inline validation (Zod)
- Persist to localStorage on each step (resume if browser closed)

---

## 9. Frontend stack and structure

### Dependencies

```json
{
  "dependencies": {
    "react": "^18.3.0",
    "react-dom": "^18.3.0",
    "react-router-dom": "^6.22.0",
    "@tanstack/react-query": "^5.0.0",
    "react-hook-form": "^7.50.0",
    "@hookform/resolvers": "^3.3.4",
    "zod": "^3.22.4",
    "tailwindcss": "^3.4.0",
    "class-variance-authority": "^0.7.0",
    "clsx": "^2.1.0",
    "lucide-react": "^0.383.0"
  },
  "devDependencies": {
    "@vitejs/plugin-react": "^4.2.0",
    "typescript": "^5.3.0",
    "vite": "^5.1.0"
  }
}
```

Note: shadcn/ui components are copied into `src/components/ui/`, not installed as a package.

### `vite.config.ts` proxy

```typescript
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        // SSE requires this:
        configure: (proxy) => {
          proxy.on('proxyReq', (proxyReq) => {
            proxyReq.setHeader('Cache-Control', 'no-cache');
          });
        },
      },
    },
  },
});
```

### State management philosophy

- **Server state:** TanStack Query. Cache invalidation on mutations.
- **Form state:** React Hook Form + Zod schemas.
- **URL state:** React Router. Session ID lives in the URL.
- **Local state:** `useState`.
- **Global client state:** Zustand **only if needed** — probably not.

### SSE wrapper pattern

```typescript
// frontend/src/lib/sse.ts
export function useSSE<T>(url: string, onEvent: (event: T) => void) {
  useEffect(() => {
    const source = new EventSource(url);
    source.onmessage = (e) => onEvent(JSON.parse(e.data));
    source.onerror = () => source.close();
    return () => source.close();
  }, [url]);
}
```

---

## 10. Demo video script

Target length: 90 seconds. Three acts.

### Act 1 — The pitch (0-15s)

Text overlay: *"Trajectory — UK job search, verified in 12 seconds."*

Show forwarding a job URL from a WhatsApp-style mobile chat. Cut to the web dashboard.

### Act 2 — Phase 1 live stream (15-45s)

Paste the URL. Hit Check.

Agents tick through in real-time on screen:
- ✓ Role parser
- ✓ Company resolver
- ✓ SOC guess
- ✓ Salary threshold
- ✓ Sponsor register
- ✓ Ghost detector
- ✓ Content shield

Verdict card slides in: **GO** · Senior Data Scientist · AstraZeneca · £75k · Sponsor confirmed · SOC threshold cleared.

### Act 3 — Full prep (45-90s)

Click "Full prep". All four generators fire in parallel, shown as four columns filling in:

- CV generated (file link)
- Cover letter drafted (file link)
- Interview questions produced (file link)
- Salary strategy drafted (file link)

Brief hover to show voice-matched writing style.

Cut to Telegram on phone: same verdict appears when you forward the URL there. Caption: *"Also runs on Telegram."*

End card: *"Trajectory — [github.com/kene/trajectory]"*

---

## 11. Portfolio narrative

### For hackathon submission

> **Trajectory** is a UK job-search assistant built as a dual-surface application: a React web app for deep work (onboarding, session review, pack generation) and a Telegram bot for on-the-go submissions. Both surfaces share a single FastAPI orchestrator, a 16-agent Phase 1 verdict pipeline, and a SQLite + FAISS state store. A transport-agnostic `ProgressEmitter` protocol enables streaming Phase 1 progress over Telegram message edits or Server-Sent Events without duplicating business logic.

### For CV

**Trajectory** — Dual-surface job-search assistant (web + Telegram)
- Built a 16-agent LLM orchestration pipeline producing sponsor-verified job verdicts in ~12s
- Designed transport-agnostic `ProgressEmitter` protocol, enabling both Telegram message-edit streaming and Server-Sent Events without code duplication
- Implemented anti-hallucination validators (citation validator against JSON-LD source, fuzzy-match sponsor register lookup) with graceful degradation on component failure
- Parallel pack generation (CV, cover letter, interview questions, salary strategy) fanning out via `asyncio.gather` behind a single SSE stream
- Stack: FastAPI, Anthropic (Opus 4.7 + Sonnet 4.6), Pydantic, SQLite + FAISS, React/Vite, python-telegram-bot

### Interview talking points

1. **Why dual-surface?** Different use contexts — Telegram for mobile quick-submit, web for desk-side review and editing. Same orchestrator, two transports.
2. **The `ProgressEmitter` abstraction.** Tell the story of walking into the codebase, seeing `PhaseOneProgressStreamer` tightly coupled to Telegram, and extracting a Protocol. ~100 lines added, unlocked the whole web surface.
3. **Cost control.** LLM cost log per call, retry-aware citation validation, structured outputs via Pydantic + Instructor to avoid reparse loops.
4. **Known limitations.** FAISS index caching per process is stale across restart. Acceptable for single-user; for multi-user, would move to pgvector.
5. **What you'd build next.** Multi-user auth, Slack as a third surface (~1 day given the Protocol), scheduled job digests.

---

## 12. Effort estimate

| Wave | Days | Owner |
|---|---|---|
| 0. Prep + bug fixes | 0.5 | You |
| 1. ProgressEmitter abstraction | 1 | You (with AI) |
| 2. FastAPI skeleton | 1 | You |
| 3. Read-only routes | 1 | You |
| 4. Forward job SSE | 2 | You |
| 5. Pack generators + full_prep SSE | 1.5 | You |
| 6. Frontend scaffold | 1 | You |
| 7. Dashboard (demo centrepiece) | 2 | You |
| 8. Session detail + pack UI | 1.5 | You |
| 9. Onboarding wizard | 3 | You |
| 10. Telegram redirect | 0.25 | You |
| 11. Test both surfaces | 0.75 | You |
| 12. Demo video + polish | 1 | You |
| **Total** | **~16.5 days** | |

### Part-time pace

At 2 hours/day (evenings after shifts), that's ~33 calendar days, or roughly 5 weeks.

At 4 hours/day on weekends (8 hours/weekend), that's ~16 weekends.

Hackathon deadline constraint: compress to 10 days by dropping Wave 9 (use current Telegram-style free-text onboarding on web, then rebuild post-hackathon).

---

## 13. Architecture Decision Records

Write these into `PROCESS.md` as the work progresses.

### ADR-001: Dual-surface architecture with web-primary

**Status:** Accepted
**Context:** Single-user portfolio demo requiring both mobile and desktop surfaces.
**Decision:** Web is primary (full functionality). Telegram is a cameo (forward_job + verdict + full_prep only). Onboarding and profile management live on web only.
**Consequences:**
- (+) Simpler state model (no cross-surface onboarding sync)
- (+) Demo video can focus on web for polish
- (+) Telegram remains useful as mobile quick-submit
- (-) Users must onboard on web before using Telegram
- (-) Future full-parity migration would require onboarding SQLite persistence
**Alternatives considered:** Full parity (+4 days), web-only (loses mobile narrative), Telegram-only (loses portfolio visual).

### ADR-002: `ProgressEmitter` protocol for transport-agnostic progress

**Status:** Accepted
**Context:** Orchestrator previously coupled to Telegram via `PhaseOneProgressStreamer(bot, chat_id, message_id, ...)`. Web surface needs same progress events delivered via SSE.
**Decision:** Introduce `ProgressEmitter` Protocol with `emit(event: dict)` and `close()`. Orchestrator takes `emitter: ProgressEmitter = NoOpEmitter()` as parameter. Two implementations: `TelegramEmitter` (wraps existing streamer), `SSEEmitter` (pushes to `asyncio.Queue`).
**Consequences:**
- (+) Orchestrator has zero transport knowledge
- (+) New surfaces (Slack, Discord, CLI) require only a new emitter (~50 lines)
- (+) Testing simplified via `NoOpEmitter`
- (-) One layer of indirection between agent completion and user-visible progress
**Alternatives considered:** Pass bot/chat_id directly to SSE handler (fails because SSE has no such concept). Emit structured events to stdout and pipe to transport (over-engineered).

### ADR-003: Onboarding state ephemeral, not synced cross-surface

**Status:** Accepted
**Context:** Current onboarding state is in-memory dict in bot process. Web would need separate state. Full sync requires SQLite persistence + race handling.
**Decision:** Onboarding is web-only. Telegram users without a completed profile are redirected to web. State lives in browser localStorage for resume-on-refresh.
**Consequences:**
- (+) No cross-process state coordination needed
- (+) No SQLite migration for onboarding
- (+) Resume-on-refresh is free via localStorage
- (-) If a user somehow starts on Telegram, they can't continue on web (but the UX prevents this via redirect)
- (-) Multi-user future will need a proper backend-persisted state
**Alternatives considered:** SQLite `onboarding_sessions` table (rejected — +0.5 days, unnecessary for single-user). Telegram-side onboarding (rejected — duplicates flow, worst UX of both surfaces).

---

## 14. Deferred items

Explicit list of things we are **not** doing now. Revisit post-hackathon.

| Item | Why deferred | Effort to add later |
|---|---|---|
| Cross-surface in-flight session visibility | Nobody notices in demo | +1 day |
| FAISS index live reload | Single-user demo accepts staleness | +1 day (file lock) or +3 days (pgvector) |
| Multi-user auth | No users yet | +3-5 days |
| Profile editing on Telegram | Rare, web sufficient | +0.5 days |
| Session browsing on Telegram | Chat log is the history | +1 day |
| Cross-surface notifications (pack complete) | Scope creep | +1 day |
| Mobile-responsive web | Desktop-first for demo | +1 day |
| OAuth (Google / GitHub) login | No users | +1 day |
| Rate limiting on web API | Single-user localhost | +0.5 days |
| Prometheus metrics | Logging sufficient for now | +0.5 days |
| Dockerfile for full stack | Local dev only | +0.5 days |
| Staging deployment (Fly / Railway) | Demo runs locally | +1 day |

---

## Appendix: critical code snippets

### `src/trajectory/progress/emitter.py`

```python
from typing import Protocol

class ProgressEmitter(Protocol):
    """Any transport that wants Phase 1 progress events."""
    async def emit(self, event: dict) -> None: ...
    async def close(self) -> None: ...


class NoOpEmitter:
    """Default when no surface is attached (CLI, tests)."""
    async def emit(self, event: dict) -> None:
        pass
    async def close(self) -> None:
        pass
```

### `src/trajectory/progress/sse_emitter.py`

```python
import asyncio

class SSEEmitter:
    def __init__(self, queue: asyncio.Queue):
        self._queue = queue
        self._closed = False

    async def emit(self, event: dict) -> None:
        if not self._closed:
            await self._queue.put(event)

    async def close(self) -> None:
        if not self._closed:
            self._closed = True
            await self._queue.put({"type": "done"})
```

### `src/trajectory/api/sse.py`

```python
import asyncio
import json
from typing import AsyncIterator
from sse_starlette.sse import EventSourceResponse

async def event_stream(queue: asyncio.Queue) -> AsyncIterator[dict]:
    while True:
        event = await queue.get()
        yield {"data": json.dumps(event)}
        if event.get("type") in ("done", "error"):
            break
```

### `src/trajectory/api/routes/files.py`

```python
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

router = APIRouter()

@router.get("/files/{session_id}/{filename}")
async def get_file(
    session_id: str,
    filename: str,
    user_id: str = Depends(get_current_user_id),
    storage: Storage = Depends(get_storage),
):
    session = await storage.get_session(session_id)
    if not session or session.user_id != user_id:
        raise HTTPException(404)

    # Prevent path traversal
    safe_name = Path(filename).name
    path = settings.generated_dir / session_id / safe_name
    if not path.exists() or not path.is_file():
        raise HTTPException(404)

    return FileResponse(path, filename=safe_name)
```

### `orchestrator.py` refactor (diff illustration)

```python
# BEFORE
async def handle_forward_job(
    job_url: str, user: UserProfile, session: Session, storage: Storage,
    bot: Bot, chat_id: int, message_id: int,   # ← Telegram-specific
):
    streamer = PhaseOneProgressStreamer(bot, chat_id, message_id, PHASE_1_AGENTS)
    ...
    await streamer.mark_complete("role_parser")

# AFTER
async def handle_forward_job(
    job_url: str, user: UserProfile, session: Session, storage: Storage,
    emitter: ProgressEmitter = NoOpEmitter(),   # ← transport-agnostic
):
    await emitter.emit({"type": "agent_started", "agent": "role_parser"})
    ...
    await emitter.emit({"type": "agent_complete", "agent": "role_parser"})
```

---

**End of plan.**
