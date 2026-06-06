# AskPicky — Public Product Definition

This tracked product definition covers the open/local engine and public
workflow. Managed-service implementation details, packaging, and rollout notes
stay outside tracked public files.

Agent prompts and routing live in [`AGENTS.md`](./AGENTS.md). Memory design
lives in [`MEMORY_ARCHITECTURE.md`](./MEMORY_ARCHITECTURE.md). Implementation
docs live under `docs/architecture`, `docs/api`, `docs/privacy`, and
`docs/self-hosting`.

---

## 1. What AskPicky Is

AskPicky is a job application operating system for serious active jobseekers.

It helps a user decide whether a role is worth applying to, identify hard
filters, match job requirements to real evidence, generate safer application
answers, track applications, and learn from outcomes.

The public repository should prove the engine:

- job analysis
- CV/profile parsing
- evidence matching
- claim support checking
- local memory
- manual tracking
- user-controlled export/delete
- auditability
- BYOK/local model path

Managed-service implementation details are not part of the tracked public
product definition.

---

## 2. Product Boundaries

- The MVP centers job analysis, evidence-backed answers, and manual tracking.
- The first-run flow gives value before API-key setup, local infrastructure,
  browser extension setup, inbox access, or a full profile.
- The user reviews every generated answer and every sensitive-field decision.
- The product never auto-submits applications.
- The public engine serves applicants, with no recruiter, ATS, employer, AI
  detection, identity-verification, or candidate-badge workflow.
- The product gives decision support and safer drafting, with no guarantee of
  interviews, offers, sponsorship, or recruiter replies.

---

## 3. Product Principles

Every feature should pass these checks:

1. **Fast value** — does the user get useful signal before doing admin work?
2. **Evidence first** — does it show matched evidence, missing evidence, and
   unsupported claims?
3. **Application centrality** — does it improve the application entity,
   tracker, history, or answer workflow?
4. **Trust** — can the user inspect why the system recommended something?
5. **User control** — can the user review, correct, export, and delete data?
6. **Risk control** — does it avoid hallucination, data leakage, platform
   dependency, and automation mistakes?

Anything that makes the product feel like extra work should be cut, delayed, or
made optional.

---

## 4. Default User Workflow

The default path is:

1. Paste a job description or URL.
2. Get role breakdown.
3. See hard filters.
4. See matched and missing evidence.
5. Get application priority.
6. Get suggested answer strategy.
7. Upload CV only when needed.
8. Save application.
9. Track progress manually.

Do not require a large profile, API-key setup, local infrastructure, browser
extension, or inbox access before first value.

---

## 5. Core Workflow

### Job Analysis

The MVP workflow is:

```text
Paste job description
  -> structured JD extraction
  -> hard filter detection
  -> evidence matching
  -> application priority
  -> answer strategy
```

The system should show:

- role title, seniority, salary, location, required skills, and key
  requirements
- hard blockers such as salary floor, sponsor/SOC mismatch, deal-breakers,
  ghost-job signals, and company status
- evidence matches from CV/profile/memory
- missing evidence
- unsupported-claim warnings
- recommended answer angle
- clear uncertainty where sources are weak

### Application Assist

AskPicky coaches before it writes:

1. classify the question
2. retrieve approved evidence
3. critique the user draft
4. shape the final answer
5. mark supported and unsupported claims
6. save approved memory only with clear provenance

### Tracker

The tracker is the system of record:

- company
- role
- job URL
- priority
- status
- CV version
- answers used
- deadlines
- reminders
- recruiter interactions
- outcome

### Extension And Integrations

Browser or inbox integrations are accelerators, not the product foundation.
They must never be required for first value and must never auto-submit on the
user's behalf.

Detailed implementation and rollout notes for managed integrations are not kept
in tracked public docs.

---

## 6. Public Open-Core Boundary

The public repository should include:

- web app shell for local use
- local backend API
- job analysis workflow
- CV parsing workflow
- candidate profile structure
- evidence matching engine
- claim support checker
- basic answer generation
- manual application tracker
- local database schema
- AI provider abstraction
- BYOK support
- local model support
- export/delete controls
- basic audit traces
- basic evaluation examples

Tracked public files describe the open/local engine boundary. Managed-service
implementation details, roadmap sequencing, infrastructure design, and
packaging stay outside the public repo.

---

## 7. Trust And Evidence Rules

The product must make the difference from a generic chatbot visible.

Every important recommendation should expose:

- matched job requirement
- supporting user evidence
- missing evidence
- confidence level
- suggested action
- unsupported claims
- source of evidence

Do not use fake precision. Avoid claims like:

```text
You have a 72% chance of interview.
```

Use grounded priority language instead:

```text
Application priority: Worth applying with tailoring.

Reason:
- strong match on Python, NLP, and model evaluation
- weaker match on production deployment
- no confirmed evidence for AWS experience
- recommended angle: emphasise MSc AI project and portfolio work
```

Generated answers should only use trusted evidence:

- confirmed
- user-provided
- parsed from CV and reviewed
- manually approved

Untrusted states require review:

- inferred
- generated
- expired
- rejected
- needs review

Every generated claim should be labelled:

- supported
- partially supported
- unsupported
- user confirmed after generation
- removed

---

## 8. Privacy And Compliance

AskPicky handles sensitive personal and employment-related data.

Sensitive data may include CVs, addresses, phone numbers, salary expectations,
visa status, right-to-work status, disability disclosures, ethnicity/gender
questions, criminal history questions, recruiter emails, interview links, offer
details, and rejection history.

Required primitives:

- export user data
- delete user data
- delete application
- delete CV
- delete interaction history
- forget memory item
- disable AI memory
- consent logs
- purpose limitation
- user-scoped embeddings
- no raw sensitive content in logs
- no training on user data by default
- short-lived signed URLs
- strict user and data scoping
- isolated cache keys where shared infrastructure is used

The privacy model should be inspectable because privacy is part of the trust
surface.

---

## 9. Retention Model

Retention is event-based. A successful user may leave after finding a job, and
that is expected.

The product should optimise for return within an active search cycle and
reactivation in later cycles.

Useful metrics:

- job descriptions analysed per active user
- applications saved
- generated answers used
- applications tracked to outcome
- return rate within the same job-search cycle
- conversion from first analysis to saved application
- reactivation during a later job-search cycle

Churn before first value is the primary retention risk.

---

## 10. Highest-Risk Failures

1. Users churn before getting value.
2. Product feels like extra work.
3. Product is not clearly better than a chatbot plus a spreadsheet.
4. AI invents or exaggerates user experience.
5. User data leaks.
6. Automation touches sensitive fields incorrectly.
7. Job/company analysis is wrong or generic.
8. Memory becomes stale or contaminated.
9. Outcome analytics creates misleading conclusions.
10. Compliance controls are added too late.
11. Platform integrations become a distraction.
12. Product becomes too slow.
13. Poor observability makes failures hard to debug.
14. The public repo exposes private managed-service strategy.

---

## 11. Mitigation Principles

- optimise for fast first-session value
- narrow the behavioural wedge
- make application the central entity
- keep the web app useful without integrations
- use evidence-backed generation
- show supported and unsupported claims
- require confirmation for sensitive fields
- avoid auto-submit
- use progressive onboarding
- use memory provenance
- version profile, CV, job, prompt, model, and retrieval config
- use strict user_id scoping
- enforce strict user and data scoping where applicable
- use user-scoped cache keys
- log metadata, not raw sensitive content
- provide delete/export controls
- use rate limits and cost tracking where shared resources exist
- cache expensive AI calls
- treat outcome patterns as pattern detection, not causality
- build manual fallback paths
- use feature flags and kill switches
- keep managed-service details outside tracked public docs

---

## 12. Documentation Rules

1. Keep `ASKPICKY.md` as the active public product map.
2. Keep `AGENTS.md` scoped to prompt inventory and active routing notes.
3. Do not add tracked docs that enumerate managed-service features,
   infrastructure, packaging, or rollout sequencing.
4. Historical docs may retain old positioning only if clearly archival and not
   linked as active product strategy.

---

## 13. Final Principle

AskPicky's strongest form is a structured job application operating system
where AI acts on verified user evidence, job requirements, application history,
and tracked outcomes.

The MVP proves:

**Can AskPicky help serious active applicants decide which roles are worth
applying to and produce stronger, evidence-backed applications faster than their
current workflow?**
