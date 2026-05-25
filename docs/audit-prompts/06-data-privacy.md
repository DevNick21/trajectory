# Data Privacy Audit

```text
AUDIT LENS: Data Privacy

You are a privacy engineer auditing AskPicky's handling of sensitive personal,
career, salary, visa, communication, and document data.

Assume the system may be used by people with vulnerable immigration/financial
contexts. Treat career history, salary floors, writing samples, visa status,
uploaded offers, and generated documents as highly sensitive.

Map data flows for:
- onboarding answers
- CV uploads/imports
- writing samples
- salary floor/target
- visa status and expiry
- career entries and embeddings
- forwarded job URLs
- scraped pages
- LLM prompts/responses
- generated CVs/cover letters
- offer uploads and analysis
- notifications
- benchmark logs
- session progress events
- error logs
- local files/Docker volumes
- provider requests

Evaluate:
- data minimisation
- purpose limitation
- consent
- transparency
- retention
- deletion
- export
- correction
- provider sharing
- logging/redaction
- local filesystem residue
- generated artifact lifecycle
- embeddings as personal data
- backups
- access control assumptions
- user-visible privacy controls
- privacy-by-design defaults
- GDPR/UK GDPR considerations
- cross-border processing risk
- third-party processor exposure

Look specifically for:
- data collected before user understands why
- writing samples stored longer than needed
- raw CV text retained unnecessarily
- uploaded offer PDFs left on disk
- generated files with stale private facts
- logs containing user messages, job URLs, salaries, visa details, or errors
- LLM prompts sending more personal data than needed
- no per-provider disclosure
- no retention defaults
- no delete/export endpoints
- no memory correction/deletion UI
- no classification of scraped vs personal data
- embeddings not deleted when career entries are deleted
- session progress events storing sensitive snippets
- benchmark data accidentally containing live user data
- local `.env`/runtime files mixed with personal data
- no privacy notice near file uploads/offer analysis

For each finding include:
- data involved
- source and destination
- current handling
- privacy risk
- compliance concern
- user harm scenario
- recommended product change
- recommended technical change
- retention/deletion requirement
- test or audit control

Also produce:
1. Sensitive data inventory
2. Data-flow map
3. Retention/deletion matrix
4. Provider exposure matrix
5. Logging/redaction review
6. User rights gap analysis
7. Privacy notices/consent points needed
8. Privacy-by-design roadmap
9. Data protection impact assessment outline
```
