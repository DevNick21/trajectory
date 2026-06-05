# Memory Architecture

AskPicky's public engine keeps memory local, auditable, and user-controlled.
The memory system exists to make application advice evidence-backed without
turning generated text into trusted history.

## Goals

- Store user-provided career evidence with provenance.
- Retrieve relevant evidence for job analysis, application answers, CVs, and
  interview preparation.
- Separate confirmed evidence from inferred or generated material.
- Let the user export, correct, or delete memory items.
- Keep local/self-hosted operation simple.

## Local Storage

The public engine uses:

- SQLite for structured records.
- FAISS for local vector retrieval.
- Local files under `data/` for generated artefacts.

The default identity is a single local user configured by `DEMO_USER_ID`.
Every persisted row still carries `user_id` so the same schema can support
tests, fixtures, and future self-hosted deployments with explicit identities.

## Core Tables

Important memory tables live in `packages/engine/src/askpicky/storage.py`:

- `user_profiles`
- `career_entries`
- `application_assist_sessions`
- `answer_attempts`
- `experience_atoms`
- `story_frames`
- `memory_edges`
- `advice_snippets`
- `application_tracker`
- `security_audit_events`

`application_tracker` is manual-only in the public engine. A forwarded job can
create a tracker row, and the user can update the application outcome.

## Evidence States

Application generation should prefer evidence that is:

- user-provided
- parsed from a CV
- confirmed during review
- approved after an assist workflow

Generated or inferred content should not become trusted evidence unless the user
approves it. This is enforced through review states on memory items and through
the application-assist approval flow.

## Retrieval

Retrieval combines:

- local embeddings for career entries and memory suggestions
- structured metadata such as memory kind, review status, visibility, and
  source id
- question type and JD context during application assist

The retrieval layer should return traceable memory candidates, not anonymous
semantic matches. Downstream generators need enough context to cite or explain
why evidence was selected.

## Application Assist

The assist workflow is:

1. Start an assist session with optional JD context.
2. Suggest relevant memory for a specific application question.
3. Critique the user's draft for missing evidence and structure.
4. Polish the answer without inventing claims.
5. Save approved memory candidates only after explicit user approval.

The Chrome companion calls the same local API endpoints as the web app.

## Privacy Controls

The public engine keeps privacy controls close to the core schema:

- export memory
- delete memory item
- hard-delete answer attempt raw text after retention
- redact sensitive values from logs
- persist security audit events for sensitive local actions

Raw answer drafts are time-limited by `raw_retention_until`. The deterministic
memory extractor runs conservatively; the LLM-backed extractor is optional and
off unless `ENABLE_MEMORY_EXTRACTOR_LLM=true`.

## Boundaries

The public memory layer deliberately does not include:

- account auth
- remote storage adapters
- cross-user analytics
- email ingestion
- reminder delivery
- usage metering

Those concerns should stay outside the open engine unless they become part of a
separate, explicit deployment layer.
