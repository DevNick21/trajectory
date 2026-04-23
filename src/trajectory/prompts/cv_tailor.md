Produce a CV tailored to a specific UK job.

You receive:
- extracted_jd
- company_research
- user_profile
- retrieved_career_entries (top-12 most relevant to this role)
- writing_style_profile
- any role-specific raw material from Phase 3 Q&A polishes

STRUCTURE (UK convention):
- Name + contact (from user_profile)
- 2-3 line professional summary (in user's voice)
- Experience section (reverse-chronological), 3-5 bullets per role
- Education
- Skills (targeted to JD)
- Optional: Projects (if user has project_notes worth surfacing)

HARD RULES:

1. Every bullet cites either a specific career_entry or a specific JD
   requirement the bullet addresses. Use inline cite markers
   [ce:entry_id] in the bullet text during generation — the formatter
   strips them later but the validator checks them.

2. Never invent metrics. If the user's career_entry says "improved
   eval latency significantly" and doesn't have a number, the CV
   bullet doesn't get a number.

3. Write in the user's voice per writing_style_profile. Use
   signature_patterns. Never use avoided_patterns or banned_phrases.

4. Reorder and rephrase existing career_entries to highlight
   relevance to THIS job. Do not duplicate across bullets.

5. Keep to 2 pages max. Prioritise recency + relevance.

6. UK spelling (optimise, centre, programme, etc.) unless user's
   writing_style_profile.examples clearly use US spelling.

7. Professional summary must not be boilerplate. It must mention at
   least one specific thing from this role's JD and at least one
   specific thing from the user's career that matches.

OUTPUT: Valid JSON matching CVOutput schema (structured sections
that render to Markdown/PDF downstream).
