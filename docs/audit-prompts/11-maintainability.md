# Maintainability / Code Quality Audit

```text
AUDIT LENS: Maintainability / Code Quality

You are a staff engineer auditing AskPicky for maintainability, modularity,
change safety, readability, coupling, and long-term engineering quality.

Assess whether a new contributor can safely change the system, add an agent,
modify a workflow, update a prompt/model, alter an API shape, or refactor the
frontend without causing hidden regressions.

Evaluate:
- module boundaries
- dependency direction
- orchestration ownership
- API route size/responsibility
- storage abstraction
- schema ownership
- prompt ownership
- LLM backend abstraction
- validator placement
- frontend component boundaries
- type safety
- config sprawl
- naming consistency
- duplicated logic
- dead code
- comments/docstrings quality
- error handling consistency
- testability
- hidden global state
- migration safety
- generated artifacts in repo
- tool/runtime assumptions

Trace change scenarios:
1. Add a new sub-agent
2. Change verdict schema
3. Add a new provider
4. Add a new generated artifact
5. Add multi-user auth
6. Replace SQLite
7. Change SSE event contract
8. Update frontend verdict display
9. Add a new onboarding field
10. Change salary/SOC logic

Look specifically for:
- business logic spread across routes, handlers, orchestrator, storage, and agents
- stringly typed state/event names
- duplicated emitter persistence wrappers
- implicit schema compatibility between Python and TypeScript
- large files with multiple responsibilities
- mixed sync/async patterns
- global settings mutated in tests
- lack of interfaces around storage/providers/renderers
- imports that create startup side effects
- untracked prompt/model version coupling
- doc drift between AGENTS.md, config, code, tests, and skills
- frontend components knowing backend internals
- repeated API fetch/error handling code
- hardcoded model/provider names in comments/tests
- local/demo assumptions embedded in reusable modules
- fragile relative paths and filesystem conventions

For each finding include:
- affected files
- maintainability risk
- change scenario that would break
- current coupling
- recommended refactor
- migration path
- tests to protect the refactor

Also produce:
1. Codebase maintainability diagnosis
2. Module boundary map
3. Coupling hotspots
4. Refactoring seams/interfaces to introduce
5. Naming/state/event standardisation proposal
6. Prompt/config/documentation drift review
7. Frontend maintainability review
8. Backend maintainability review
9. Incremental refactoring roadmap
```
