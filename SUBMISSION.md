# SUBMISSION.md — Hackathon Submission Pack

> Final submission checklist, video script, written description.
> Use this as the single reference document on Sunday night.

---

## 1. Submission deadline

**Sunday 26 April 2026, 8:00 PM EST = Monday 27 April 1:00 AM BST.**

Live finals: **Tuesday 28 April 2026, 5:00 PM BST** (for medaling teams).

Build window: **Tue 21 Apr → Sun 26 Apr**. One full week of hacking.

---

## 2. What the submission must include

Per the hackathon rules:

| Item | Spec |
|------|------|
| Video | Up to 3:00, YouTube unlisted URL |
| GitHub repo | Public, open-source licence (MIT chosen), README with setup instructions |
| Written description | 100–200 words |

---

## 3. Video script (final draft)

Total: 3:00 target (hard cap 3:00). Mix of animated narrative and live footage. See `CLAUDE_DESIGN_PLAYBOOK.md` for visual production details.

### [0:00–0:18] Opening — title card + hook

**Visual:** Trajectory title card on clean off-white background.

**VO:**
> "Over the last 18 months on a UK Graduate visa, I applied to more than 80 jobs. Research says about a third of UK job listings are ghost postings — for software roles, closer to half. The rest were below sponsorship thresholds, or at companies not even on the UK Sponsor Register. I built Trajectory because the AI job-search tools I tried were making the problem worse."

### [0:18–0:45] Setup — friend sends job, user forwards to bot

**Visual:** iMessage mockup — friend message, link, user's "Let me check. Sending to my PA." — transitions to Telegram chat with Trajectory.

**VO:**
> "A friend sends me a job. Looks fine on paper. Instead of burning three hours writing a tailored CV and cover letter, I forward it to Trajectory."

### [0:45–1:20] Phase 1 fan-out — 8 parallel Opus 4.7 agents

**Visual:** Trajectory chat bubble appears: "Running 8 checks in parallel." A status list populates line by line.

**VO:**
> "Eight Opus 4.7 sub-agents run in parallel via Managed Agents. They scrape the company surface, check Companies House, cross-reference the Sponsor Register and SOC going rates, score ghost-job probability against four signals, and pull salary data from three sources. Thirty seconds. What I used to do in four hours, badly."

### [1:20–1:45] Verdict — the receipt

**Visual:** expanded verdict card: "Don't apply — this company isn't on the UK Sponsor Register." Three hard blockers listed. Citations visible as small pills.

**VO:**
> "Verdict: don't apply. Three hard blockers. Each cited to gov.uk, Companies House, or public review data. Every claim clickable. Nothing invented."

### [1:45–2:20] Salary moment — situational strategy

**Visual:** later chat — user asks "salary for that ML role I forwarded earlier" — bot responds with opening number, floor, ceiling, and exact phrasing script.

**VO:**
> "Later, for a job I'm actually considering, I ask about salary. Trajectory knows my situation — visa timeline, recent rejection count, market data for the role in London — and pitches an opening number grounded in all of it. Plus the exact words to use when the recruiter asks."

### [2:20–3:00] Live footage — real product running

**Visual:** Screen.studio capture of real Telegram bot, real pipeline. User forwards a pre-tested URL. Status list populates from live agents. Verdict arrives with real citations. Brief cut to Streamlit dashboard showing session history with clickable source data.

**No VO during this segment. Let the bot speak.**

### [2:55–3:00] Close

**Visual:** closing card — lowercase "t" mark, "Trajectory — Open source. Never auto-applies." — GitHub URL, Kene's handle.

---

## 4. Written description (150–180 words target)

```
Trajectory is a Telegram-native personal assistant for UK job seekers.
Users onboard once — career history, motivations, deal-breakers, writing
samples, urgency context — then interact in natural language. Paste a
job URL and eight Opus 4.7 sub-agents run in parallel via Managed
Agents: company scraping, Companies House, Glassdoor, Sponsor Register,
SOC going rates, ghost-job detection across four signals, and salary
benchmarking. The verdict ships with cited hard blockers and stretch
concerns — every claim links to gov.uk, the company's own page, or a
specific career entry. Never invented. On-demand, users ask for tailored
CVs, cover letters, interview questions, or salary advice. Every output
is written in the user's voice from their own samples, not AI voice.
Salary recommendations adapt to urgency — visa timeline, rejection
count, employment status — so someone running out of runway doesn't
get the same advice as someone negotiating from strength. Trajectory
explicitly never auto-applies. It tells you the truth about each job
so you spend your time on the ones worth it.
```

**Word count check:** ~175 words. Within the 100–200 range.

**Why this framing:**

| Element | Judging criterion |
|---------|------------------|
| "18 months on visa" lived-experience lede | Problem Statement 1: Build From What You Know |
| "eight Opus 4.7 sub-agents … parallel via Managed Agents" | Opus 4.7 Use (25%) |
| "every claim links to gov.uk" | Depth & Execution (20%) + genuine moat |
| "written in user's voice" | Demo (25%) — visible in video |
| "never auto-applies" | Impact (30%) — counter-positioned vs harm-amplifying alternatives |
| "someone running out of runway" | Impact — specific human framing |

---

## 5. README (repo homepage) draft

```markdown
# Trajectory

A Telegram-native personal assistant for UK job search. Grounds every claim in live
UK government data. Writes in the user's voice. Adapts to the user's situation.
Never auto-applies.

Built for Built with Opus 4.7: a Claude Code hackathon (April 2026).

## Why

Almost a third of UK job listings are ghost postings. Many more are below
sponsorship thresholds, at companies not on the Sponsor Register, or in
companies quietly circling administration. Most AI job tools make this
worse — they volume-apply, they write generic AI-voice cover letters,
they ignore the candidate's actual situation.

Trajectory is built by a UK-based AI engineer who's spent 18 months on a
Graduate visa applying to the UK market. It solves for the user type the
author is, and extends to the UK-resident market that shares most of the
same information asymmetries.

## What it does

- **Forward a job, get a verdict.** Eight Opus 4.7 sub-agents run in
  parallel via Managed Agents. They scrape, check Companies House,
  cross-reference the Sponsor Register and SOC going rates, detect
  ghost-job probability, and pull salary data from multiple sources.
  The verdict ships with cited hard blockers.
- **Ask for a CV, cover letter, interview questions, or salary advice.**
  Each is generated on demand, in the user's voice from their own samples.
- **Every claim is clickable.** Citations resolve to gov.uk, the
  company's own page, a Companies House filing, or a specific career
  entry from the user's history.
- **Salary adapts to urgency.** The recommendation accounts for visa
  timeline, recent rejection count, current employment, and search
  duration. A candidate running out of runway doesn't get the same
  advice as one negotiating from strength.
- **Never auto-applies.** The user is always in the loop.

## Stack

Python 3.11, Anthropic SDK + Managed Agents (`managed-agents-2026-04-01`),
python-telegram-bot (async long-polling), Playwright + trafilatura,
python-jobspy, pandas + pyarrow, SQLite + sqlalchemy + FAISS + sentence-
transformers, Pydantic v2, Streamlit.

No LangChain. Raw SDK + asyncio.gather for parallel fan-out.

## Running locally

```
uv sync
cp .env.example .env  # fill in ANTHROPIC_API_KEY, TELEGRAM_BOT_TOKEN,
                      # COMPANIES_HOUSE_API_KEY, RAPIDAPI_KEY
uv run playwright install chromium
uv run python scripts/fetch_gov_data.py
uv run python -m trajectory.bot.app
```

In another terminal:

```
uv run streamlit run src/trajectory/dashboard/app.py
```

## Architecture

See [ARCHITECTURE.md](./ARCHITECTURE.md).

See [CLAUDE.md](./CLAUDE.md) for the operating manual that any agent
(or human) working on this codebase should read first.

See [AGENTS.md](./AGENTS.md) for the prompt specifications of all 16
LLM-driven components.

See [PROCESS.md](./PROCESS.md) for the design decision log — the pivots,
the rejections, the reasoning.

## Licence

MIT.

## Post-hackathon roadmap

See [PROCESS.md](./PROCESS.md) §Post-hackathon roadmap.

## Author

Kene — AI/ML engineer, Manchester, UK. `kene@[...]`.
```

---

## 6. GitHub repo checklist

Before you push the submission, verify:

- [ ] Public repo
- [ ] `LICENSE` file with MIT text (full standard text, not abbreviated)
- [ ] `README.md` populated from the template above
- [ ] No secrets committed (check `.env` is in `.gitignore`; search repo for common secret prefixes)
- [ ] `CLAUDE.md`, `ARCHITECTURE.md`, `AGENTS.md`, `SCHEMAS.md`, `PROCESS.md`, `SUBMISSION.md`, `CLAUDE_DESIGN_PLAYBOOK.md` committed
- [ ] `pyproject.toml` with pinned versions
- [ ] `.env.example` showing required env vars (no real values)
- [ ] Smoke test script that runs end-to-end
- [ ] Commit history is honest — hackathon-window commits only
- [ ] No force-push on submission day to hide earlier commits
- [ ] Repo URL copied into the submission form

---

## 7. Video checklist

- [ ] Final cut <= 3:00
- [ ] Voiceover clear, paced, not rushed
- [ ] Captions burned in (accessibility + muted watching)
- [ ] Live footage segment present and clearly real (URL bar visible, timestamps visible in chat)
- [ ] Citations visible and at least one shown resolving
- [ ] No Anthropic logo, no sponsor badges
- [ ] Exported mp4, h.264, decent bitrate
- [ ] Uploaded to YouTube as unlisted
- [ ] URL tested in incognito window
- [ ] URL copied into the submission form

---

## 8. Submission form checklist

(Exact form fields may differ — fill in whatever Cerebral Valley provides.)

- [ ] Project name: `Trajectory`
- [ ] Description: paste from §4 of this document
- [ ] GitHub URL
- [ ] YouTube URL
- [ ] Problem Statement: `Build From What You Know`
- [ ] Team size: 1
- [ ] Category prize interest (if asked): `Best Managed Agents Use`
- [ ] Contact email

---

## 9. The night before — Saturday checklist

Before you go to sleep Saturday:

- [ ] End-to-end pipeline runs on a fresh fixture job URL without errors
- [ ] All 3 tests pass (citations, ghost-job combination, verdict branching)
- [ ] Telegram bot starts up cleanly with `uv run python -m trajectory.bot.app`
- [ ] Real-footage segment recorded and saved to at least 2 locations
- [ ] Voiceover recorded, best take identified
- [ ] Claude Design frames downloaded, organised by timeline position
- [ ] Known issues documented in a file so you're not firefighting Sunday
- [ ] Phone charged, laptop charged, cables located

---

## 10. Sunday schedule

| Time (BST) | Task |
|------------|------|
| 09:00 | Tea. Sit at desk. Open this doc. |
| 09:30 | Final smoke test. Fix any overnight breakage. |
| 10:00 | Start video edit in timeline editor. |
| 11:30 | Voiceover sync + captions. |
| 13:00 | Lunch break (30 min, phone away). |
| 13:30 | Colour / caption / pacing polish. |
| 14:30 | Export, watch end-to-end. |
| 15:00 | Upload to YouTube as unlisted. Test URL. |
| 15:30 | README final pass. |
| 16:00 | Written description final pass. |
| 16:30 | Open submission form. Fill every field. Screenshot draft. |
| 17:00 | Re-read video once more. Spot issues. |
| 17:30 | Submit. Take a breath. |
| 18:00 | Stop working on Trajectory. You're done. |

**Hard rule:** nothing new gets added after 14:00. From 14:00 onward, only polish and submission mechanics.

---

## 11. If medaling — Tuesday live finals

Top finalists demo live at **Tuesday 28 April 2026, 5:00 PM BST**.

Prep Monday:

- Rewatch the video once
- Prepare a 2-minute live walkthrough (no new slides; walk through the bot live)
- Anticipate 3 questions:
  1. "Why Telegram over a web app?"
  2. "How does ghost-job detection handle false positives?"
  3. "Why not auto-apply?"
- Have Trajectory running on a pre-onboarded test user, with a pre-tested job URL staged

Don't redesign anything between submission and Tuesday. The version they're judging is the version they'll ask about.

---

## 12. After submission

Whatever happens with judging — this was worth building. It's a real product addressing a real pain you have first-hand. It will be useful post-hackathon regardless of whether it medals.

Start collecting early users from the Graduate visa community on LinkedIn and Discord the week after. That audience will forgive rough edges for the specificity of what the tool does.
