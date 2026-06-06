# AskPicky

> **A job application operating system for serious active applicants.**
> Paste a job description, see hard filters, match the role against your real
> evidence, generate safer application answers, and track what happens next.

Python 3.12+ · FastAPI · Vite/React · DeepSeek + OpenAI model tiers ·
Open-core engine · No auto-apply, ever.

---

## What It Does

**Analyses jobs before you apply.**
AskPicky extracts the role, seniority, salary, location, required skills,
hard filters, company status, ghost-job signals, and visa/SOC constraints where
relevant.

**Matches the job to actual evidence.**
It compares job requirements against CV/profile/memory evidence, shows what is
supported, what is missing, and which claims would be unsafe to make.

**Coaches before it writes.**
The application-assist loop critiques drafts, retrieves approved evidence,
shapes final answers, and flags unsupported claims before the user copies
anything.

**Tracks applications as the central entity.**
The tracker records roles, statuses, evidence, generated answers, deadlines,
and outcomes.

**Keeps the user in control.**
AskPicky never auto-submits. Sensitive fields require confirmation. Memory is
provenance-backed and user-scoped.

---

## Public Strategy

The public repository documents and develops the inspectable engine:

- job analysis
- CV/profile parsing
- candidate and application schemas
- evidence matching
- claim support checking
- basic answer generation
- manual tracker
- local database support
- AI provider abstraction
- BYOK/local model path
- export and delete controls
- audit traces and evaluation examples

Managed-service implementation details, packaging, rollout plans, and commercial
roadmaps are deliberately not maintained in tracked public files.

The active public product definition lives in [ASKPICKY.md](./ASKPICKY.md).
Agent prompts and routing live in [AGENTS.md](./AGENTS.md).

---

## Repository Layout

```text
apps/
  api/          # thin FastAPI app boundary
  web/          # React/Vite app
apps/extension  # optional low-permission browser companion
packages/
  engine/       # FastAPI application package
  core/         # shared public schemas/types
  parsers/      # deterministic JD/CV/application parsers
  evaluators/   # deterministic claim/evidence evaluators
  privacy/      # export/delete and local privacy primitives
  ai/           # provider abstraction for BYOK/local model adapters
infra/
  docker/       # Docker runtime files
  local/        # local-only runtime scaffolding
docs/           # public architecture, privacy, API, and self-hosting docs
examples/       # sample CV/JD/workflow/trace fixtures
tests/          # Python regression tests
scripts/        # repository tooling and smoke tests
```

---

## First Useful Workflow

```text
Paste job description
  -> role breakdown
  -> hard filters
  -> evidence match
  -> application priority
  -> suggested answer strategy
  -> optional CV upload/profile save
  -> application tracking
```

Do not require a large profile, API-key setup, browser extension, or inbox
access before first value.

---

## Analysis Checks

| Check | What it catches |
|---|---|
| JSON-LD pre-LLM extractor | Avoids an LLM call when the page exposes Schema.org JobPosting. |
| JD extractor | Structured role fields, requirements, salary, location, seniority, and vagueness signals. |
| Ghost-job detector | Stale posting, missing careers-page signal, vague JD, and distress patterns. |
| Sponsor Register | Whether the employer holds a Skilled Worker licence for visa holders. |
| SOC threshold | Whether salary clears going-rate constraints where relevant. |
| Companies House | Dissolution, administration, overdue filings, wind-up signals. |
| The Gazette | Insolvency notice signals. |
| Red flags | Layoffs, lawsuits, regulatory actions, review patterns, and other candidate risks. |
| Company investigation | Bounded, best-effort company context for verdict reasoning. |

The verdict agent reasons over the bundle with citation validation and source
status warnings. Advisory company research failures should degrade gracefully,
not crash the session.

---

## Run It Locally

```bash
# Backend
python -m venv .venv && . .venv/bin/activate    # or .venv\Scripts\activate on Windows
pip install -e .
pip install -r requirements.txt

# Fetch UK gov data
python scripts/fetch_gov_data.py

# Copy .env.example to .env, enable local mode for deterministic first-run use
cp .env.example .env
# Set ASKPICKY_LOCAL_MODE=1 for self-hosted mode without managed AI credentials.

# Web frontend
cd apps/web && npm install && npm run dev

# Backend (in another shell)
uvicorn askpicky.api.app:app --reload --port 8000
```

---

## Smoke Tests

```bash
# Cheap suite, no live LLM calls
python -m scripts.smoke_tests.run_all --cheap

# Local self-host path only
python -m scripts.smoke_tests.run_all --only self_host_local

# Application-assist memory/API contract only
python -m scripts.smoke_tests.run_all --only application_memory,api_assist,api_contract

# Extension detector fixtures
npm run --prefix apps/extension test

# Full live suite
python -m scripts.smoke_tests.run_all
```

Each LLM-backed test honours `SMOKE_<NAME>_MOCK=1` for free iteration.

---

## Public Scope Boundaries

- Auto-apply or auto-submit
- Managed-service implementation details
- Managed-service packaging or rollout notes
- Inbox or platform integration roadmaps
- Autonomous ATS autofill
- Employer-facing ATS or recruiter tooling

---

## Docs

- [ASKPICKY.md](./ASKPICKY.md) — public product definition
- [AGENTS.md](./AGENTS.md) — agent prompt inventory and adapter assignments
- [MEMORY_ARCHITECTURE.md](./MEMORY_ARCHITECTURE.md) — application-assist memory graph, privacy, API, and tests
- [ASKPICKY_AUDIT_EXPORT.md](./ASKPICKY_AUDIT_EXPORT.md) — public audit export

---

## Licence Note

This repository currently includes an AGPL-3.0 licence file. Public release
scope and managed-service boundaries should be decided outside tracked public
docs before any broad launch.
