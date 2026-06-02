# AskPicky — Product Definition (v1.0)

*Canonical source of truth. Supersedes CLAUDE.md, AGENTS.md, PROCESS.md, new_claude.md, trajec_notes.md where any contradiction exists.*

*Last updated 2026-06-02 — V2 security gate, hosted quotas, Chrome pairing bridge, and extension detector tests clarified.*

---

## 1. What AskPicky is

**AskPicky is a UK-first, visa-aware, agent-powered job search assistant. It verifies roles before you apply, learns from what happens after you apply, and helps you be picky in a market that rewards volume.**

The free tier delivers the core experience: research a role, get a cited verdict, apply with help, track outcomes, get the visa-aware signal nobody else gives.

The premium tier deepens it: continuous monitoring, salary defensibility against Home Office rules, pre-application benchmarks built from the network's outcomes, and post-rejection analysis.

**The data network — outcomes users report — is the moat.** Code is open (AGPL-3.0 + CLA). The aggregated employer-behaviour database is the closed, operationally-defended layer.

### Product delivery sequence

AskPicky ships in three surfaces, with the hosted web app as the source of
truth:

| Version | Surface | Role |
|---|---|---|
| V1 | Hosted web app | Core paid product: onboarding, verdicts, application assist, Memory Inbox, tracker, outcome reporting. |
| V2 | Chrome MV3 companion | In-browser coaching overlay for application forms. Detects active fields/questions, sends context to the hosted API, and writes/copies approved answers back. |
| V3 | Electron companion | Power-user desktop shell for deeper screen/audio/system integration once the hosted loop proves retention and willingness to pay. |

The Chrome extension is not an auto-apply tool. It is the delivery surface for
the coaching loop already implemented in `/api/assist/*`: detect question,
retrieve memory, nudge, polish, approve, and save privately. It uses ATS/site
adapters where available, a generic DOM fallback, confidence labels, and a
manual highlight/paste fallback when detection is uncertain.

V2 is security-gated before it is feature-gated. Hosted usage requires
Supabase bearer auth, route and storage ownership checks, quota recording,
retention purge jobs, SSRF-safe fetch paths, generated API contracts, and
secret scanning. The Chrome companion uses a one-time hosted pairing flow:
`/api/extension/pairing-token` creates a short-lived token for the signed-in
Supabase user, `/api/extension/exchange` accepts it only with a matching
Supabase access token, and the extension stores that bearer locally.
The Supabase Postgres/pgvector migration and RLS policy contract is committed;
hosted Postgres mode fails closed until the async storage adapter targets it.

---

## 2. What AskPicky is not

- An auto-apply tool. Never. No DOM automation, no mass submission, no "smart apply."
- A trust badge or verification service for applicants. The spam paradox kills any "I'm not spam" signal.
- An ATS, recruiter sourcing tool, or employer-facing product. Different sales motion, different company.
- An identity verifier (CLEAR/Sardine territory).
- An AI-detector for CVs (adversarial, unwinnable, contradicts using AI).
- A general job board. We don't aggregate listings; users bring URLs.
- A LangChain / RapidAPI wrapper. We use raw SDKs + Firecrawl for scraping + LangGraph for optional orchestration wrapping.

---

## 3. The four-question test

Every feature, shipped or proposed, passes or fails on these. Anything failing 2+ should cut, consolidate, or defer.

1. **Strategic fit** — serves "verify before apply" OR "learn from outcomes" OR the visa wedge?
2. **Voice fit** — Picky (honest, blunt, opinionated, anti-sycophant) needs this?
3. **Maintenance vs usage** — actually called in production at a rate that justifies its weight?
4. **Differentiation** — distinguishes AskPicky from a generic AI job tool?

---

## 4. How Picky talks

The name personifies the assistant. The voice is not generic — and it carries through to the UI itself. Picky is a *character* the user can read reactions on, not a faceless tool.

### Copy

- Honest about uncertainty. ("Don't trust me on this one — we only have 3 reports.")
- Opinionated. ("I wouldn't apply to this. Here's why.")
- Blunt but not rude. ("That role's been reposted 4 times in 3 months. Reconsider.")
- Takes a side. The verdict is a position, not a hedge.
- Not sycophantic. Never starts a reply with "Great question."
- Cites sources for every load-bearing claim.
- Uses the user's writing style for generated content (CVs, cover letters, replies) — not its own.

### Picky-as-character (added 2026-05-22)

The product previously read as a serious-but-mute analyst. The frontend now treats Picky as a character with visible reactions to the work it does:

- **A mascot with states.** An animated avatar (the `PickyAvatar` component) carries the four product states the user actually cares about: `idle / thinking / go / no_go`. Idle blinks. Thinking gets a thinking-aura. GO is a celebratory bounce. NO_GO is a deflation with a small "UGH." sticker.
- **A research-lab aesthetic.** Headings lean detective/case-file ("Case Files", "Inspect Evidence", "Risk Detected", "Approved Case"). The verdict is "Picky's call", not "the system's output". This makes the *position* feel like it's coming from someone.
- **Theatrical reveal moments.** When the verdict lands, there's a brief visual transition (`MatrixTransition`) and a rotating GO/NO_GO stamp on the verdict card. These aren't decoration — they reinforce the §3-§4 promise that *Picky took a position*, not "an LLM emitted a JSON object."

### What the character voice rules still keep

- No celebratory emoji or AI clichés. The mascot's reactions replace the emoji surface; emoji in copy is still banned.
- No exclamation marks in default-state UI text. The verdict card's serif headlines ("Go for it.", "Picky says no.") are positions, not cheers.
- Theatre serves the position. Any flourish that doesn't reinforce "Picky took a side" is decoration and gets cut. Loading shimmer on a card that has nothing to load is decoration. A rotating stamp on the verdict card that names the decision is theatre.
- Banned-phrase catalogue still enforces the prose floor. Style injection still pulls the user's voice across generators.

---

## 5. The system in 8 layers

```
+-------------------------------------------------------------+
| Layer 1: CAPTURE       - How jobs and context enter         |
+-------------------------------------------------------------+
| Layer 2: INTELLIGENCE  - What we learn about the role       |
+-------------------------------------------------------------+
| Layer 3: DECISION      - The verdict, the position          |
+-------------------------------------------------------------+
| Layer 4: ACTION        - Help acting on the verdict         |
+-------------------------------------------------------------+
| Layer 5: MEMORY        - What we know about the user        |
+-------------------------------------------------------------+
| Layer 6: NETWORK       - What we know about the market      |
|                          (the closed moat: outcomes)        |
+-------------------------------------------------------------+
| Layer 7: DISCIPLINE    - Voice, safety, citation rules      |
+-------------------------------------------------------------+
| Layer 8: OPERATIONS    - Cost, infra, monitoring            |
+-------------------------------------------------------------+
```

A feature's place in the stack tells you what breaks if it's missing.

---

## 6. Feature map by layer

Status: **S** = shipped, **B** = build new (v1 priority), **D** = deferred, **U** = under flag.
Tier: **F** = free, **P** = premium, **I** = infrastructure (invisible to user).

### Layer 1 — Capture

| Feature | Tier | Status | What breaks without it |
|---|---|---|---|
| Web URL forward | F | S | Primary entry point gone |
| Web offer-letter PDF forward | F | S | Offer-stage value disappears |
| Web onboarding wizard (career, motivations, money, deal-breakers, visa, life, samples, CV) | F | S | No personalisation, no style profile, no visa context — every verdict generic |
| CV upload (PDF / DOCX / TXT) | F | S | Style profile cold; CV tailoring impossible |
| `/api/onboarding/cv_import` multipart | F | S | Wizard CV import fails |
| Bot redirects new users to web wizard | F | S | Discoverability of onboarding broken |
| Onboarding draft persistence (localStorage) | F | S | Users lose wizard progress on tab close |
| Per-stage clarification + off-topic budgets | F | S | Conversation drifts; users hit dead ends |
| Visa eligibility check (front-page tool, no signup) | F | B | Conversion driver missing — biggest free-tier hook for the visa audience |
| Sponsor register search (better UX than gov.uk, front-page) | F | B | Wedge isn't surfaced; users don't see specialism |

### Layer 2 — Intelligence

| Feature | Tier | Status | What breaks without it |
|---|---|---|---|
| 9-agent Phase 1 parallel fan-out | F | S | **The product.** Differentiation lives here |
| JD extractor (DeepSeek V4 Flash) | F | S | Every downstream agent reasons on raw HTML |
| Tier-0 JSON-LD extractor (7 ATSes pre-LLM) | F | S | Every JD costs an LLM call — unsustainable cost |
| Company scraper + summariser (Playwright, trafilatura, BS4) | F | S | No company context; verdict reasoning hollow |
| Sponsor Register check + alias + Splink fuzzy match | F | S | Visa moat gone |
| SponsorAlternativeMatch field (ambiguity tier + match_path) | F | B | Visa false positives/negatives in tricky cases (recruitment agencies, rebrands) |
| CRN-based entity resolution + parent/subsidiary walk | F | B | Group-company sponsor licences missed (e.g. subsidiary under parent licence) |
| Companies House lookup (dissolution / admin / overdue filings) | F | S | Ghost / dying companies pass verdict |
| SOC threshold check (£41,700 + new-entrant) | F | S | Salary signal for visa wrong; verdicts mislead |
| Salary data sub-agent (ASHE primary, JD band, jobspy fallback) | F | S | No salary baseline — no defensibility analysis |
| Ghost-job detector (deterministic 5-dim score) | F | S | Volume-spam jobs pass verdict |
| Red flags detector (DeepSeek V4 Flash) | F | S | Picky can't take a sharp position on bad actors |
| Reviews scraping (Firecrawl anti-bot fallback) | F | S | No reputation signal; users blind to Glassdoor |
| Triage-before-verdict (SERIOUS / EXPLORATORY / DEFINITE_PASS, DeepSeek V4 Flash) | F | B | Every role gets full treatment — cost spirals |
| Live going-rates parser (gov.uk Appendix Skilled Occupations) | I | B | Salary defensibility premium feature impossible |
| Gov-data freshness sidecars (14d / 400d) + weekly refresh | I | S | Stale visa rules — wrong verdicts — loss of trust |

### Layer 3 — Decision

| Feature | Tier | Status | What breaks without it |
|---|---|---|---|
| Verdict agent (DeepSeek V4 Pro, 6-label taxonomy + entropy_norm) | F | S | No position. No product |
| User-type branching (resident vs visa) | F | S | Wrong verdict for half the user base |
| Hard-blocker → BLOCKED guard (fatal vs negotiable blockers) | F | S | Visa-impossible roles slip through |
| 6-label verdict taxonomy (STRONG_GO through BLOCKED) | F | S | Binary GO/NO_GO too coarse for real-world nuance |
| Citation discipline (3 kinds, enforced) | F | S | No trust. No defensible claim |
| Self-audit (Phase 4.5, banned-phrase + company-swap test) | F | S | Voice drift, sycophancy, fabrication leak through |
| Source-status fallback sentinels (OK/UNREACHABLE/NO_DATA/STALE) | F | S | Picky claims knowledge it doesn't have |
| Streaming Phase 1 progress (SSE) | F | S | Long verdicts feel dead; users churn during the 30s wait |
| LangGraph orchestrator wrapper (opt-in, checkpointed state) | F | B | Long-running pipelines lack durable retry |
| Outcome → verdict calibration loop | I | B | Network data doesn't improve verdicts — flywheel doesn't compound |
| `challenge_verdict` intent (conversational refinement) | F | B | Picky can't defend a position when pushed; voice is incomplete |

### Layer 4 — Action

| Feature | Tier | Status | What breaks without it |
|---|---|---|---|
| `draft_cv` intent (DOCX + PDF) | F | S | Users have a verdict but no help applying |
| `draft_cover_letter` intent (Citations) | F | S | Same |
| `predict_questions` intent (8–12 Qs + strategy) | F | S | Interview prep gap |
| `salary_advice` intent (4 scripts, basic) | F | S | Negotiation help missing |
| Salary defensibility (extends salary_advice with full Home Office rules) | **P** | B | Premium feature #2. Visa specialism's killer paid feature |
| `draft_reply` intent (short + long) | F | S | Recruiter reply friction; users churn back to manual |
| `full_prep` (4 generators parallel + SSE) | F (capped) / P (uncapped) | S | Single-shot pack generation impossible |
| Application assist loop (classify, retrieve memory, critique, polish, approve) | F (capped) / P (uncapped) | S | Users still leave the app to answer form questions manually |
| `application_answer_shaper` agent | F | S | Final answers are not voice-preserved or memory-grounded |
| Question Designer (3 Qs before pack) | F | S | Tailoring quality drops without role-specific Qs |
| STAR Polisher | F | S | CV bullets generic, not story-driven |
| CV tailor — single consolidated adapter (cut multi-provider routing + LaTeX templates) | F | B (consolidate) | Tailoring quality unchanged but maintenance halves |
| Tailored CV version management (saved per role) | F | B | "System of record" promise broken; users re-tailor from scratch |
| Application autopsy after rejection | **P** | B | Premium feature #3. Post-outcome learning loop |
| Three packaged Agent Skills (uk_cv, uk_cover_letter, interview_prep) | F | S | Generator outputs lose UK-specific polish |

### Layer 5 — Memory

| Feature | Tier | Status | What breaks without it |
|---|---|---|---|
| `memory/` module (recorder + recall) | F | S | No cross-application learning; every session cold |
| FAISS over career entries (MiniLM) | F | S | Tailoring uses irrelevant entries; STAR bank doesn't surface |
| 6 CareerEntry kinds (motivation/deal_breaker/preference/project_note/cv_bullet/conversation) | F | S | Memory becomes a blob with no structure |
| WritingStyleProfile (tone, length, formality, hedging, signature/avoided) | F | S | Generated content sounds like Claude, not user |
| Style profile downgrade when sample_count < 3 | F | S | Style overconfidence on thin signal |
| Style injection across all generators + STAR + draft_reply | F | S | Voice cloning broken |
| Story-bank weighting (STAR_BOOST_KINDS) | F | S | Tailoring picks weak bullets |
| Private evidence graph (`ExperienceAtom`, `StoryFrame`, `MemoryEdge`) | F | S | Memory stays as unstructured story notes and cannot adapt per question |
| AnswerAttempt auto-save with raw-retention metadata | F | S | No source trail for application-assist learning |
| Memory Inbox review gate | F | S | Auto-extracted memory affects suggestions without user approval |
| Sensitive-memory private default | F | S | Visa/salary/family context leaks into future suggestions too easily |
| Hybrid application-memory recall | F | S | Live assist becomes too slow or too generic |
| `memory_extractor` background agent | I | U | Deterministic extraction works, but richer story framing cannot run under budget control |
| Verdict ignores story-bank weights (separation of concerns) | F | S | Personal optimism bleeds into verdict — verdict no longer honest |
| Cross-application outcome recorder | F | S | No data flowing into Layer 6 — moat doesn't form |
| Recruiter-interaction recorder (fires post-draft_reply) | F | S | Negotiation memory cold; salary advice generic |
| Outcome recall during salary advice | F | S | Same as above |
| Recruiter-interaction recall during draft_reply | F | S | Same |
| Personal application tracker + follow-up reminders | F | B | "System of record" promise hollow; users churn to spreadsheets |
| MotivationProfile recalibrated from outcomes | I | D | Refinement — frozen profile fine for v1 |

### Layer 6 — Network (the moat)

| Feature | Tier | Status | What breaks without it |
|---|---|---|---|
| **One-tap outcome reporting (Day-21 nudge)** | F | B | **No data network. No moat. No premium tier in 12 months.** This is P0 |
| Smart-timed reporting nudges (selection-bias mitigation) | F | B | Reporting too sparse / too biased |
| Light verification of adversarial reports (subject / recruiter / date cross-ref) | F | B | Data quality collapses; benchmarks unusable |
| "Insufficient data" honest UI for long-tail employers | F | B | Trust collapses on first sparse data point |
| **Aggregated employer-behaviour database** | **P** (read) / F (contribute) | B | Premium feature #4 (benchmarks). The closed moat |
| Pre-application employer benchmarks (response rate / interview→offer / ghost frequency / time-to-response) | **P** | B | Premium feature #4 |
| Methodology transparency on benchmarks (sample size, takedown, employer-invite-to-comment) | F | B | Legal exposure (defamation, GDPR); user trust |
| Product-relative benchmark framing (honest about selection bias) | F | B | Misleading benchmarks degrade trust |
| Sponsor licence change alerts on saved roles | F | B | Visa-aware retention hook missing; users churn between job searches |
| Hosted continuous monitoring (compute SaaS) | **P** (heavy) | D | Premium tier infrastructure — wait for usage |
| Anonymised market-data licensing | **P** (future) | D | Future tier; not v1 |

### Layer 7 — Discipline

| Feature | Tier | Status | What breaks without it |
|---|---|---|---|
| Banned-phrase enforcement (~21 patterns) | I | S | Sycophancy + AI-slop creep into output |
| Banned-phrase post-validator in adapter | I | S | Catches what generation missed |
| Citation discipline (3-kind) enforced across verdict / cover_letter / draft_reply / likely_questions / salary_strategist / red_flags / offer | I | S | Trust model collapses |
| Self-audit company-swap test | I | S | Fabrication / hallucination leak |
| Content Shield Tier 1 (regex) | I | S | Trivial abuse passes |
| Content Shield Tier 2 (Sonnet classifier) | I | S | Subtle abuse passes |
| Fail-closed shield on transient errors for high-stakes | I | S | Errors bypass safety |
| PII scrubber | I | S | Data leaks in logs / cost reports / outputs |
| Prompt auditor (build-time predicted + empirical Code Execution) | I | S | Prompt regressions silent until production |

### Layer 8 — Operations

| Feature | Tier | Status | What breaks without it |
|---|---|---|---|
| Cost log with cache-read/creation tokens | I | S | Can't reason about per-user economics |
| Per-stage prompt caching (5m + 1hr opt-in) | I | S | Cost spirals 3-5x |
| Correlation IDs (request / session contextvars) | I | S | Debugging multi-stage runs impossible |
| Per-stage timing + token logging | I | S | Same |
| SQLite WAL + busy_timeout | I | S | Concurrent users break |
| Single → multi-user identity seam (ADR-0001) | I | S | Migration to multi-tenant requires rewrite |
| Startup secrets validation | I | S | Production crashes mid-request |
| Files API for PDFs | I | S | Offer analysis broken; PDF handling hand-rolled |
| Friendly rate-limit replies (429 + Retry-After) | I | S | Users hit walls without explanation |
| Sliding-window rate limit per (user, intent_category) | I | S | Cost runaway from single bad actor |
| Credits check with priority refusal at <$20 | I | S | Account drains mid-month |
| Batch URL queue with Semaphore(3) concurrency cap | I | S | Bulk runs DoS the system |
| Compaction + context-editing helper (opt-in) | I | S | Long sessions hit context limits |
| Real Batch API dispatch (50% discount) | I | D | Cost optimisation, not strategic for v1 |

---

## 7. Free tier — definition

**The free tier must deliver the core promise alone.** A user who never pays must still get genuine value: verify roles, get visa-aware signals, apply with help, track outcomes.

### What's in free

- All capture surfaces (web)
- Full onboarding + style + CV import
- Phase 1 9-agent verdict with citations — **rate-limited to N/month (suggest 15)**
- All visa-specific features (sponsor register, Companies House, SOC, alerts, eligibility check)
- Application generation (CV / cover letter / questions / reply / salary advice) — capped at packs per month
- Personal memory + style + tailored CV versions
- Application tracker + reminders
- **One-tap outcome reporting (always free, non-negotiable — feeds the network)**
- Triage layer (avoids burning quota on cheap "DEFINITE_PASS" / exploratory checks)
- Reviews investigator (light depth, Reddit + archives)
- All Layer 7 discipline (banned-phrase, citations, content shield, PII)

### What's not in free

- Continuous monitoring (running deep verification on saved roles in background)
- Aggregated employer benchmarks lookup
- Salary defensibility (full Home Office rules check)
- Application autopsy
- Reviews investigator at deep depth (Glassdoor archive deep-dive)
- Verdict refinement / challenge mode unlimited (free gets N challenges/month)
- Priority Phase 1 processing (free tier waits in queue when load is high)

### Rate-limit principles for free

- Limits scale to **realistic monthly job-search behaviour** (15–25 deep verdicts is plenty for a thoughtful applicant — auto-apply spammers don't fit this product anyway)
- Limits **reset monthly**, not weekly (no anxiety pressure)
- Limits **clearly visible** in UI ("12 verdicts used this month") so users plan
- Limits never gate **outcome reporting** — that's always free, always one-tap

---

## 8. Premium tier — definition

**Premium accelerates and deepens. It does not replace the free experience.** The four premium features are bets on willingness-to-pay at moments of high leverage.

### What's in premium

| Premium feature | The moment user pays | Compute cost |
|---|---|---|
| Real-time hiring intent verification | "I'm about to spend 4 hours on this application" | High |
| Pre-application employer benchmarks | "Has anyone here actually heard back?" | Low (DB) |
| Salary defensibility for visa roles | "Is this offer going to clear Home Office?" | Medium |
| Application autopsy after rejection | "Why did I not get this one?" | High |

### Premium also includes

- Unlimited verdicts (no monthly cap)
- Continuous background monitoring on saved roles (sponsor licence, salary changes, repost detection)
- Priority Phase 1 queue
- Unlimited pack generation
- Reviews investigator at deep depth

---

## 9. Pricing principles

**Goal:** premium accessible to a job-seeker on a budget. A single avoided ghost-job application saves 2-4 hours; one well-defended salary negotiation saves £5,000+. Pricing must reflect that asymmetry without exploiting it.

### Pricing rules

1. **Job searches aren't permanent.** Subscription pressure is wrong for the audience. Default to credits + pay-as-you-go.
2. **Premium must clear under £10/month** for a casual user, **under £20/month** for an active job seeker. Anything higher and users self-host.
3. **Contribute-to-earn is real.** Outcome reports = premium credits. A user who reports every outcome they have should never need to pay.
4. **Transparent credit costs per feature** — no hidden charges, no surprise depletions.
5. **Free tier rate limits are generous enough that pre-paying isn't required to evaluate the product.** First-touch conversion is via the free tier's quality, not a paywall.

### Suggested credit costs (calibrate from real compute costs)

| Action | Credits |
|---|---|
| Free tier deep verdict (above monthly cap) | 5 |
| Real-time hiring intent verification | 10 |
| Employer benchmark lookup | 1 |
| Salary defensibility check | 15 |
| Application autopsy | 20 |
| Outcome report (earn) | +2 |
| Verified outcome report w/ evidence | +5 |

### Suggested price points

| Tier | Price | Credits / month |
|---|---|---|
| Free | £0 | 30 included (regenerate monthly) |
| Top-up | £5 | 100 |
| Top-up | £15 | 350 |
| Subscription "Active job search" | £8/month | 250 + rollover up to 500 |
| Subscription "Heavy use" | £15/month | 600 + rollover |

These are illustrative — calibrate against actual compute spend after the first 100 paying users.

---

## 10. Build roadmap

### P0 — must ship before any premium

These close the gap between current state and the new positioning. Without them, the strategic shift is aspirational.

1. One-tap outcome reporting (Day-21 nudge + smart-timed)
2. Light verification of adversarial reports
3. Personal application tracker + follow-up reminders
4. Tailored CV version management
5. Hosted application-assist editor UI over the new `/api/assist/*` routes
6. Hardened private-save controls: raw retention purge, memory export/edit/merge/delete, cross-user isolation tests
7. Application cockpit + evidence-vault redesign for the web app
8. Chrome MV3 companion scaffold after web hardening
9. Triage-before-verdict layer
10. Visa eligibility check (front-page tool)
11. Sponsor register search (front-page tool)
12. CV tailor consolidation (cut multi-provider routing + LaTeX templates)
13. Operational debt: fix doc drift, missing canonical docs, license drift, duplicate PROCESS entries, agent-call inventory
14. Keep AskPicky naming consistent across repo, README, brand assets

### P1 — first premium feature ships

1. Live going-rates parser (gov.uk Appendix)
2. Salary defensibility for visa roles (extends salary_advice) — **Premium feature #1 to ship**
3. CRN-based entity resolution + parent/subsidiary walk
4. Sponsor licence change alerts on saved roles
5. Live-web hiring-intent verification (multi-step DeepSeek agent with Firecrawl) — **Premium feature #2**

### P2 — data network reaches threshold (~1,000 contributing users)

1. Aggregated employer-behaviour database queries — **Premium feature #3** (benchmarks)
2. Methodology transparency UI + "Insufficient data" honest UI
3. Outcome → verdict calibration loop
4. `challenge_verdict` intent

### P3 — late premium + quality

1. Application autopsy after rejection — **Premium feature #4**
2. Phase 1 signal weighting (learned)
3. Freshness gradient (continuous staleness)
4. Continuous background monitoring of saved roles
5. Always-on company research with Firecrawl + Playwright pipeline

### Deferred indefinitely (until evidence demands it)

V2 is security-gated before Chrome is treated as a commercial release:
Supabase hosted auth/storage, tenant isolation, SSRF protection, quota ledger,
privacy retention jobs, generated API contract, and cleanup of removed
compatibility paths. See `V2_SECURITY_CHROME_PLAN.md`.

- Real Batch API dispatch (cost optimisation only)
- Daily Sponsor Register refresh (weekly fine)
- Verdict ensemble (parallel x2) — voice-incompatible with Picky's confidence
- Competitive ranking (`compare_verdicts`)
- AskPicky Interview (sister product, separate decision)
- Coaching module for interview role-play (lives under AskPicky Interview if it ever ships)

### Cut entirely

- LaTeX CV renderer + LaTeX writer/repairer agents + LaTeX sandbox
- Legacy single-provider runtime entirely — all models via DeepSeek + OpenAI tiers (2026-05-25)
- Legacy live-research sandbox stubs (company_investigator, reviews_investigator, verdict_deep_research) — removed
- Multi-provider CV tailor v1 — replaced by unified agent_model_map routing
- Binary GO/NO_GO verdict — replaced by 6-label VerdictLabel taxonomy
- Cohere provider — dead code, no integration
- Three competing CV-tailor feature flags — collapse to one
- All discarded `new_claude.md` items (Smart-Apply, Concierge, behavioural telemetry, self-healing schema, IP rotation, "Behavioral Moat" framing)

---

## 11. Operational hygiene before more building

Doc drift means scope can't be reasoned about cleanly. Fix this before any P0 build.

1. Delete or write the 6 missing canonical docs (ARCHITECTURE.md, SCHEMAS.md, PROJECT_STRUCTURE.md, SUBMISSION.md, MIGRATION_PLAN.md, CLAUDE_DESIGN_PLAYBOOK.md)
2. Fix licence drift in PROCESS.md Entry 18 (still says MIT; actual is AGPL-3.0)
3. Resolve PROCESS.md duplicate entry numbers (29, 44 appear twice)
4. Update agent count in README + AGENTS.md to match reality
5. Inventory which of the 22 agents are actually called — cut anything not used in past 30 days of dev
6. Resolve AGENTS.md vs CLAUDE.md verdict-adapter contradiction (pick the real implementation)
7. Audit which feature flags have ever flipped on in production — anything default-off forever is dead code

This doc is the new canonical reference. All older docs should point here for product definition and only retain their narrow operational scope (process log, agent inventory, architecture diagram).

---

## 12. Open strategic questions (decisions deferred)

- Reporting opt-in vs opt-out at nudge level (current bias: opt-out at nudge, never silent reporting)
- AskPicky Interview brand: shared account, separate product
- Auth mechanism for multi-user (ADR not yet written)
- Cross-surface identity unification (web user identity)
- Exact credit costs and price points (calibrate against real compute spend post-first-100-users)
- Whether AskPicky publishes anonymised market data publicly (free goodwill) vs paid licensing only

Resolved 2026-06-01:

- Private-save is the default for application assist. Private memory recall is
  opt-in per answer/session through an explicit UI toggle.
- Chrome MV3 ships before Electron, but uses portable APIs so Edge can follow.
- Hosted outcome/benchmark intelligence is the commercial moat; forks can run
  the open core but do not receive hosted aggregate employer data unless they
  join the hosted contribution loop.

---

## 13. Visual / UI direction

Revised 2026-05-22 to match the Picky-as-character voice (see §4).

Application assist revision 2026-06-01: the dedicated web workspace should
feel like an application cockpit and evidence vault, not a chatbot dashboard.
The assist screen prioritises the current JD/question, rubric nudges, best
story angles, answer draft, final answer, and save state. The memory screen
prioritises provenance, pending/private status, edit/merge/delete controls,
and outcome-backed story reuse.

- **Brand colour:** **VSCode blue** (`#007ACC` primary) on a deep dark canvas (Zinc-9 cards on Zinc-12 background). Status colours: success green, destructive red, warning amber — saturated, not muted.
- **Typography is a brand asset.** Three self-hosted families (no third-party CDN — GDPR): **Fraunces** (serif display, for verdict headlines and the brand mark), **Inter** (sans body), **JetBrains Mono** (citations, agent labels, gov-data IDs). Self-hosted via `@fontsource/*` packages — no Google Fonts CDN calls at runtime.
- **Layout: sidebar + canvas.** 256px sidebar with the PickyAvatar logo, nav, and a live status block (real session counts — never hardcoded marketing copy). Main canvas is a wide research-lab surface.
- **Voice in the UI matches voice in copy.** Blunt, opinionated, honest about uncertainty. No celebratory emoji. No exclamation marks in default-state UI text. Verdict serif headlines ("Go for it." / "Picky says no.") are positions, not cheers.
- **Citations are first-class.** Cited substrings are visually distinct (mono font, inline link affordance) and not hidden in tooltips.
- **Purposeful theatre.** Motion serves state OR reinforces "Picky took a position" — never decoration. The verdict reveal gets a brief matrix-style transition; the verdict card gets a rotating GO/NO_GO stamp; the PickyAvatar mascot has per-state reactions (idle blink, thinking aura, GO bounce, NO_GO "UGH." sticker). Loading shimmer on a card with nothing to load is still decoration and still gets cut.
- **Honest status surfaces.** Anywhere the UI claims a system fact ("N roles checked this week", "X% confidence on this verdict"), the number is pulled from real data. Hardcoded marketing copy in a system-status slot violates the §4 "honest about uncertainty" rule and is treated as a bug.

---

*End of v1.0. Next revisions: capture P0 build progress, calibrate credit costs against real compute data, fill in any of section 12.*
