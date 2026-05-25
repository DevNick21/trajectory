# Scalability Audit

```text
AUDIT LENS: Scalability

You are a principal engineer auditing whether AskPicky can scale from a local
single-user assistant to a hosted product with 10, 100, 1,000, and 10,000 users.

Do not assume the current product must become SaaS, but identify exactly where
the current design would break if that became the goal.

Evaluate scalability of:
- SQLite
- FAISS local index
- local generated files
- in-memory rate limiting
- in-memory running tasks
- SSE connections
- queue/batch processing
- scraper/browser state
- Playwright concurrency
- LLM provider throughput/quotas
- embeddings
- session progress event storage
- frontend polling
- file uploads/downloads
- Docker runtime
- migrations/backups

Trace scaling levels:
1. 1 local user
2. 10 users
3. 100 users
4. 1,000 users
5. 10,000 users

For each level, identify:
- expected bottleneck
- data isolation risk
- operational complexity
- provider quota needs
- cost profile
- architecture changes required

Look specifically for:
- hardcoded demo user assumptions
- no auth/multi-tenant boundary
- single SQLite writer bottlenecks
- FAISS index shared across users without tenant isolation
- local files as source of truth
- process-local queue state
- process-local rate limit state
- progress events without retention/partitioning
- unbounded session history
- no horizontal worker model
- no distributed locking
- no object storage abstraction
- no database migration strategy for multi-user scale
- provider quota not mapped to concurrency
- scraping concurrency likely to trigger anti-bot blocks
- SSE connection scaling limits
- no per-tenant budget/rate policies

For each finding include:
- scaling limit
- what breaks first
- user count where it likely appears
- current coupling causing it
- short-term mitigation
- target scalable design
- migration difficulty
- test/load simulation needed

Also produce:
1. Current scalability posture
2. 10/100/1,000/10,000-user roadmap
3. Data-store migration plan
4. Worker/queue scaling plan
5. File/object storage plan
6. Multi-tenant isolation model
7. Provider quota/capacity plan
8. Load-test plan
9. Scalability risk register
```
