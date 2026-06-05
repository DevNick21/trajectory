# Public Monorepo Architecture

AskPicky is now organised as an open-core monorepo.

```text
apps/api        thin FastAPI app boundary
apps/web        React/Vite user interface
apps/extension  optional localhost-only browser companion
packages/engine compatibility FastAPI/application package
packages/core   shared public schemas/types
packages/parsers deterministic public parsers
packages/evaluators deterministic public evidence/claim evaluators
packages/privacy local export/delete and privacy metadata
packages/ai     provider abstraction for BYOK/local models
infra/docker    Docker runtime files
infra/local     local runtime scaffolding
examples        sample inputs and traces
tests           regression tests
scripts         repository tooling
```

The public engine owns job analysis, profile/CV parsing, evidence matching,
claim support checking, manual tracking, local storage, privacy export/delete,
provider abstraction, and audit traces.

Do not add hosted billing, dedicated email infrastructure, managed model
routing, production abuse systems, hosted analytics, admin dashboards, or
team/coach features to this public tree.
