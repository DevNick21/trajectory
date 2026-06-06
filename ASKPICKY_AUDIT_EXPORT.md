# AskPicky Public Audit Export

This tracked export records public-safe product and engineering status only.
Managed-service implementation details, commercial rollout notes,
infrastructure-specific plans, packaging strategy, deployment notes, and
managed-service security notes stay outside tracked public files.

---

## Done

- The web app remains the source of truth for the public workflow.
- Onboarding finalise is deterministic:
  - structured profile save
  - deterministic career-entry writes
  - optional CV import remains separate from profile save
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

## Public Hardening Summary

### Pipeline and onboarding

- [ASKPICKY.md](./ASKPICKY.md) covers the public product map.
- Progressive onboarding, forward-job, assist, local storage modes, privacy
  controls, and public test gates are represented in tracked implementation
  docs and smoke tests.
- `/api/onboarding/finalise` performs deterministic profile and career-entry
  writes so the user-facing save step stays fast and inspectable.
- Generated OpenAPI/TypeScript contracts match the onboarding payload.
- Voice guidance comes from explicit persona, approved memory, and assist-loop
  feedback.

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

### Public security and reliability hardening

- Added route identity and ownership checks for multi-user deployments.
- Added retention purge paths and privacy audit metadata for sensitive
  operations.
- Added SSRF-safe URL validation before external fetch paths.
- Added OpenAPI export plus generated frontend contract view.
- Added extension fixture tests and manifest permission checks.
- Added static frontend accessibility checks for unlabeled icon-only buttons.
- Added browser-level accessibility smoke coverage over the built frontend.
- Added schema-drift enforcement for generated OpenAPI/types.

Implementation-specific deployment details are intentionally omitted here.

---

## Still Needed

- CV import UX:
  - show progress and extracted fields clearly
  - allow skip/retry without blocking onboarding finalise
  - move richer profile enrichment into a background memory job
- Forward-job reliability:
  - make JD extraction confidence visible when JSON-LD/text is thin
  - expand tests for broken/dynamic/blocked job pages
  - keep company investigation advisory and non-fatal
- Company investigation:
  - explicit source-status model for missing/stale/low-confidence company pages
  - bounded page list per company
  - fallback budget and failure messaging in the UI
- Sponsor Register:
  - stronger alias/domain/CRN resolution
  - clearer ambiguity states for visa users
  - fixture coverage for recruitment agencies, subsidiaries, rebrands, and
    similarly named sponsors
- Production-like testing:
  - tenant-isolation release gate where multi-user storage is used
  - one manually observed live forward-job run before release
  - no claim that local storage tests prove deployment-level isolation
- Redundant-code cleanup:
  - align remaining generator signatures around memory/persona inputs
    directly
  - keep provider/model references scoped to current tier routing
  - inventory default-off feature flags and unused agents before new surface work
- Full design pass:
  - Assist becomes an application cockpit.
  - Memory becomes an evidence vault.
  - UI should feel closer to Linear/Superhuman/1Password/Grammarly than a
    chatbot dashboard.
- Extension:
  - fixture coverage for more field/page variants
  - generic DOM fallback hardening
  - browser-level integration tests for the side-panel flow
- Managed-service roadmap details are deliberately not tracked
  in this file.

---

## Verification Commands

```bash
python -m compileall src\askpicky scripts\smoke_tests
python -m scripts.smoke_tests.run_all --only api_onboarding,onboarding_journey_uk,onboarding_journey_visa --fail-fast
python -m scripts.smoke_tests.run_all --only application_memory,api_assist,api_contract --fail-fast
python -m scripts.smoke_tests.run_all --only application_answer_shaper,memory_extractor --fail-fast
python -m pytest tests/test_content_shield.py tests/test_url_safety.py
npm run api:contract
npm run lint
python scripts/check_frontend_accessibility.py
npm run --prefix frontend build
npm run --prefix extension test
git diff --check
```
