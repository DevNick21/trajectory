# Reliability / SRE Audit

```text
AUDIT LENS: Reliability / SRE

You are a senior SRE auditing AskPicky for reliability, failure recovery, and
production readiness. Assume users will run long, expensive, interruption-prone
workflows involving scrapers, LLM calls, document generation, file uploads,
SSE streams, and background queue processing.

Your audit must focus on how the system behaves when real-world failures happen:
timeouts, retries, provider outages, process crashes, partial writes, queue
interruptions, browser scraping failures, network drops, client refreshes, and
storage failures.

Trace these reliability-critical workflows:

1. User starts forward_job from the dashboard
   - session creation
   - SSE stream open
   - progress event emission
   - progress event persistence
   - scraper/JD extraction
   - parallel Phase 1 agents
   - verdict generation
   - session update
   - frontend recovery after refresh

2. User queues multiple jobs
   - queued job insertion
   - batch processing
   - concurrency control
   - per-job session creation
   - error handling
   - progress history
   - partial completion

3. User generates artifacts
   - CV/cover letter/questions/salary flows
   - LLM call failure
   - renderer failure
   - file write failure
   - retry/regenerate behaviour
   - user navigation during generation

4. User uploads a file
   - upload read
   - parsing/extraction
   - LLM/provider failure
   - partial parsed state
   - user-visible recovery

5. System restarts during active work
   - API process dies
   - frontend SSE disconnects
   - queue task lost
   - partially written SQLite state
   - orphaned generated files
   - duplicate user submissions after retry

Evaluate:
- idempotency keys
- durable workflow state
- explicit state machines
- retry policy
- timeout policy
- cancellation behaviour
- duplicate submission handling
- orphan cleanup
- atomic writes
- transaction boundaries
- backpressure
- retry budgets
- dead-letter states
- user-visible failure states
- resume/replay ability
- degradation when non-critical agents fail
- critical vs non-critical failure classification
- readiness/liveness health checks
- safe shutdown
- startup recovery

Look specifically for:
- tasks spawned without durable ownership
- long-running work tied to request lifetime
- failures logged but not represented in domain state
- "done" states emitted before all durable writes complete
- missing terminal states for failed sessions
- retries that can double-spend LLM/provider budget
- retry loops without jitter/backoff
- lost progress events
- stale active sessions after crash
- partial sessions that look complete
- sessions with verdict but missing research bundle
- research bundle saved without source status
- queue jobs stuck in processing forever
- frontend polling that hides backend failure
- generated files written without manifest/state
- document generation that can leave mixed old/new outputs
- SQLite busy errors under concurrent writes
- FAISS/SQLite divergence
- silent fallbacks that lower answer quality without surfacing uncertainty

For each finding include:
- reliability failure mode
- trigger condition
- affected user workflow
- current state before failure
- current state after failure
- what the user sees
- what operators can see
- data consistency risk
- cost/spend risk
- recommended immediate mitigation
- recommended target design
- test case to reproduce

Also produce:
1. Reliability architecture map
2. Workflow state-machine gaps
3. Crash recovery matrix
4. Retry/idempotency design proposal
5. Queue/worker/process separation recommendation
6. SLO proposal for core flows
7. Synthetic monitoring plan
8. Incident runbook outline
9. Prioritised hardening roadmap
```
