# Observability Audit

```text
AUDIT LENS: Observability

You are an observability architect auditing whether AskPicky can be debugged,
operated, and trusted in production.

The core question: when a user says "the verdict was wrong" or "the job got
stuck", can engineers reconstruct what happened without leaking private data?

Evaluate observability for:
- request logs
- structured logs
- correlation/request IDs
- session IDs
- workflow timelines
- progress events
- agent-level telemetry
- model/provider metadata
- prompt/schema version metadata
- token/cost usage
- retry counts
- validator failures
- scraper failures
- source truncation
- storage errors
- queue events
- frontend errors
- SSE lifecycle
- generated artifact lifecycle
- notification delivery
- benchmark runs
- privacy-safe redaction

Trace debug scenarios:
1. forward_job hangs
2. verdict contradicts hard blocker
3. source citation does not resolve
4. provider fallback triggered
5. LLM spend spikes
6. scraper returns wrong company
7. user refreshes and sees stale progress
8. queue job stuck in processing
9. file upload parse fails
10. generated CV contains unsupported claim
11. notification not delivered
12. benchmark result regresses

Look specifically for:
- logs without correlation IDs
- exception text returned to user but not structured for operators
- sensitive data in logs
- no trace spanning frontend/API/orchestrator/agents/storage
- no prompt/model version stored with output
- no visibility into fallback vs primary route
- no metric for validation retry failures
- no metric for citation validation failures
- no scraper source-quality metrics
- no queue lag/age metrics
- no active session/generation metrics
- no p95 latency/cost dashboard
- no alerting on stuck jobs
- no alerting on provider errors
- no audit trail for user data changes
- progress event history not connected to operational traces

For each finding include:
- missing signal
- debugging scenario that currently fails
- affected component
- privacy concern
- recommended log/metric/trace
- label/cardinality guidance
- alert threshold
- dashboard panel

Also produce:
1. Observability signal inventory
2. Missing trace model
3. Required metrics
4. Required structured logs
5. Privacy-safe redaction policy
6. Production dashboard design
7. Alerting/runbook proposal
8. User support/debug workflow
9. Instrumentation roadmap
```
