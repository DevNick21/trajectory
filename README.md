# Trajectory — Export Pack

Eight markdown files, designed to be dropped into the root of your repo
(except PROCESS.md, which some judges may want to see and others may
not — you decide).

## Read order

**Wednesday morning (before you touch code):**

1. **CLAUDE.md** — the operating manual. 15 min read.
2. **ARCHITECTURE.md** — system design in detail. 20 min read.
3. **PROJECT_STRUCTURE.md** — file-by-file reference. 10 min skim.

**Wednesday as you build Phase 1:**

4. **AGENTS.md** — open to the relevant agent's section each time you
   implement one. Copy the system prompt verbatim into the code.
5. **SCHEMAS.md** — paste the code block into `src/trajectory/schemas.py`
   in one go.

**Saturday late afternoon / Sunday:**

6. **CLAUDE_DESIGN_PLAYBOOK.md** — follow section by section during
   video production.
7. **SUBMISSION.md** — the closeout checklist.

**Optional but recommended:**

8. **PROCESS.md** — re-read before live finals (if medaling). It's
   the document that gives you the exact reasoning behind every
   choice, which is what judges probe at.

---

## File sizes

| File | Purpose | Length |
|------|---------|--------|
| CLAUDE.md | Operating manual for Claude Code + humans | ~500 lines |
| ARCHITECTURE.md | System design, data flow, invariants | ~400 lines |
| AGENTS.md | 16 agents' full prompt specs | ~800 lines |
| SCHEMAS.md | Every Pydantic model | ~450 lines |
| PROJECT_STRUCTURE.md | File-by-file responsibilities | ~500 lines |
| CLAUDE_DESIGN_PLAYBOOK.md | Video production guide | ~450 lines |
| PROCESS.md | Decision log (the "why") | ~400 lines |
| SUBMISSION.md | Video script, description, checklists | ~350 lines |

Total: ~3,800 lines of scaffolding documentation.

---

## What these files don't contain

- **Full Python implementations.** That's your Wednesday–Saturday work.
  Each agent spec in `AGENTS.md` tells you the system prompt, the I/O
  schema, the validation rules. Each file listing in
  `PROJECT_STRUCTURE.md` tells you the function signature. You
  implement the middle.

- **API client boilerplate.** The first 30 minutes of Wednesday builds
  `config.py`, `llm.py`, and `storage.py`. These are trivial Claude
  Code tasks given the specs.

- **Test implementations.** Only the test file names and what each
  covers. Writing tests is fast once the code is there.

- **Prompt engineering iterations.** The prompts in `AGENTS.md` are
  solid starting points. You'll tune them during build, and that
  tuning is judged work.

---

## How to keep these docs honest during the week

Every time you make a design change during build — even a small one —
append it to `PROCESS.md` as a new entry. Format:

```markdown
## Entry N — What changed

- What was on the table: ...
- What changed: ...
- Why: ...
- Cost / unlock: ...
```

This is what "Depth & Execution" (20% of judging) actually rewards. Not
"I had a plan and executed it". "I had a plan, hit reality, adjusted,
documented why."

If you find yourself implementing something not described in these
docs, either:
1. Write the missing spec in the relevant doc first, then implement.
2. Or document why the doc was wrong in `PROCESS.md` as a new entry.

Never let the implementation drift silently from the docs. On demo day,
a judge asking "I see your verdict agent does X but your spec says Y —
can you explain?" is the nightmare question. Keeping these in sync
prevents it.

---

## Licence

These docs are part of the Trajectory repo and ship under MIT. If you
want to keep your decision log private (PROCESS.md), add a `.private`
suffix and add to `.gitignore`. My default recommendation: keep it
public. It's part of the moat.

---

Good luck this week, Kene. Go ship it.
