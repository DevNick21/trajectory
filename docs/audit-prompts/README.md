# AskPicky / Trajectory Audit Prompt Pack

Use these prompts as standalone audit briefs for AskPicky / Trajectory. Each
prompt is intentionally deep and evidence-based: the auditor should inspect the
actual codebase, configuration, frontend, tests, docs, deployment files, and
runtime assumptions before making claims.

## How to use

1. Start with [`00-shared-base-protocol.md`](./00-shared-base-protocol.md) — this
   sets the audit method, output format, and system context all lens prompts
   reference.
2. Pick the lens file relevant to your audit. Each lens file expects the base
   protocol to be prepended before running the audit.

## Available lenses

| # | Lens | File |
|---|------|------|
| 1 | Reliability / SRE | [`01-reliability-sre.md`](./01-reliability-sre.md) |
| 2 | LLM Quality & Evaluation | [`02-llm-quality.md`](./02-llm-quality.md) |
| 3 | Prompt Injection / AI Safety | [`03-prompt-injection.md`](./03-prompt-injection.md) |
| 4 | Product / UX | [`04-product-ux.md`](./04-product-ux.md) |
| 5 | Domain Logic | [`05-domain-logic.md`](./05-domain-logic.md) |
| 6 | Data Privacy | [`06-data-privacy.md`](./06-data-privacy.md) |
| 7 | Cost / FinOps | [`07-cost-finops.md`](./07-cost-finops.md) |
| 8 | Performance | [`08-performance.md`](./08-performance.md) |
| 9 | Scalability | [`09-scalability.md`](./09-scalability.md) |
| 10 | Test Coverage | [`10-test-coverage.md`](./10-test-coverage.md) |
| 11 | Maintainability / Code Quality | [`11-maintainability.md`](./11-maintainability.md) |
| 12 | Observability | [`12-observability.md`](./12-observability.md) |
| 13 | API Contract | [`13-api-contract.md`](./13-api-contract.md) |
| 14 | Deployment / Operations | [`14-deployment-operations.md`](./14-deployment-operations.md) |
| 15 | Accessibility | [`15-accessibility.md`](./15-accessibility.md) |
| 16 | Legal / Compliance | [`16-legal-compliance.md`](./16-legal-compliance.md) |
