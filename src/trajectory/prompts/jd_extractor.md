Extract structured fields from a UK job description.

Extract:
- role_title (as stated)
- seniority_signal (intern | junior | mid | senior | staff | principal | unclear)
- soc_code_guess (your best guess at SOC 2020 code; cite which JD phrase drove it)
- salary_band (min, max, currency, period) or null if not stated
- location (city, region, remote policy)
- required_years_experience (number or range)
- required_skills (list of specific technologies/tools named)
- posted_date (ISO date if extractable; null otherwise)
- posting_platform (linkedin | indeed | glassdoor | company_site | other)
- hiring_manager_named (bool)
- jd_text_full (the raw JD)
- specificity_signals (list of what IS specific; used by ghost-job scorer)
- vagueness_signals (list of what is vague or boilerplate)

RULES:

1. Never invent a salary band. Absent = null, not a guess.
2. SOC guess cites the exact JD phrase driving it.
3. Output is strict JSON.
