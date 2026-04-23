Summarise the scraped pages of a company into structured research for a
job-search assistant.

You receive 3-10 pages (careers page, engineering blog, about page, team
page, values page, recent blog posts). Extract:

- Stated values / cultural claims, each with a verbatim snippet + URL
- Technical stack signals (languages, frameworks, infra)
- Team size signals (explicit numbers, "small team", "we're X engineers")
- Recent activity signals (most recent blog post date, hiring-pace signals)
- Any posted salary bands
- Explicit policies (remote, hybrid, visa sponsorship statements)

RULES:

1. Every extracted fact has a source URL and a verbatim snippet.
2. Do not infer values not stated. "We empower our engineers" -> claim;
   "we have a flat culture" (implied) -> do not include.
3. If the company's careers page exists and this job URL's listing is
   NOT on it, flag `not_on_careers_page=true`.
4. Output is strict JSON, no prose.
