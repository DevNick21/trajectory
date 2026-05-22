# Trajectory — Strategic Direction Notes

*Captured from conversation. Thinking document, not a spec. Decisions still open.*

---

## TL;DR

Reposition Trajectory from **"AI does your application"** to **"system of record for your job search + verify roles before you waste research on them."** A user-reported employer-behaviour data network powers the premium tier. Free tier feeds the flywheel; premium captures high-leverage moments. Open-core moat is the data, not the code.

---

## 1. Strategic repositioning

- **From**: AI-cited applications, anti-volume-apply, visa-aware
- **To**: Trajectory researches, applies, tracks, and learns from outcomes. The more people use it, the better it gets at telling you whether a role is worth your time
- **Wedge stays**: anti-volume-apply, visa-aware UK specialism, no auto-apply
- **What's new**: outcome tracking + employer behaviour data as a closed-network moat

---

## 2. The data flywheel (core mechanic)

User reports outcomes via one-tap in Telegram → aggregated into employer-behaviour micro-database → served back as premium pre-application benchmarks.

- **Asymmetric value**: free to contribute (one tap), hours saved to consume
- **Precedent**: Levels.fyi did this for compensation. There's no equivalent for hiring behaviour (response rate, interview-to-offer ratio, ghost frequency, time-to-response)
- **Why it bypasses the spam paradox**: Trajectory isn't claiming anything about applicants. It's letting users tell each other what employers actually do. Employers can't game it because they don't control the data — the network of candidates does

---

## 3. Open-core architecture

| Layer | Open / Closed |
|---|---|
| Agent code, Telegram UX, schemas, verification UI | OSS (AGPL — already in place) |
| **Aggregated employer behaviour database** | **Closed — the network-effect moat** |
| Hosted continuous monitoring (compute layer) | Paid SaaS |
| Anonymised market data licensing (future) | Future paid tier |

Code is forkable. Data network isn't. **Let's Encrypt model**: open code, centrally operated trust authority.

CLA + AGPL-3.0 already in place. No licensing changes needed for this direction.

---

## 4. Freemium architecture

### Free tier (expanded beyond hackathon scope)

| Feature | Why free |
|---|---|
| Visa eligibility check | Conversion driver — front-page tool |
| Sponsor register search (better UX than gov.uk) | Existing wedge, can't gate |
| Basic 9-agent role research (rate-limited, e.g. N/month) | Core product |
| Application drafting + cited CV/cover letter | Existing core |
| Personal application tracker + follow-up reminders | Why users stay between job searches |
| Outcome reporting (one-tap) | Feeds the data network — non-negotiable free |
| Sponsor licence change alerts on saved roles | Visa-aware retention hook |
| Tailored CV version management | Low compute, high value |

### Premium tier (focused — 4 features, not 14)

| Feature | Why pay | Compute cost |
|---|---|---|
| **Pre-application employer benchmarks** | Save hours on the wrong applications | Low (DB lookup) |
| **Real-time hiring intent verification** | Live 9-agent check: is this a ghost job, recycled posting, dead team? | High |
| **Salary defensibility for visa roles** | Home Office going rate + new entrant threshold + 25th percentile check — niche, high-value, nobody else does it | Medium |
| **Application autopsy after rejection** | Your app + employer's hiring pattern + comparable user outcomes → what likely missed | High |

**Salary defensibility is the strongest unique angle.** Visa specialism creates a moat no general tool can copy. Willingness-to-pay is high (cost of a bad sponsorship offer is the visa itself).

---

## 5. Pricing model

Job searches aren't permanent — pure subscription is the wrong model for the audience.

| Path | What you get |
|---|---|
| **Free** | Basic tier + N free premium features/month |
| **Contribute** | Report outcomes consistently → earn credits → spend on premium |
| **Pay-as-you-go** | Credit packs, no commitment |
| **Subscription** | Heavy users, unlimited, quality-of-life perks |

The contribute-to-earn track aligns incentives: heavy contributors stay free, casual users pay, both feed the database.

---

## 6. Sister product candidate: Trajectory Interview

Don't bundle into Trajectory's premium tier — it's a different product.

- **Separate surface** (probably not Telegram — interactive simulation needs more UI)
- **Different usage pattern** (intensive bursts pre-interview)
- **Industry analysis**: "most underused AI capability in 2026" is pre-interview research on hiring manager + company news + role pain points
- **Personal motivation**: JPMC + HMLR rejections both had interview-prep gaps (explaining ML models to different audiences; STAR delivery against Civil Service Success Profiles)
- **Trajectory's research depth makes this differentiated** from generic AI mock-interview tools

---

## 7. The reporting UX (critical constraint)

If reporting takes more than one tap inside the existing Telegram flow, the data dies. Hard rule.

```
Day 21 after application:
Bot:  "Any update on Acme Senior ML Engineer?"
User: [No response] [Rejected] [Interview] [Offer]
Bot:  [if Interview] "Scheduled within 2 weeks of applying? Yes / No"
```

No forms. No dashboards in v1. Data extraction has to feel like the existing assistant being helpful.

---

## 8. Operational risks & mitigations

| Risk | Mitigation |
|---|---|
| **Selection bias**: hired users stop reporting, ghosted over-report | Smart-timed nudges, gamify completion, accept that benchmarks are *Trajectory-relative* and label honestly |
| **User base not representative of all applicants** | Frame as "among applicants who did Trajectory-level research" — feature not bug |
| **Adversarial reporting** (fake outcomes) | Light verification (interview email subject, recruiter first name, date), cross-reference across users, downweight outliers |
| **GDPR** on individuals | Aggregate company-level data publicly; named individuals (recruiters, HMs) only if public/consenting |
| **Defamation exposure** ("Acme has 5% response rate") | Methodology transparency, sample size visible, takedown process, invite-to-comment from named employers |
| **Cold start**: data is noise until ~1,000 users | Premium benchmark feature is a v2 monetization layer; free tier must carry the product for 12–18 months |
| **Long-tail employer coverage gap** | Be honest in UI: "Insufficient data" not silent absence |

---

## 9. What's been ruled out (and why)

| Ruled out | Why |
|---|---|
| Identity-verification badges | CLEAR/Sardine territory; different problem |
| AI-content detection on applications | Adversarial, unwinnable, contradicts using AI |
| Citation packet as trust badge | Spam paradox: any "I'm not spam" signal becomes spam |
| Employer ATS/sourcing product | Different sales motion, solo founder can't pull off |
| "Verify the employer" dossier directory | Sponsor register lookup with extra steps |
| OSS triage agent for employers | Jack & Jill / general ATS territory |
| Forcing Open\* naming for OpenClaw aesthetic alignment | Generic Open + path/journey words mostly taken (OpenPath, OpenScout, OpenLane). OpenClaw lesson: second word must be unusual, not a dictionary word. Strongest indie OSS-commercial products don't use Open\* (Cal.com, Plausible, Supabase, PostHog) |

---

## 10. Naming decision — parked

- "Trajectory" actually maps onto the new positioning better than the Open\* alternatives we explored
- Demo is shipped, no time pressure
- Revisit only if a clearly stronger name emerges or there's a brand-collision issue

---

## 11. The honest test

For each premium feature: **"Would I have paid £5–15 for this at the moment I needed it during my own job search?"**

- Ghost job check before OnBuy.com / Prolynk: **probably yes**
- Salary defensibility for TalkTalk FTC: **yes — exactly that analysis was needed**
- Application autopsy after JPMC (the "explaining ML models" miss): **maybe — would have informed HMLR prep**
- Benchmark on AXA Manchester before applying: **yes, if data existed**

If 2 of 4 are "yes" → model holds. Currently 3 of 4.

---

## 12. Open questions to revisit

1. Is the data network a moat or chicken-and-egg trap?
2. Does this dilute or strengthen Trajectory's existing core?
3. Is this a new product or a layer inside Trajectory?
4. What ships in v1 before the data network is meaningful?
5. Does this change the rename decision?
6. Should reporting be opt-in or opt-out (default to nudge)?
7. Credit pricing model: how many credits per premium feature, how many credits per outcome report?
8. Does Trajectory Interview share an account / brand with Trajectory or stand alone?

---

## 13. What's next (when ready to think more)

Pick any of:

1. Spec the 4 premium features properly (what each ships with at v1)
2. Map the pricing model — exact credit costs, contribution rewards, subscription tiers
3. Pressure-test the free tier — what's missing, what's bloated
4. Define the v1 launch scope before data exists
5. Talk through Trajectory Interview as a sister product
6. Revisit naming with the new positioning in hand
