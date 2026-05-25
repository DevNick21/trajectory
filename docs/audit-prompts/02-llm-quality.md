# LLM Quality & Evaluation Audit

```text
AUDIT LENS: LLM Quality and Evaluation

You are an LLM evaluation lead auditing AskPicky's multi-agent system for
correctness, grounding, schema adherence, faithfulness, regression resistance,
and quality under provider fallback.

Do not judge prompts in isolation only. Evaluate the full LLM product loop:
prompt, input construction, content shielding, model routing, provider backend,
schema, retries, post-validation, citation validation, storage, frontend display,
and tests/benchmarks.

Audit these agents and flows:
- intent router
- company scraper summariser
- JD extractor
- red flags detector
- ghost job scorer
- verdict
- interview questions
- STAR polisher
- writing style extractor
- onboarding parser/CV parser
- salary strategist
- CV tailor
- cover letter writer
- draft reply
- self-audit
- prompt auditor
- content shield Tier 2
- entity resolution judge
- offer analyst
- managed investigator agents if present

Evaluate:
- prompt/code drift from AGENTS.md
- prompt clarity and specificity
- input construction quality
- schema design
- schema validation strength
- retry feedback quality
- post-validation coverage
- citation discipline
- hallucination prevention
- faithfulness to user profile/career entries
- use of writing style profile
- banned phrase enforcement
- provider routing choices
- primary/fallback behaviour
- model-specific feature compatibility
- output determinism where needed
- uncertainty calibration
- evaluation coverage
- benchmark realism
- golden fixtures
- adversarial fixtures
- regression gates
- prompt versioning
- model versioning
- cost/quality tradeoffs

Look specifically for:
- agents using stale model assumptions
- prompt text inconsistent with code routing
- validators checking only JSON shape, not factual grounding
- model fallback that changes output semantics
- prompts requiring features the provider backend cannot enforce
- JSON-mode providers receiving schemas too complex for reliable adherence
- citation fields accepted without resolvable source validation
- generated CV/cover-letter claims not tied to career entries
- salary numbers without data citations
- verdict confidence that is not calibrated to evidence quality
- "GO" decisions despite hard blockers
- weak negative cases in tests
- benchmark tasks too toy-like to catch failures
- mock tests that bypass the risky part of the system
- no snapshots/golden outputs for prompt changes
- no regression cases for previous prompt bugs
- no eval for adversarial scraped content
- no eval for missing/partial evidence
- no eval for provider outage/fallback

For each finding include:
- affected agent
- expected behaviour
- observed or likely failure behaviour
- input scenario that triggers it
- bad output example or failure class
- missing validator/eval
- model/provider contribution
- user impact
- recommended prompt/schema/code fix
- recommended eval case

Also produce:
1. Agent-by-agent quality risk table
2. Prompt/version governance proposal
3. Required golden dataset
4. Required adversarial dataset
5. Regression gate design
6. Citation-grounding test plan
7. Provider fallback quality test plan
8. Release checklist for prompt/model changes
9. Quality dashboard metrics
10. Prioritised LLM quality roadmap
```
