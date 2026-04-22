# PROCESS.md — Design Decision Log

> The full thinking process behind Trajectory, from first brief to
> final product. If a judge asks "why did you choose X?", the answer
> is in here.

---

## How to read this doc

Entries are chronological. Each entry records:

- **What was on the table** — the state before a decision
- **What changed** — the new direction or refinement
- **Why** — the reasoning
- **What it cost or unlocked** — the trade-off

This doc does not hide the pivots. The hackathon's "Depth & Execution" criterion (20% of judging) explicitly rewards projects where the team "pushed past their first idea". These pivots are the evidence.

---

## Entry 1 — The brief

Kene arrived with a 4-day window to build something for the Built with Opus 4.7 Claude Code hackathon. First message: "How can I win?"

The starting position:
- Solo builder (team size max 2, picked solo)
- Target: prize pool of $100K in Claude API credits
- Judged by 6 Anthropic engineers
- Judging criteria: Impact 30%, Demo 25%, Opus 4.7 Use 25%, Depth & Execution 20%
- Two problem statements: "Build From What You Know" vs "Build For What's Next"

**Decision made early:** Problem Statement 1 — Build From What You Know. Pattern-matched against last round's winners (4 of 5 were domain experts, not professional developers). Lived expertise is the moat; judges can't fake-build what they don't know.

## Entry 2 — Which lived expertise?

Kene surfaced several candidate domains:

| Domain | Depth | Verdict |
|--------|-------|---------|
| Clinical RAG / healthcare (MSc topic) | Strong academically | Rejected — cardiologist already won this lane last round |
| Renewable energy developer credibility (Kanu DDCE work) | Strong commercial | Rejected — IP conflicts with live commercial work |
| Gambling / compliance (Betfred floor) | Lived daily | Considered — narrow judge empathy |
| UK job search / visa hiring | Lived daily | **Chosen** |

**What the decision cost:** emotional pull toward healthcare where the academic credentials live.

**What it unlocked:** a domain where Kene is literally the end-user, every other builder in the 500 lacks the lived context, and the moat is clear.

## Entry 3 — Initial framing: visa-holder primary

First product concept: a tool specifically for UK visa-dependent candidates. Sponsor Register checks, SOC threshold verification, nationality-specific grant data.

**Why this was chosen first:** Kene's own story is the visa-holder story. Mike Brown (last round's 1st place winner) won by solving his own problem.

## Entry 4 — First major pivot: broaden to UK residents

Mid-thread, Kene pushed back: "The visa thing is a great sell but not strong — I want to strengthen the non-visa applicant pipeline because that's most of the market."

**This was correct.** Reasoning:

1. UK visa sponsorship is ~80–120k CoS per year. UK job applications overall run into tens of millions. Two orders of magnitude.
2. Anthropic judges in SF don't personally feel UK visa pain. They do feel "I've wondered if I left money on the table on a salary negotiation".
3. Post-hackathon product-market fit: visa-only is a niche; "honest job-search PA" is a category.
4. The moat (live government data + verbatim citations + writing in user's voice) applies to both user types.

**Resolution:** Two user types, both first-class:
- UK Resident (primary by market size) — gets salary benchmarking, ghost-job detection, Companies House health, deal-breaker checks, motivation fit
- Visa Holder (secondary, sharper) — gets all the above PLUS Sponsor Register and SOC threshold checks

**Framing note:** Kene's personal story stays in the narrative ("built because my visa made me aware of every information asymmetry") but the product serves everyone. This is the strongest framing — it earns the moat through lived expertise without narrowing the product to the niche.

## Entry 5 — The ghost-job insight

Once UK-resident became primary, the hard-blocker logic needed sharpening. Sponsor Register + SOC threshold don't apply to UK residents. What replaces them?

Research revealed:
- **StandOut CV analysis of 91,318 UK job listings: 34.4% are ghost jobs**
- **Software engineer jobs specifically: 46.5% ghost rate**
- **69.4% of companies admit to posting ghost jobs at least occasionally**

This became both:
1. A primary hard blocker for UK residents
2. The opening hook for the demo narrative

**Ghost job detection is probabilistic, not deterministic.** Four signals combine:
1. Posting age (stale >30 days, hard flag >60)
2. Not on the company's own careers page
3. JD vagueness (LLM-scored on 5 dimensions)
4. Company distress markers from Companies House

Combination logic produces LIKELY_GHOST / POSSIBLE_GHOST / LIKELY_REAL with HIGH / MEDIUM / LOW confidence.

**Honest caveat documented**: false positives are possible (legitimate 45-day postings at slow enterprises). Mitigated by always showing which signals triggered, never just a verdict.

## Entry 6 — The salary strategist

Sharpest single feature addition. Every candidate hits "what's your salary expectation?" — the single most expensive guess in the hiring process.

No existing tool does this well with UK-specific grounding. AIApply, JobCopilot, FirstResume, Teal — none cross-reference:
- SOC going rates (visa-critical)
- Companies House financial health (can they afford it?)
- Glassdoor / Levels.fyi salary data
- User's personal floor and target

**The feature design:**
- `opening_number` — what to say first (60–70th percentile by default)
- `floor` — walk-away (personal floor, or sponsor floor for visa holders)
- `ceiling` — push-to for later rounds (90th percentile)
- `scripts` — exact phrasings for 4 moments: recruiter first call, hiring manager ask, offer counter, pushback response

## Entry 7 — Salary adapts to situation

Kene: "The salary offer would be suggestive based on the user's situation."

Initial interpretation was just a framing softening. But on push-back, the real interpretation emerged: **the numbers should change based on user context**.

A visa holder with 6 months until expiry needs offer security more than optimal number. Someone unemployed for 8 months opens lower than someone employed and patient. Someone just rejected 5 times in a week pitches below someone fresh to the search.

**Resolution:** `JobSearchContext` computed fresh per salary request:
- urgency level (LOW / MEDIUM / HIGH / CRITICAL)
- recent rejection count
- time since last offer
- months until visa expiry
- current employment status
- search duration

Urgency adjusts both the opening percentile (lower urgency → higher percentile) and the script tone (LOW = assertive, CRITICAL = stability-first).

**Why this matters competitively:** it's genuinely novel. No salary tool adapts to the human situation of the person negotiating. Most treat salary as a market lookup. This treats it as a negotiation strategy informed by real constraints.

## Entry 8 — Dialogue-driven generation (not one-shot)

Original Phase 4 design: verdict → 3 questions → auto-generate pack.

Kene pushed: "The candidate pack would only be asked on request, not generated on the fly."

**Why this is better:**
1. Real user behaviour — most job decisions are "let me read and think overnight"
2. Saves credits — 60%+ of verdicted jobs probably never get applied to
3. Sharper per-request quality — re-research at generation time gives fresh data
4. Matches PA framing — a PA drafts what you ask for, not everything proactively

**Architectural shift:** Phase 4 components became their own intents (draft_cv, draft_cover_letter, salary_advice, predict_questions, draft_reply, full_prep). The Opus 4.7 parallel fan-out moment moved from always-on to user-triggered via `full_prep`.

**Cost:** the "always ship a pack" demo beat was lost. **Gain:** a naturalistic PA demo beat (user asks for salary, bot responds) replaces it, which is actually more compelling for the judges.

## Entry 9 — Writing style capture

This is the feature that eliminates the AI-slop tell.

Every cover letter generated by AIApply / Teal / Jobscan reads like AI wrote it. The signature: certain sentence rhythms, certain transitions, certain words LLMs over-index on.

**The feature:** during onboarding, capture 3–5 professional writing samples (emails, cover letters, LinkedIn posts). Extract a `WritingStyleProfile`:
- tone (concrete 3–5 words)
- sentence length preference
- formality level 1–10
- hedging tendency
- signature patterns (verbatim phrases the user actually uses)
- avoided patterns (corporate phrases notably absent)
- 5–7 verbatim example sentences

Every Phase 4 generator (CV tailor, cover letter, etc.) receives this profile in its system prompt. Self-audit checks style conformance after generation.

**Competitive moat:** visible in the output. Generic AI cover letter uses "I'm excited to apply" and "passionate about". Trajectory cover letter uses the user's actual phrases. Judge-observable on a single demo.

## Entry 10 — Motivations beyond money

Kene flagged: onboarding should capture motivations beyond money.

**Why this matters:** money-only user modelling produces shallow verdicts. A job might clear all hard blockers and still be wrong for this person because it bores them, because it has a commute pattern they hate, because it's in an industry they won't enter.

**Six-topic onboarding:**
1. Career narrative
2. Motivations (what energises, what drains)
3. Money (floor and target)
4. Deal-breakers and good-role signals
5. Visa/location situation
6. Life and urgency context

Each answer generates `CareerEntry` rows with kinds like `motivation`, `deal_breaker`, `preference`. The verdict agent retrieves relevant motivations per job and scores motivation fit, generating `MOTIVATION_MISMATCH` as a stretch concern when 2+ motivations misalign.

**Competitive effect:** the verdict isn't just "sponsor-legal and salary-adequate". It's "sponsor-legal, salary-adequate, AND aligned with what you've told me you actually want".

## Entry 11 — Never auto-applies (philosophical moat)

Every scaled competitor (AIApply, JobHire.AI, Jobr.pro, LazyApply) is built around volume auto-application. Some have BBB F ratings for this specifically.

**Trajectory's position:** deliberately does NOT auto-apply. Makes this explicit in the product, the name, the positioning.

**Why this wins with Anthropic judges specifically:**
1. Matches Anthropic's own philosophical stance on AI safety and thoughtful deployment
2. Volume auto-apply is making the job market worse for everyone (ghost jobs partly caused by this); Trajectory is a counter-positioned alternative
3. Judge-narratable in a single sentence: "everyone else built a bot that applies for you. I built one that tells you honestly whether to apply yourself."

## Entry 12 — Chat-native (Telegram)

Early consideration was a web dashboard. Rejected.

**Why Telegram:**
1. No friction — paste job URL in chat, get answer. No tab-switching, no signup.
2. Matches user behaviour — people forward interesting jobs to friends; same action here goes to the PA.
3. Cross-platform native UI — iOS, Android, desktop, web all work identically.
4. Python-telegram-bot async long-polling is trivial — no webhook infra for the demo.

**Streamlit dashboard kept** as a secondary surface for session history viewing, not primary interaction.

**WhatsApp initially considered** — rejected because:
- Business API approval 24–72h (risky for hackathon timeline)
- Template message restrictions
- Telegram looks identical in demo video

The pitch frames the product as "chat-native, WhatsApp-ready" to capture the broader market positioning without the WhatsApp approval risk.

## Entry 13 — The $500 credits clarification

Mid-thread clarification: the $500 hackathon API credits fund the product's runtime token usage, not Claude Code's coding assistance during development.

**Implication:** budget aggressively, not frugally:
- ~$100 for build-time prompt iteration (15–25 full pipeline runs)
- ~$30 for demo recording
- ~$80 reserve for judge testing
- ~$290 buffer

**Don't downgrade to Sonnet to save credits on quality-critical agents.** The "Opus 4.7 Use" criterion is 25% of judging. Default Opus 4.7 xhigh for all reasoning-heavy agents; Sonnet 4.6 only for deterministic extraction.

## Entry 14 — Managed Agents integration

Anthropic launched Managed Agents on April 8, 2026 (weeks before the hackathon). The "Best Use of Claude Managed Agents" prize ($5K) explicitly rewards "something you'd actually ship".

**Decision:** use Managed Agents for the two long-running parallel blocks (Phase 1 research, Phase 4 `full_prep` fan-out). Everything else via plain Messages API.

**Known risks:**
- Multi-agent coordination requires research preview access, not automatic with hackathon API keys
- Beta API can flake
- Single-agent Managed Agents work — multi-agent doesn't

**Mitigation:** 2-hour cutoff rule. If Managed Agents beta is flaking on Wednesday afternoon, rip it out, fall back to `asyncio.gather` with plain Messages API. Same architecture, less Anthropic platform credit, same product quality.

## Entry 15 — Demo video: animated + live hybrid

Initial plan: full screen recording of real Telegram flow.

Pivot: "Animated text-based interaction where a friend recommends a job, user copies to Telegram, everything happens — very artsy."

**Concern raised:** pure animation hides the engineering. Judges might think it's a visual concept, not working code.

**Resolution:** 2:20 animated narrative + 40s real footage at the end. Animation tells the story cinematically; live segment proves the code works.

**Tool stack:**
- Claude Design for static frames (title cards, chat mockups, verdict displays)
- Screen.studio for the live segment (automatic cinematic styling of a raw screen recording)
- Simple timeline editor for stitching + voiceover sync

## Entry 16 — Citation discipline as the technical moat

Across the thread, one principle kept reinforcing itself: every generated claim must cite a real source.

**Three citation types:**
1. `url_snippet` — verbatim text from a scraped company page + URL
2. `gov_data` — specific field + value from UK gov data (e.g., `sponsor_register.status = NOT_LISTED`)
3. `career_entry` — specific row in the user's career knowledge store

**Validation:** runs after every generation. Invalid citations trigger one retry with feedback. Second failure fails loud.

**Why this is the moat:** competitors produce confident output with no backing. Trajectory produces less output but every piece is click-verifiable. A judge clicking a citation sees the exact gov.uk page or company blog post the claim came from.

## Entry 17 — The scope cut list discipline

Across the thread, scope grew: two user types → motivations → writing style → on-demand generation → situational salary → ghost jobs → PA surface → 11 intents → Managed Agents → animated video.

**Cut list (ordered), if Saturday night isn't end-to-end working:**
1. Self-audit (Phase 4.5)
2. Style-conformance check in self-audit (keep extraction + injection)
3. Ghost-job signal 4 (company distress)
4. Intent router edge cases (drop to 5 core intents)
5. Streamlit dashboard
6. Managed Agents wrapping
7. JobSearchContext computed fresh (store on profile instead)

**Never cut:** onboarding + style extractor, Phase 1 core 6 sub-agents, verdict with motivation-fit, salary strategist, 3 of 4 Phase 4 generators, citation validator, basic Telegram flow.

## Entry 18 — The hackathon rules read

Mid-thread, the rules clarified several things:
- **Open source mandatory** — every component under an approved OSS licence. Closed-model API calls (like Opus 4.7) are fine; the project code must be open.
- **New work only** — everything built during the hackathon window. This means the detailed product plan is fine (design is not code); the actual implementation must be fresh.
- **Judging criteria** — Impact 30% / Demo 25% / Opus 4.7 Use 25% / Depth & Execution 20%
- **Submission** — video + repo + 100–200 word description. No deployed URL required. This saved 0.5–1 day vs earlier planning.

**Licence chosen: MIT.** Low friction for adoption; post-hackathon commercial path separate.

## Entry 19 — The final scope

| Piece | In V1 |
|-------|-------|
| 11-intent natural-language PA surface | Yes |
| Onboarding flow (6 topics + writing samples) | Yes |
| Writing style extraction + injection | Yes |
| 8 Phase 1 parallel sub-agents | Yes |
| Ghost-job detector with 4 signals | Yes |
| UK government data grounding | Yes |
| Verdict with motivation fit + user-type branching | Yes |
| 3 Phase 3 questions + STAR polish | Yes |
| 4 Phase 4 generators (CV, cover letter, likely Qs, salary) | Yes |
| Salary strategist with JobSearchContext | Yes |
| Self-audit Phase 4.5 | Yes |
| Draft reply intent | Yes |
| Citation validator | Yes |
| Career knowledge store with embeddings | Yes |
| Telegram bot with long-polling | Yes |
| Streamlit dashboard | Yes |
| Managed Agents (Phase 1 + full_prep, fallback ready) | Yes |
| 2:20 animated + 40s live demo video | Yes |

**Explicitly not in V1:** auto-apply (philosophical), multi-tenant auth, Postgres, CI/CD, deployed public URL, email integration, calendar integration, multi-language, iOS/Android native apps.

## Entry 20 — The framing that emerged

By the end of the thread, the product had a single coherent framing:

> "A personal assistant for UK job search. Lives in Telegram. Tells you
> the truth about each job — grounded in live government data. Writes in
> your voice, not AI voice. Adapts to your situation. Never auto-applies."

Problem Statement 1 — Build From What You Know. 18 months of lived job-search pain, built by someone who is literally the target user, serving the broader UK market that shares the same information asymmetries.

---

## What wasn't chosen and why

### Rejected: Kubernetes cost optimisation agent

Considered early as a money-saving infrastructure play. Rejected because:
- Required K8s domain depth Kene doesn't have yet (Docker still actively learning)
- "Native to me" test failed — Kene's identity is AI/NLP + career changer, not SRE
- Would have been a strong hackathon project but not the right one for this builder

### Rejected: Knowledge Graph + Dijkstra "insight layer"

Considered as a healthcare RE system. Rejected because:
- Framed around "beating LLMs" — wrong pitch for Anthropic judges
- 48h to fine-tune a model doesn't work
- Clinical RE is a 15-year-old solved problem; SciSpacy exists
- "Dijkstra insight layer" was algorithmic theatre, not real insight
- No shocking before/after stat

### Rejected: LinkedIn scraping via grey-area RapidAPI

Considered for target-company people data. Rejected because:
- Violates LinkedIn ToS
- Break-risk on demo day
- Incompatible with "real product post-hackathon" ambition
- Apollo.io / Hunter.io exist and are compliant

### Rejected: Pure Messages API (skip Managed Agents)

Considered as a safety-first simplification. Rejected because:
- Opus 4.7 Use is 25% of judging; using Anthropic's latest platform stack scores higher
- Category prize ($5K) for Best Managed Agents use is realistic
- Path B (single Managed Agents session wrapping internal asyncio fan-out) is low-risk adoption

### Rejected: Visa-holder-only framing

Covered in Entry 4. Right call to broaden.

### Rejected: Auto-applying

Covered in Entry 11. Philosophical moat — never revisit.

---

## Post-hackathon roadmap (noted, not built)

Things explicitly deferred:
- Calendar writes (proposing interview slots)
- Dedicated email + inbox monitoring
- Multi-tenant auth
- Production deployment
- Natural language voice interface
- Coaching module for interview role-play
- Integration with Greenhouse, Workday, and other ATS platforms for direct submission

These live in a README roadmap section. The hackathon scope is deliberately narrower.
