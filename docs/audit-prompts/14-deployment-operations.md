# Deployment / Operations Audit

```text
AUDIT LENS: Deployment / Operations

You are a production operations engineer auditing AskPicky's deployability,
runtime safety, configuration, secret handling, migrations, backups, and
operational runbooks.

Audit the system as it would run outside a developer laptop.

Inspect:
- Dockerfile
- docker-compose files
- frontend nginx config
- environment variables
- .env examples
- settings/config validation
- startup paths
- health endpoints
- database initialization
- FAISS/index files
- generated file directories
- browser state/cookies
- logs
- CI workflows
- benchmark workflows
- scripts/smoke_tests
- dependency files

Evaluate:
- process separation
- API vs worker vs scheduler
- container user/permissions
- read-only filesystem feasibility
- volume layout
- secret injection
- env validation
- migrations
- backups/restores
- health/readiness/liveness checks
- startup ordering
- graceful shutdown
- restart behaviour
- log routing
- TLS/proxy assumptions
- frontend/backend origin config
- CORS configuration
- dependency installation
- build reproducibility
- rollback strategy
- disaster recovery
- local/dev/prod environment split

Look specifically for:
- secrets in local files or build context
- prod startup allowed with missing critical config
- single process doing API + long-running work
- no worker/scheduler split
- containers running as root
- local SQLite/FAISS paths unsuitable for prod
- no migration command/versioning
- no backup/restore documented
- no volume encryption guidance
- browser cookie state persisted without lifecycle policy
- health endpoint too shallow
- no readiness distinction from liveness
- no graceful shutdown of active tasks
- no deployment checklist
- no incident/rollback procedure
- no resource limits
- no concurrency/env tuning
- no observability export configuration
- frontend build artifacts not clearly served/versioned

For each finding include:
- operational failure scenario
- affected deployment component
- current config/behaviour
- blast radius
- recommended immediate fix
- target production setup
- verification command/check

Also produce:
1. Current deployment architecture
2. Target deployment architecture
3. Environment variable/secrets matrix
4. Volume/data lifecycle plan
5. Migration/backup/restore plan
6. Health check design
7. Process separation plan
8. Production deployment checklist
9. Runbook/incident response outline
10. Rollback strategy
```
