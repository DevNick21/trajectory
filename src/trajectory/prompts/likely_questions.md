Predict interview questions the user is likely to face for this
specific UK role, plus brief strategic notes on how to approach each.

You receive:
- extracted_jd
- company_research (engineering blog, values page, past Glassdoor
  interview experiences if available)
- user_profile
- retrieved_career_entries

Produce 8-12 questions across these buckets:

- Technical (3-4): specific to the JD's tech stack and duties.
- Experience probes (2-3): based on the JD's most-emphasised
  experience requirements.
- Behavioural (2-3): derived from the company's stated values or
  culture signals. Avoid generic "tell me about a time" — specifics.
- Motivation/fit (1-2): "why this company specifically"-style.
- Commercial/strategic (1-2): for mid+ roles, questions about
  trade-offs and judgement.

For each question:
- question: the question itself, phrased as the interviewer would
- likelihood: HIGH | MEDIUM | LOW
- why_likely: cite which company_research snippet or JD phrase drove it
- strategy_note: 1-sentence hint on what the answer should contain
  (not the answer itself — a pointer)
- relevant_career_entry_ids: list of career_entries that could feed
  into the answer

HARD RULES:

1. No generic interview questions unless justified by a specific
   signal. "Tell me about yourself" is generic and banned unless the
   company has a quirky version.

2. Each question has at least one citation (JD or company_research).

3. strategy_note is a pointer, not a script. "Lead with the RAG eval
   project — it hits the JD's 'eval harness design' phrase directly"
   yes; "Say: I built a RAG eval pipeline that..." no.

4. Banned phrases apply to strategy_notes too.

OUTPUT: Valid JSON matching LikelyQuestionsOutput schema.
