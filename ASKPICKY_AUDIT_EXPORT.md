# AskPicky Audit Export

*Last updated 2026-06-02.*

This is the working export of what is done, what was hardened in this pass, and
what remains next.

---

## Done

- Hosted web app remains the source of truth for AskPicky v1.
- Application assist API exists:
  - `/api/assist/start`
  - `/api/assist/suggest-memory`
  - `/api/assist/critique-draft`
  - `/api/assist/polish`
  - `/api/assist/approve`
- Private evidence graph exists:
  - `ApplicationAssistSession`
  - `AnswerAttempt`
  - `ExperienceAtom`
  - `StoryFrame`
  - `MemoryEdge`
  - `AdviceSnippet`
- Memory Inbox exists with review states and private/sensitive visibility.
- `application_answer_shaper` and `memory_extractor` are registered agents with
  prompts, schemas, tier routing, content-shield registration, audit registry,
  and smoke tests.
- Frontend pages exist for application assist and memory review.

---

## Hardened In This Pass

### Application assist hardening

- Assist UI now starts an assist session first and carries the session id
  through suggest, critique, polish, and approve.
- Private-save is the default. Attempts and extracted memories inherit private
  visibility unless the session opts out.
- Private recall is explicit and defaults off in the UI.
- Save indicators now show private/pending/not-saved state through critique,
  polish, and approve.
- Memory controls now include edit, export, raw-retention purge, soft delete,
  hard delete, and backend merge support.
- Raw draft/transcript purge clears expired raw content while retaining
  answer-attempt metadata.
- OpenAPI smoke coverage checks the assist/memory route contract to reduce
  backend/frontend drift.
- Prompt auditor CLI now works on Windows UTF-8 output.
- Live prompt audits were run and high-severity findings were fixed:
  - `application_answer_shaper`: STRONG, 0 HIGH.
  - `memory_extractor`: STRONG, 0 HIGH.

### 16-lens audit-prompt pass

- Every prompt in `docs/audit-prompts/` was applied against the current repo.
- Full export is in
  `docs/AUDIT_PROMPT_RUN_2026_06_01.md`.
- Fixed config drift that could crash rate-limited routes:
  - added `Settings.enforce_rate_limit`
  - added `Settings.enable_batch_queue_runner`
  - removed legacy model/provider aliases and updated verdict code, tests,
    and smoke scripts to tier-based routing
- Added V2 hosted security foundation:
  - Supabase bearer-auth dependency for hosted mode
  - `SUPABASE_DATABASE_URL` config
  - Supabase Postgres/pgvector migration contract with RLS policies
  - hosted quota ledger and route-level assist quotas
  - protected internal purge and quota reconciliation endpoints
  - scheduled raw-retention purge with privacy audit events
  - SSRF-safe URL validation before httpx, Playwright, and Firecrawl
  - OpenAPI export plus generated frontend contract view
  - Chrome MV3 companion scaffold with manual highlight/send flow
- Added FastAPI security headers and equivalent nginx headers:
  - `Content-Security-Policy`
  - `Permissions-Policy`
  - `Referrer-Policy`
  - `X-Content-Type-Options`
  - `X-Frame-Options`
- Restricted CORS request headers from wildcard to explicit API headers.
- Added `/api/version` for frontend/API compatibility checks.
- Hardened `.dockerignore` so `.env.*`, SQLite/DB, and FAISS artifacts do not
  enter Docker build context.
- Added regression tests for `/api/version` and API security headers.
- Added Chrome companion pairing bridge:
  - `/api/extension/pairing-token`
  - `/api/extension/exchange`
  - hosted `/extension/connect` page outside the workspace and onboarding gate
  - extension external-message completion from the hosted connect page
  - one-time hashed pairing tokens with audit events
- Added Chrome detector fixture tests and manifest permission checks.
- Hardened the Chrome side-panel assist loop:
  - renders question type, what the question tests, missing evidence, memory
    angles, and save state
  - calls suggest-memory, critique, polish, and approve before copy/write-back
  - keeps private-memory recall off by default and covered by fixtures
- Added first-pass Greenhouse, Lever, and Workday detector adapters with
  fixture coverage before the generic DOM fallback.
- Added hosted quota coverage for `/api/chat`, `/api/queue`, and batch
  `/api/queue/process`; queue processing charges forward-job quota by the
  number of pending jobs.
- Added a dedicated Firecrawl fallback quota bucket and direct quota-denial
  test so anti-bot fallback spend is isolated from normal verdict quotas.
- Added CI schema-drift enforcement for generated OpenAPI/types and CI
  execution of the extension fixture tests.
- Added hosted Supabase route-isolation tests proving unauthenticated `401`
  and cross-user `404` behaviour across sessions, files, packs, queue,
  assist sessions, answer attempts, and Memory Inbox mutations.

---

## Still Needed

- Full design pass:
  - Assist becomes an application cockpit.
  - Memory becomes an evidence vault.
  - UI should feel closer to Linear/Superhuman/1Password/Grammarly than a
    chatbot dashboard.
- Chrome MV3 companion:
  - additional ATS adapters beyond Greenhouse/Lever/Workday
  - generic DOM fallback hardening
  - browser-level integration tests for the side-panel flow
- Electron V3 companion after Chrome/web retention is proven.
- Hosted commercial data layer:
  - outcome reporting
  - aggregate employer benchmarks
  - response-rate intelligence
  - ghost-frequency trends
  - hosted-only managed sync and consented aggregate outcomes
- Supabase Postgres/pgvector repository adapter is still needed; this pass adds
  the migration/RLS contract and fails closed when
  `STORAGE_BACKEND=supabase_postgres` is configured before the adapter lands.
- Storage-level tenant isolation still needs the runtime Postgres adapter test
  suite, but the hosted FastAPI route layer now has focused cross-user tests.
- CI now has secret scanning and schema drift enforcement; remaining CI work is
  broadening the hosted route-isolation and Playwright/axe suites.

---

## Verification Commands

```bash
python -m compileall src\askpicky scripts\smoke_tests
python -m scripts.smoke_tests.run_all --only application_memory,api_assist,api_contract --fail-fast
python -m scripts.smoke_tests.run_all --only application_answer_shaper,memory_extractor --fail-fast
python -m pytest tests/test_content_shield.py tests/test_auth_supabase.py tests/test_url_safety.py tests/test_supabase_foundation.py tests/test_hosted_route_isolation.py
npm run api:contract
npm run lint
git diff --check
python scripts/audit_prompt.py application_answer_shaper
python scripts/audit_prompt.py memory_extractor
python -m pytest tests\test_api_health.py tests\test_api_queue.py tests\test_api_pack.py tests\test_verdict_fallback.py tests\test_api_read_routes.py -q
python -m pytest tests\test_extension_pairing.py -q
python -m pytest tests\test_firecrawl_quota.py -q
npm run --prefix extension test
```
