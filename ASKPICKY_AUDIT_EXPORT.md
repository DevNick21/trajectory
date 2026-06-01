# AskPicky Audit Export

*Last updated 2026-06-01.*

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
  - restored compatibility model/provider settings still referenced by
    verdict code, tests, and smoke scripts
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

---

## Still Needed

- Full design pass:
  - Assist becomes an application cockpit.
  - Memory becomes an evidence vault.
  - UI should feel closer to Linear/Superhuman/1Password/Grammarly than a
    chatbot dashboard.
- Chrome MV3 companion:
  - content script
  - side panel/overlay
  - auth bridge to hosted AskPicky
  - ATS adapters
  - generic DOM fallback
  - manual highlight/send fallback
- Electron V3 companion after Chrome/web retention is proven.
- Hosted commercial data layer:
  - outcome reporting
  - aggregate employer benchmarks
  - response-rate intelligence
  - ghost-frequency trends
  - hosted-only managed sync
- Full schema codegen is still needed. The OpenAPI smoke is a drift guard, not
  a replacement for generated TypeScript types.
- Auth/multi-tenant identity is still a future boundary. Storage is keyed by
  `user_id`, but the current API dependency still uses `settings.demo_user_id`.
- URL safety / SSRF controls need to be added before hosted users can submit
  arbitrary job URLs.
- Scheduled privacy cleanup is still needed; the purge route exists, but
  hosted retention should not depend on a manual call.
- Per-user quota and cost attribution are still needed; current budgets are
  global and rate limiting is process-local.

---

## Verification Commands

```bash
python -m compileall src\askpicky scripts\smoke_tests
python -m scripts.smoke_tests.run_all --only application_memory,api_assist,api_contract --fail-fast
python -m scripts.smoke_tests.run_all --only application_answer_shaper,memory_extractor --fail-fast
python -m pytest tests/test_content_shield.py
npm run lint
git diff --check
python scripts/audit_prompt.py application_answer_shaper
python scripts/audit_prompt.py memory_extractor
python -m pytest tests\test_api_health.py tests\test_api_queue.py tests\test_api_pack.py tests\test_verdict_fallback.py tests\test_api_read_routes.py -q
```
