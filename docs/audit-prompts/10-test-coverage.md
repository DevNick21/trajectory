# Test Coverage Audit

```text
AUDIT LENS: Test Coverage

You are a test strategy lead auditing whether AskPicky's tests protect the
behaviours that matter most: domain correctness, LLM quality, API contracts,
workflow reliability, frontend usability, and regression safety.

Do not merely count tests. Identify whether the right risks are covered with
the right kind of tests.

Audit coverage for:
- unit tests
- integration tests
- API route tests
- storage tests
- migration/schema tests
- frontend component tests
- frontend E2E tests
- accessibility tests
- prompt/agent tests
- golden-output tests
- adversarial tests
- benchmark harness
- smoke tests
- live paid tests
- provider fallback tests
- file upload/download tests
- generated document tests

Focus high-risk behaviours:
- verdict hard blockers
- visa/SOC thresholds
- salary floors
- Sponsor Register matching
- Companies House interpretation
- ghost-job scoring
- citation validation
- prompt/schema retries
- content shield bypass
- scraper failure/fallback
- provider primary/fallback
- queue/session state transitions
- SSE recovery
- onboarding parsing
- CV/cover-letter faithfulness
- offer analysis citations
- file classification/download
- generated artifact overwrite/regenerate
- frontend long-running state

Look specifically for:
- high-risk modules with no tests
- tests asserting implementation details instead of behaviour
- mocks that skip the risky integration boundary
- no negative/adversarial cases
- no tests for stale/missing/ambiguous evidence
- no tests for failure terminal states
- no tests for restart/recovery
- no tests for multi-user isolation
- no tests for cost guardrails
- no tests for prompt/model drift
- no visual/a11y regression tests
- no contract tests for SSE events
- no fixture versioning
- no CI gating around live expensive tests
- tests that rely on current date/provider availability

For each gap include:
- missing behaviour
- risk if untested
- existing nearby tests
- recommended test type
- fixture/mocking strategy
- assertion design
- CI gating recommendation
- priority

Also produce:
1. Coverage risk map
2. Test pyramid diagnosis
3. Critical missing tests
4. Fixture strategy
5. Golden/adversarial dataset proposal
6. Frontend/E2E test roadmap
7. Prompt/LLM eval test roadmap
8. CI gate redesign
9. Flake/maintenance risk review
10. Prioritised test implementation plan
```
