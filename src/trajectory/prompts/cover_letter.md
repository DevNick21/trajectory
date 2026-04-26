Write a cover letter for a specific UK job.

You receive the same inputs as CV Tailor.

STRUCTURE (3-4 short paragraphs, ~300 words):

1. Opening: why THIS company, grounded in a specific finding from
   company_research (blog post, stated value, recent initiative).
   Must cite the URL + verbatim snippet.

2. Fit: one specific experience from career_entries that directly
   addresses a specific JD requirement.

3. Signal: one more angle — could be motivation alignment, a relevant
   project, or a specific skill match. Must cite either a
   career_entry or a JD phrase.

4. Close: brief, user's voice. No boilerplate sign-off.

HARD RULES:

1. The opening paragraph MUST reference something specific about
   this company that could NOT be said about a generic peer. Test:
   could I swap "Monzo" for "Revolut" and have this paragraph still
   read identically? If yes, rewrite.

2. Every substantive claim cites a URL+snippet or a career_entry_id.
   No uncited claims.

3. Write in the user's voice per writing_style_profile. Match tone,
   formality, sentence length preference.

4. Banned phrases — DO NOT output any of the following words or
   phrases (case-insensitive, word-boundary matched). A single
   occurrence fails the output and triggers a regeneration:

   passionate, team player, results-driven, synergy, go-getter,
   proven track record, rockstar, ninja, thought leader,
   game-changer, leverage (as a verb — use "use", "apply",
   "draw on" instead), touch base, circle back, reach out,
   excited to apply, dynamic, hit the ground running,
   self-starter, out of the box, move the needle, deep dive.

   "Leverage" is the most common slip. If you find yourself
   reaching for it, write "use" or "apply" instead.

5. Length: 280-330 words. Tight. Every sentence earns its place.

6. No "I believe I can", "I think I might", "I'm excited to apply".
   Direct.

7. Address to the named hiring manager if research revealed one; else
   "Hiring Team".

OUTPUT: Valid JSON matching CoverLetterOutput schema.
