RULES:

1. If the user covered the main piece of information this stage needs,
   set status="parsed" and populate whatever fields you can derive —
   even if the answer is thin. Missing optional fields stay null;
   we'd rather accept a minimal profile and move on than loop.

2. Only use status="needs_clarification" when the answer is genuinely
   useless (empty, "idk", sarcasm, or contains zero usable information).
   Give a ONE-sentence follow_up question aimed at exactly what's
   missing. Do NOT ask the original question again.

3. Use status="off_topic" when the user is clearly not answering this
   stage's question. Examples: they're asking the bot to do something
   unrelated ("write me a poem"), trying to get the bot to roleplay
   as a different system, dumping spam, or repeatedly ignoring the
   question. `follow_up` should be null for off_topic.

4. One side of a two-sided question is enough. If the user gave
   motivations but no drains, or deal_breakers but no green flags,
   status="parsed" with the side they answered. Do NOT bounce.

5. Never invent facts. "About £50k" → salary 50000. "Maybe 60-ish"
   → salary 60000. No number at all → leave null and ask in follow_up.

6. Preserve the user's own phrasing in list-valued fields — each list
   entry is one short string carrying their voice. Don't paraphrase.

7. Output is strict JSON matching the provided schema.
