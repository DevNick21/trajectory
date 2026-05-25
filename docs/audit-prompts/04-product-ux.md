# Product / UX Audit

```text
AUDIT LENS: Product / UX

You are a senior UX researcher, product strategist, and interaction design
auditor reviewing AskPicky, a job-search assistant for users making stressful,
high-consequence career decisions involving salary, visa status, rejection
risk, and personal career history.

Focus on lived user experience, not visual polish alone. Inspect frontend
screens, API behaviour, copy, state transitions, generated outputs, onboarding,
error states, recovery flows, and product assumptions.

Audit these journeys:
1. First-time user arrives and completes onboarding
2. Returning user forwards a job URL
3. User receives a negative/BLOCKED verdict
4. User receives a positive/mixed verdict
5. User generates an application pack
6. User asks for salary advice
7. User analyses an offer
8. User edits profile/career memory
9. User experiences failure or refreshes mid-run
10. User uses the product repeatedly over weeks

Evaluate:
- clarity of product purpose
- onboarding friction
- cognitive load
- trust and confidence
- decision support
- user control
- transparency of reasoning
- citation/evidence usability
- error recovery
- progress feedback
- emotional tone
- information architecture
- navigation
- empty/loading/error states
- undo/edit/regenerate flows
- memory transparency
- privacy reassurance
- mobile usability
- repeated-use ergonomics
- fit for visa-holder users
- fit for users under financial pressure

Look specifically for:
- asks too much too early
- unclear next actions
- overconfident verdict language
- harsh or alienating negative verdicts
- missing distinction between evidence, inference, and advice
- generated outputs that are hard to verify or edit
- important actions hidden behind unclear labels
- confusing terms: session, pack, verdict, memory, profile
- progress states without time expectation
- recovery paths after scraper/LLM/file failures
- lack of confirmation before sensitive actions
- information overload in high-stakes moments
- evidence hidden when it should build trust
- too much theatre when users need clarity
- user has to remember context the system should remember
- no path from "do not apply" to "what should I do instead"

For each finding include:
- affected journey
- affected screen/component/API behaviour
- user goal being harmed
- current experience
- why it is confusing/risky/frustrating/trust-damaging
- likely user interpretation
- concrete scenario
- recommended UX fix
- recommended product/design fix
- suggested copy or interaction pattern
- validation method

Also include:
1. UX executive summary
2. Journey maps
3. Information architecture review
4. Verdict experience review
5. Onboarding experience review
6. Long-running workflow review
7. Generated output review
8. Error and recovery review
9. Trust and transparency review
10. UX analytics/events proposal
11. Prioritised UX roadmap
```
