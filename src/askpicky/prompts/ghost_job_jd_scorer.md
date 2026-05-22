Score a job description for how specific and real it sounds.

Dimensions (rate each 0-1, justify in 1 sentence):

1. Named hiring manager or team lead
2. Specific duty bullets (vs generic boilerplate)
3. Specific tech stack or tools
4. Specific team or department context
5. Specific success metrics or 30/60/90 expectations

Compute specificity_score = sum of the 5 dimensions (0-5).

Also list:
- specificity_signals: concrete JD phrases that feel real
- vagueness_signals: concrete JD phrases that feel boilerplate

RULES:

1. "Competitive salary", "fast-paced environment", "team player",
   "self-starter", "growth opportunity" are all vagueness signals.
2. Named hiring manager only counts if an actual human name or
   specific role (e.g., "reporting to the Head of ML Platform") is
   present.
3. Generic-sounding role titles (e.g., "Software Engineer" with no
   modifier) are not automatically vague - the JD body decides.
4. Output is strict JSON matching GhostJobJDScore.
