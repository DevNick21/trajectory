# HANDOFF.md — AskPicky

> Read-in for a fresh Anthropic agent picking up this repo.
> Time-box this doc to ~10 minutes. Then read [CLAUDE.md](./CLAUDE.md) before touching code.

*Authored 2026-05-22 20:50 BST. Last updated 2026-05-22 23:30 BST · HEAD `60add03` (Close gap #7: explicit per-pillar signal weights as verdict priors). All 9 architecture gaps from the 2026-05-17 review are now closed at the data layer + verdict prompt level; see §4. Working tree status in §9.*

---

## 1. What this is

AskPicky (Python package: `askpicky`; was `trajectory` until 2026-05-22) is a UK-first, visa-aware, agent-powered job search assistant. The product promise has three parts:

1. **Verify before applying.** Forward a job URL → 9 Phase 1 sub-agents run in parallel against the JD, the company, and live UK government data → a cited GO/NO_GO verdict with every load-bearing claim grounded by Anthropic's Citations API.
2. **Visa-aware out of the box.** Sponsor Register (with Splink fuzzy match), SOC threshold + new-entrant rule, Appendix Skilled Occupations eligibility, Companies House officers/charges/PSC, The Gazette insolvency notices. The visa wedge is the differentiator, not a bolt-on.
3. **Learn from outcomes.** One-tap reporting in Telegram → aggregated employer-behaviour database → premium benchmarks. Code is open (AGPL-3.0 + CLA); the data network is the closed moat.

**It is not** an auto-apply tool, an ATS, a trust badge, an AI-content detector, or a LangChain/LangGraph/RapidAPI/Firecrawl wrapper. Raw Anthropic SDK only.

Canonical docs in priority order:
- [ASKPICKY.md](./ASKPICKY.md) — product definition, free/premium split, roadmap. Supersedes everything else on contradiction.
- [CLAUDE.md](./CLAUDE.md) — the 10 hard architectural rules + adapter dispatch.
- [AGENTS.md](./AGENTS.md) — agent prompt + adapter inventory (24 agents).
- [PROCESS.md](./PROCESS.md) — decision log (50+ entries).
- [docs/architecture_review_2026_05_17.md](./docs/architecture_review_2026_05_17.md) — 9 known architectural gaps. Still open.

---

## 2. The architecture in one screen

**Two surfaces, one orchestrator.** Telegram (mobile capture) + Web (Vite/React/TanStack Query, desktop deep-work) → one FastAPI orchestrator → one 9-agent Phase 1 pipeline → SQLite + FAISS state. `ProgressEmitter` protocol streams progress over both surfaces without duplicating business logic.

**The 10 hard rules** (CLAUDE.md is canonical; here so you know they exist):
1. No invented data — every claim has a resolvable citation, enforced by validators.
2. User-type branching in the verdict (`uk_resident` vs `visa_holder` get different hard-blocker sets).
3. WritingStyleProfile injected into every Phase 4 generator.
4. Phase 1 fan-out + `full_prep` Phase 4 generators run in parallel (`asyncio.gather`).
5. Structured Pydantic output everywhere — no free-form prose from sub-agents.
6. On-demand, not on-the-fly — `forward_job` stops at verdict; packs are separate intents.
7. Cheapest model that meets the bar — Opus only where judgement is the product.
8. Cost discipline via `llm.py`'s tracker + `priority` refusal at < $20.
9. Telegram-native affordances — streaming Phase 1, file generation for CV/cover letter.
10. Content Shield is a **precondition** for every agent invocation on untrusted content.

**Four adapter shapes in `src/askpicky/llm.py`**, pick one per agent:
| Adapter | When |
|---|---|
| `call_structured` | Schema-dense outputs |
| `call_with_citations` | Source-grounded text |
| `call_with_tools` | Web Search / Web Fetch / Code Execution |
| `call_in_session` | Managed Agents long-running sandbox |

**Model ladder** (CLAUDE.md Rule 7 is canonical):
- **Opus 4.7 `xhigh`** — verdict, cv_tailor, cover_letter, salary_strategist, offer_analyst, prompt_auditor. The 6 calls where the *position itself* is the product.
- **Sonnet 4.6** — style_extractor, red_flags, star_polisher, draft_reply, company_scraper_summariser, onboarding_parser, content_shield_tier2.
- **Haiku 4.5** — intent_router (fallback), cv_parser, interview_questions, jd_extractor, self_audit, entity_judge.
- **Deterministic (no LLM)** — intent_router tier-0, ghost_job_jd_scorer, cv_parser tier-0, entity_resolution footer/local-CH-index, **The Gazette parser**.

---

## 3. What just landed (the 2026-05-22 overhaul)

This is the most important context for picking up. The repo went through two simultaneous rounds in May 2026:

### A. Rebrand + cuts (commits `ca61263` through `9d0594b`)
- **Trajectory → AskPicky** — package rename, no backward compat. Python imports are `from askpicky.X import Y`. Test mode env var: `ASKPICKY_TEST_MODE=1`.
- **AGPL-3.0** — relicensed from MIT (`9cac865`).
- **Cuts**: LaTeX CV path, multi-provider CV tailor, legacy jobspy reviews, verdict ensemble + deep-research flags (deep-research survives as the spec for the premium "Real-time hiring intent verification" feature), several dead config flags. See CLAUDE.md "Cuts landed in the 2026-05-22 overhaul" for the full list.

### B. Distress signals + agent consolidation (commits `ea35fcf` and `9760a0e`)
- **Salary out of Phase 1.** Most UK JDs don't post a band so the comparison fired on absent data. Salary lives now as the on-demand `salary_strategist`; not a verdict hard blocker.
- **The Gazette in.** New `gazette_check.py` (deterministic) plus a new `GAZETTE_INSOLVENCY_NOTICE` hard-blocker type. Wind-up petitions (2450), administrator appointments (2410), winding-up orders (2440/2441) are the strongest pre-failure signals available without a paid feed.
- **Companies House officers/charges/PSC** — added `recent_director_resignations_6mo`, `recent_charges_6mo`, `psc_changes_6mo` to `CompaniesHouseSnapshot`. Surfaced as **stretch concerns** (`DIRECTOR_CHURN`, `CHARGES_FLURRY`, `PSC_CHURN`) rather than hard blockers, plus a **compound distress heuristic**: when 2+ of those fire together, drop verdict confidence by ≥20 points even if formal CH status is still "Active".
- **Entity-resolution sanity** — when `company_identity.confidence < 0.5` AND CH signals look extreme, surface as `CONTENT_INTEGRITY_CONCERN` rather than asserting confident NO_GO. The resolver may have anchored on the wrong entity.
- **Agent consolidation** — 4 LLM calls per typical session removed:
  - `intent_router` got a deterministic tier-0 (URL + keyword rules cover ~80% of messages; Haiku fallback for the rest).
  - `ghost_job_jd_scorer` is now pure regex (5-dim scoring).
  - `question_designer` + `likely_questions` → merged into `interview_questions.design` / `.predict`.
  - `cv_parser` + `career_narrator` → merged into one Haiku call.
  - ~10 agents downgraded Sonnet → Haiku without smoke regressions.

### C. Frontend cv_enrich wiring + verdict prompt update (commit `d03b6fd`)
- Wizard CV upload now does tier-0 (regex extract, ~50ms, $0) → renders → fires `cv_enrich` in the background to populate bullets/education/projects/narrative via Haiku. User keeps editing visible fields while the slower bits land.
- `prompts/verdict.md` rewritten to reflect the new signal set (Gazette as hard blocker, director churn / charges / PSC as stretch concerns, salary blockers removed, entity-resolution sanity rule, AskPicky/Picky branding).

### D. Gazette API verification (this session, uncommitted)
- The deferred verification item from earlier discussions. Live-tested 2026-05-22 against thegazette.co.uk.
- **The non-obvious bits** — endpoint is `/all-notices/notice/data.json` (with `service=insolvency` filter); envelope key is `entry` *singular*; `content` is escaped HTML, not pre-stripped text; there is NO `notice-code` field at entry level (it's a phrase inside the body); bundled supplements list 200+ companies per entry.
- Parser at [src/askpicky/sub_agents/gazette_check.py](src/askpicky/sub_agents/gazette_check.py) was rewritten with CRN-anchored matching, phrase-pattern classification, 730-day recency cutoff, and a `HARD_BLOCKER_CODES = {2410, 2440, 2441, 2450, 2451}` scope. Generic insolvency code `2400` surfaces as informational only — bundled-supplement noise would otherwise cause false NO_GOs on active companies that share corporate groups with defunct siblings.
- Locked in by new smoke test [scripts/smoke_tests/gazette_check.py](scripts/smoke_tests/gazette_check.py); registered in `run_all.py` under `phase1`, cheap-tier. Optional live probe behind `SMOKE_GAZETTE_LIVE=1`.
- Memory note recorded at `~/.claude/projects/.../memory/gazette_api_shape.md`.

---

## 4. Known architectural gaps — status as of 2026-05-22

Pulled from [docs/architecture_review_2026_05_17.md](./docs/architecture_review_2026_05_17.md). **All 9 gaps closed (data layer + verdict prompt) as of commits `210dd8d` → `60add03`.** What's left is the optional learning loop on top of gap #7.

1. **Hard gates were binary** — *closed.* `match_confidence: float` + `match_path: MatchPath` (`EXACT_NAME / FUZZY_NAME / CRN_VERIFIED / NO_MATCH / LOOKS_LIKE_SUB_ENTITY`) on `CompaniesHouseSnapshot`, `SponsorStatus`, `SocCheckResult` in [schemas.py](src/askpicky/schemas.py). `SponsorStatus.status` literal gained `AMBIGUOUS`. `StretchConcernType` gained `SPONSOR_AMBIGUITY` + `AGENCY_POSTING`. Verdict prompt's AMBIGUITY TIER OVERRIDE demotes NOT_LISTED → stretch concern when match_confidence < 0.95, alternative_matches non-empty, register_age_days >= 7, status == AMBIGUOUS, or match_path ∈ {FUZZY_NAME, NO_MATCH, LOOKS_LIKE_SUB_ENTITY}; same treatment for soc_check.match_confidence < 0.7.
2. **Entity resolution ignored CRN** — *closed.* Resolver-layer hardening landed in `9d0bb4b` / `ce1eaab` (multi-token blocking, dissolved-shell penalty, footer-CRN scrape, LLM-judge fallback). Parent/subsidiary walk added in `d9576dd`: `_extract_corporate_parents` pulls corporate PSCs from CH (filtering individuals + ceased PSCs + dedup); `_walk_parent_sponsors` in [orchestrator.py](src/askpicky/orchestrator.py) re-runs sponsor lookup against each parent when sponsor.status == NOT_LISTED, demoting to AMBIGUOUS + match_path=LOOKS_LIKE_SUB_ENTITY when any parent matches. Verdict prompt has a "Parent-walk specifically" paragraph.
3. **No outcome → verdict calibration** — *closed.* [orchestrator.py](src/askpicky/orchestrator.py) recalls `application_outcome` memory and threads `prior_outcomes_text` into [verdict.py](src/askpicky/sub_agents/verdict.py). Verdict prompt's OUTCOME CALIBRATION section uses prior outcomes to adjust confidence — never decision ("a dissolved company is still a NO_GO even if the user has ignored 10 of them").
4. **Cost-of-verdict mismatched** — *closed.* [triage.py](src/askpicky/sub_agents/triage.py) (Haiku, ~$0.02) classifies every forward as SERIOUS/EXPLORATORY/DEFINITE_PASS before Phase 1; DEFINITE_PASS short-circuits the $1-2 pipeline. Gated by `enable_triage_before_verdict` (default on).
5. **Recruitment-agency vs hiring-entity confusion** — *closed.* New [agency_detection.py](src/askpicky/agency_detection.py) (pure regex, ~0.5ms). Strong/weak phrase ladder + known agency company-name fragments. `ExtractedJobDescription` gained `is_agency_post`, `agency_client_name`, `agency_signals`. `_extract_jd` overlays them post-LLM. Verdict prompt has an AGENCY POSTING TIER OVERRIDE that demotes NOT_LISTED → AGENCY_POSTING stretch concern when the JD was an agency post.
6. **No competitive ranking** — *closed.* New `compare_verdicts` intent + `handle_compare_verdicts` in orchestrator. Deterministic composite: 60% verdict confidence + 25% freshness (linear decay over 28 days) + 15% signal density. NO_GOs excluded; per-row rationale always names the dominant driver. New `CompareVerdictsOutput` / `RankedSession` schemas.
7. **Phase 1 signal weighting was implicit** — *closed (static priors).* New [signal_weights.py](src/askpicky/signal_weights.py) returns per-(user_type, soc_code) weight dicts summing to 1.0. Verdict's `_build_user_input` includes `signal_weights` in the payload. Verdict prompt's SIGNAL WEIGHTS section instructs: use as priors for confidence calibration (3x effect on a 0.28-weight pillar vs 0.08-weight), hard-blocker rules still fire deterministically, weights calibrate the *confidence number*, not the decision. **Optional next step:** outcome-driven re-weighting (replace static dict with storage lookup keyed by the same tuple).
8. **No conversational refinement** — *closed.* New `challenge_verdict` intent + `handle_challenge_verdict` orchestrator handler. Reuses the same research bundle, re-runs the verdict with `user_challenge_text` threaded through. Verdict prompt's CHALLENGE HANDLING section spells out two valid moves (accept-and-rerank, hold-the-position); never silently change the decision; never sycophantically lower confidence on a clean hard blocker.
9. **Data-freshness was binary** — *closed.* New `age_days()` in [data_freshness.py](src/askpicky/data_freshness.py). `register_age_days` on `SponsorStatus`; `data_age_days` on `SocCheckResult`. Verdict prompt's DATA-FRESHNESS GRADIENT section: ≥7 days for sponsor downgrades confidence; ≥90 days for SOC downgrades SALARY_BELOW_SOC_THRESHOLD; multiple stale sources compound. CH data is fresh-per-request so doesn't need an age field.

**Pattern across the close-out:** schemas + data layer + verdict prompt all landed as one unit per gap. Smokes cover the deterministic plumbing (`agency_detection`, `compare_and_challenge`, `parent_walk`, `signal_weights`, `gazette_check`) without requiring live LLM calls. The verdict prompt now reasons about provenance, freshness, outcomes, identity ambiguity, agency posts, parent-walks, and per-pillar priors — none of which were surfaces it had access to before May 2026.

**Process-safety side-note:** [storage.py](src/askpicky/storage.py) extracted FAISS + sentence-transformer plumbing into an `EmbeddingStore` class (instance-level locks, lazy init). Module-level globals retained as backward-compat aliases. Was a multi-process fragility called out in the architecture review.

**Bug found while closing the gaps:** the triage DEFINITE_PASS branch in orchestrator.py initially constructed `MotivationFitReport` and `GhostJobJDScore` with non-existent fields. Would have crashed any time triage fired. Fixed in `b56edad`.

---

## 5. What's next — the build queue

From ASKPICKY.md §10. **P0 must ship before any premium work begins.**

### P0 (close the gap to the new positioning)
1. **One-tap outcome reporting in Telegram** + Day-21 nudge. *No data network without this.*
2. Light verification of adversarial outcome reports.
3. Personal application tracker + follow-up reminders.
4. Tailored CV version management (saved per role).
5. Triage-before-verdict layer (architecture gap #4).
6. Visa eligibility check (front-page tool, no signup) — conversion driver.
7. Sponsor register search (front-page tool) — surfaces the visa wedge.
8. CV tailor consolidation — already largely done in the 2026-05-22 overhaul; finish cleanup.
9. Operational debt: doc drift, missing canonical docs, license drift, duplicate PROCESS entries.
10. ~~Trajectory → AskPicky rename~~ — done.

### P1 (first premium feature ships)
1. Live going-rates parser (gov.uk Appendix Skilled Occupations).
2. **Salary defensibility for visa roles** — Premium feature #1.
3. ~~CRN-based entity resolution + parent/subsidiary walk (gap #2).~~ — done in `d9576dd`.
4. Sponsor licence change alerts on saved roles.
5. **Real-time hiring intent verification** (promote `verdict_deep_research` managed session from flag to premium) — Premium feature #2.

### P2 (data network reaches ~1,000 contributors)
1. **Aggregated employer-behaviour benchmarks** — Premium feature #3.
2. Methodology transparency UI + "Insufficient data" honest UI.
3. ~~Outcome → verdict calibration loop (gap #3).~~ — done in `210dd8d`. Optional follow-up: outcome-driven re-weighting of [signal_weights.py](src/askpicky/signal_weights.py).
4. ~~`challenge_verdict` intent (gap #8).~~ — done in `b56edad`.

### P3 (late premium + quality)
1. **Application autopsy after rejection** — Premium feature #4.
2. Phase 1 signal weighting (learned, gap #7).
3. Continuous staleness gradient (gap #9).
4. Continuous background monitoring of saved roles.

### Deferred indefinitely
Real Batch API dispatch, daily Sponsor Register refresh, verdict ensemble (voice-incompatible), competitive ranking, AskPicky Interview sister product.

---

## 6. Where things live

```
src/askpicky/
├── api/                      FastAPI orchestrator + routes + schemas
├── bot/                      python-telegram-bot v21 handlers + adapters
├── sub_agents/               Phase 1 + Phase 4 generators (one file per agent)
├── managed/                  Managed Agents sessions (company_investigator,
│                             reviews_investigator, verdict_deep_research, ...)
├── memory/                   recorder + recall (SQLite-backed)
├── entity_resolution/        local CH index, judge, footer extractor
├── validators/               citations, banned_phrases, content_shield, pii
├── renderers/                python-docx + reportlab for CV/cover letter
├── progress/                 ProgressEmitter protocol (Telegram + SSE)
├── prompts/                  *.md system prompts (verdict.md is canonical)
├── voice/                    persona layer (thought_partner / value_architect
│                             / direct_operator) — see voice.py
├── schemas.py                ALL Pydantic models (~2000 lines, single source)
├── llm.py                    four-adapter dispatch + cost tracker
├── config.py                 Settings (env-driven; ASKPICKY_TEST_MODE=1 opts out)
├── agency_detection.py       Deterministic recruitment-agency post detector (gap #5)
├── signal_weights.py         Per-pillar verdict priors (gap #7)
└── data_freshness.py         age_days() + is_stale() for parquet sidecars (gap #9)

frontend/                     Vite + React 18 + TanStack Query + Tailwind
demo/                         Remotion v4 composition (5400 frames @ 30fps)
scripts/
├── smoke_tests/              ~50 smokes; --cheap tier must stay green
├── fetch_gov_data.py         Sponsor Register / ASHE / SOC / Appendix
└── audit_prompt.py           prompt_auditor entry point

data/
├── processed/                parquet — ch_companies, sponsor_register, ASHE
└── managed_agents.json       resource cache for Managed Agents
```

---

## 7. How to verify a change

```bash
# 35 cheap smokes, ~5 min, $0 — the regression net. Must stay green.
python -m scripts.smoke_tests.run_all --cheap

# Full live suite (~$5, ~10 min)
python -m scripts.smoke_tests.run_all
```

Each LLM-backed smoke honours `SMOKE_<NAME>_MOCK=1` for free iteration. Managed Agents paths gate behind their own env vars (`SMOKE_AGENTIC_CV=1`, `SMOKE_GAZETTE_LIVE=1`, etc.).

When adding an agent:
1. Pydantic I/O in `schemas.py` first.
2. Prompt in `prompts/<name>.md`.
3. Pick an adapter from the four-shape table; document in [AGENTS.md](./AGENTS.md).
4. Orchestrator wiring.
5. Smoke test in `scripts/smoke_tests/`, registered in `run_all.py`.

In that order. Skipping the smoke is a P0 bug.

---

## 8. Pitfalls / traps to know about

- **The Gazette returns bundled supplements** that list 200+ companies' CRNs per entry. Naive name-matching gives false positives for any active company in a corporate group with a defunct sibling. CRN-anchored matching + specific-phrase classification (HARD_BLOCKER_CODES) is load-bearing — don't loosen it.
- **`storage.save_session` is INSERT, `update_session` is UPDATE.** Calling `save_session` twice on the same session raises IntegrityError. The Job-stamping path in `handle_forward_job` learned this the hard way (PROCESS Entry 48).
- **`Windows + Playwright`** — set `WindowsProactorEventLoopPolicy` at module import (already in `api/app.py`). uvicorn `--reload` sometimes uses the Selector loop, which doesn't implement `subprocess_exec`.
- **Sonnet/Opus output validation** — Pydantic schemas with untyped `dict` fields aren't strict-compatible with OpenAI's structured outputs. Anthropic-only is the canonical path now (multi-provider was cut in the 2026-05-22 overhaul), so this is moot inside `askpicky` but worth knowing if you ever revisit.
- **Motion v12 strict types** in the frontend require `as const` on literal strings in variants (`type: "spring" as const`). Two-character fix; hostile error message.
- **Banned phrases enforced by self-audit.** Don't write "passionate", "leverage" (as verb), "deep dive", "hit the ground running", etc. into prompts or generators. Full list in CLAUDE.md. Self-audit also runs a **company-swap test** — any sentence where swapping the company name doesn't change the meaning is flagged.
- **Resolver false positives on shared brand names.** The loveholidays-class bug: dissolved-shell CRNs sharing a brand name with a trading entity used to be picked over the real one. Fixed via multi-token blocking + dissolved-shell penalty + footer-CRN scrape + LLM-judge fallback (`9d0594b`). If you touch `entity_resolution/`, smoke-verify against Wilko and Body Shop.
- **Voice personas are real and load-bearing.** `src/askpicky/voice.py` maps intent → persona; system prompts in `prompts/voice/` are composed onto the base prompt. Don't write tone instructions into individual agent prompts; use the persona layer.

---

## 9. Uncommitted work-in-progress (as of 2026-05-22)

The current working tree has the Gazette verification rewrite plus several frontend changes from a separate dashboard polish thread. The handoff target should decide whether to commit + push or leave for the next session.

```
Modified (not committed):
  frontend/index.html
  frontend/src/App.tsx
  frontend/src/components/Phase1Stream.tsx
  frontend/src/components/VerdictCard.tsx
  frontend/src/index.css
  frontend/src/pages/Dashboard.tsx
  frontend/tailwind.config.ts
  scripts/smoke_tests/run_all.py            (gazette_check registration)
  src/askpicky/sub_agents/gazette_check.py  (rewrite)

Untracked:
  frontend/src/components/PickyAvatar.tsx   (new Picky persona avatar)
  scripts/smoke_tests/gazette_check.py      (new cheap smoke)
```

The Gazette rewrite + smoke is a clean unit — safe to commit on its own. The frontend changes look like an in-progress visual pass (PickyAvatar component plus Tailwind/index.html/Dashboard touch-ups) — confirm with the user before bundling.

---

## 10. Memory and conventions for the next agent

- **Auto-memory directory:** `~/.claude/projects/c--Users-DELL-5420-OneDrive-Documents-Dev-trajectory/memory/`. Index at `MEMORY.md`. The Gazette API contract is recorded there (`gazette_api_shape.md`) — non-obvious traps are exactly what belongs in memory; don't re-investigate from scratch.
- **Decision discipline.** Every meaningful architectural decision lands in PROCESS.md as a numbered Entry. Read the last 5 entries before starting major work — context for the current direction.
- **When stuck:** read ASKPICKY.md §3 (the four-question test). A change failing 2+ of {strategic fit, voice fit, maintenance vs usage, differentiation} should cut, consolidate, or defer.
- **The architecture is stable. Do not redesign. Implement.** That line from CLAUDE.md is repeated because it's load-bearing. The interesting work is in the gaps section (§4) and the build queue (§5), not in restructuring what's already shipped.
