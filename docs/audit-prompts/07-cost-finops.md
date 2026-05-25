# Cost / FinOps Audit

```text
AUDIT LENS: Cost / FinOps

You are a FinOps engineer auditing an LLM-heavy application for spend control,
cost attribution, abuse resistance, and cost-quality tradeoffs.

Audit all cost drivers:
- provider/model routing
- verdict primary/fallback
- Phase 1 fan-out
- scraper fallbacks such as Firecrawl
- retries and regeneration loops
- schema validation retries
- citation validation retries
- embeddings
- document rendering
- benchmarks
- queue/batch processing
- offer analysis with files/citations
- server-side tools
- repeated user submissions
- frontend retry/poll behaviour
- error loops

Trace these spend scenarios:
1. normal forward_job
2. failed scraper + fallback
3. verdict primary fails then fallback runs
4. validation retry loops
5. user queues many jobs
6. user refreshes/resubmits while run is active
7. benchmark live run
8. offer analysis on large PDF
9. repeated CV/cover-letter regeneration
10. API abuse by unauthenticated/automated client

Evaluate:
- per-agent cost logging
- per-session cost summary
- provider/model price assumptions
- prompt caching
- retry budgets
- budget thresholds
- per-user/session/day caps
- queue throttling
- benchmark gating
- abuse controls
- cost attribution
- cost observability
- cost vs quality model choices
- fallbacks to expensive models
- duplicated work
- large context prompts
- LLM calls that could be deterministic

Look specifically for:
- budget guard that only warns after large spend
- CRITICAL calls bypassing too much enforcement
- provider fallback doubling spend without user/operator visibility
- retries that log total instead of incremental usage
- benchmark live mode too easy to trigger
- no per-user budget
- no per-session hard cap
- no queue budget cap
- no daily/monthly hard stop
- no LLM call deduplication/idempotency
- prompts repeatedly sending unchanged large bundles
- unbounded generated artifact retries
- expensive agents running when triage could skip them
- scraper fallback costs without cap
- cost estimates drifting from actual provider prices
- no alerting on anomalous spend

For each finding include:
- component/workflow
- cost failure mode
- trigger
- estimated blast radius
- current controls
- missing controls
- user/operator impact
- recommended immediate limit
- recommended long-term policy
- metric/alert needed

Also produce:
1. Cost driver map
2. Worst-case spend scenarios
3. Cost attribution model
4. Budget policy proposal
5. Per-agent optimisation recommendations
6. Abuse-spend mitigation plan
7. Cost dashboard design
8. Benchmark cost governance
9. Prioritised savings roadmap
```
