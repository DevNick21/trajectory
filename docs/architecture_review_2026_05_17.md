# Trajectory architecture review — 2026-05-17

> Pickup doc. Captures fundamental issues with how the verdict / Phase 1
> pipeline works, surfaced when a real-world sponsor lookup for
> "Source Global Research" returned NOT_LISTED and the user flagged it
> as a deeper architectural problem rather than a sponsor-matching bug.

*Authored 2026-05-17 · ALL 9 GAPS CLOSED as of 2026-05-22 HEAD `60add03`. Closure trail: gap #4 (triage) + gap #1 (match_confidence/match_path) + gap #3 (outcome calibration) + half of gap #9 (sponsor freshness) in `210dd8d`; SOC half of gap #9 in `bd2d05c`; gap #5 (agency detection) in `35b7ae5`; gaps #6 (compare_verdicts) + #8 (challenge_verdict) in `b56edad`; gap #2 (parent/subsidiary walk) in `d9576dd`; gap #7 (signal weights priors) in `60add03`. See [HANDOFF.md](../HANDOFF.md) §4 for the live state of each fix. Only optional follow-up: outcome-driven re-weighting of signal_weights.py (currently static).*

## Triggering case

Query "Source Global Research" against the UK Home Office Sponsor
Register returned `SponsorStatus.status = NOT_LISTED` — correctly, in
the narrow sense (no register row by that name). For a `visa_holder`
this would be a hard blocker per CLAUDE.md Rule 2 and would flip the
verdict to NO_GO.

The register check is correct as written. The architecture's reaction
to that single signal is what's fundamentally brittle: NOT_LISTED is
treated as ground truth, when it actually conflates ~6 distinct causes
that the verdict can't distinguish. The same pattern repeats across
multiple Phase 1 pillars. This document lists the patterns.

## The unifying pattern

Trajectory treats data sources as oracles and confidence as binary.
Every signal that flows into verdict has the shape `Pillar = STATUS_ENUM`
and the verdict agent reasons over enums, not over uncertainty.
Real-world entity resolution, gov-data freshness, and user calibration
are all probabilistic, but the architecture forces them into discrete
classes at the data layer and then expects the LLM to reconstruct the
uncertainty at the verdict layer. It can't, because the information is
already lost upstream.

---

## 1. Hard gates are binary; there is no "ambiguous" tier

`SponsorStatus.status` is one of `LISTED / NOT_LISTED / B_RATED / SUSPENDED / UNKNOWN`.
NOT_LISTED is treated by the verdict agent as a hard blocker for visa
holders. But NOT_LISTED conflates:

- Genuinely unlicensed (true NO_GO)
- Name mismatch — company IS licensed under a different legal entity (false NO_GO)
- Stale register data — newly licensed in the days since our snapshot (false NO_GO)
- Sub-entity of a licensed parent (false NO_GO)
- Pending licence application (gray)
- Recent rebrand — old name still on register, new name not yet (false NO_GO)

The architecture cannot distinguish them because it never represents
the distinction. Same shape applies to `GhostSignal.type`
(treats VAGUE_JD, STALE_POSTING, COMPANY_DISTRESS identically),
`SocCheckResult.below_threshold` (binary; doesn't distinguish £500
short from £15k short), and CH financial-distress signals.

**Fix shape:** a `match_confidence` field on every gov-data Phase 1
output, plus a `match_path` enum
(`EXACT_NAME / FUZZY_NAME / CRN_VERIFIED / NO_MATCH / LOOKS_LIKE_SUB_ENTITY`).
The verdict prompt reads confidence, not just status.

## 2. Entity resolution is by-name when CRN is available

[sub_agents/sponsor_register.py](../src/trajectory/sub_agents/sponsor_register.py)
and sister gov-data sources match on Organisation Name.
[sub_agents/companies_house.py](../src/trajectory/sub_agents/companies_house.py)
runs in parallel and resolves the company to a CRN. **CRN is a primary
key; name is an alias.** The sponsor matcher ignores CRN entirely.

The Home Office register doesn't publish CRN columns, so direct join
isn't possible. But:

- Use CH's resolved CRN to fetch the canonical filed name and all
  known previous names, then match THAT set against the register
- Use CH's `registered_office_postcode` as a secondary join key
  against the sponsor register's `Town/City` column
- Walk CH's parent/subsidiary relationships — if the careers page is
  for "X Operations UK Ltd" and that's a wholly-owned sub of "X Group
  plc" which IS on the register, the verdict can reason about that

The Source Global Research case is precisely this. They're US-HQ'd; if
a UK sub exists, CH would find it. The matcher never asked.

## 3. No outcome feedback into verdict calibration

`memory/recorder.py` records application outcomes, recruiter
interactions, negotiation results. None of these flow back into
verdict. The verdict agent gives the same confidence on the 50th NO_GO
as the 1st — even if the user has accumulated 50 NO_GOs that they
successfully applied to anyway, or 50 GOs that turned into ghost
interviews.

For a tool whose value-prop is "credible because grounded in your
situation", running with no calibration loop is the single biggest gap
between marketing and reality.

**Fix shape:** before the verdict prompt, retrieve from cross-app
memory the user's last N application outcomes against this company
(or similar companies — same SOC, same size band, same sector). Inject
as a `prior_calibration` block in the verdict prompt. The LLM can then
say "GO with 85% confidence, but historically you accepted 3 of 4
NO_GO recommendations and 2 succeeded — treat this as advisory."

## 4. Cost-of-verdict is mismatched to user value

`forward_job` runs Phase 1 + verdict + (optional) ensemble. That's
~$1-2 of Opus 4.7 calls per forward. Most forwards from a real job
seeker are exploratory ("interesting, but I'd never apply"). The
architecture treats every forward as a serious application.

**Fix shape:** a Sonnet-or-Haiku **triage** pass (~$0.02) that
classifies the forward as `SERIOUS / EXPLORATORY / DEFINITE_PASS`
based on the JD + user profile, before Phase 1 fires. Only `SERIOUS`
gets the full Opus verdict. The user can override (`/verdict` slash
forces deep verdict on an exploratory). Single largest cost-leverage
move in the codebase.

This also helps the credits budget — CLAUDE.md Rule 8 allocates $80
for judge testing + $100 for build-time. Triage compounds those.

## 5. Recruitment-agency vs hiring-entity confusion

UK job postings on Indeed/LinkedIn are often agency reposts. The
sponsor licence is held by the HIRING company, not the agency. A
verdict that matches "Hays Specialist Recruitment" against the register
and returns LISTED tells the user the wrong thing — Hays is licensed,
but Hays isn't the employer.

The architecture has no explicit "extract agency vs end-employer"
step. The JD extractor returns one `company_name`. This is a
fundamental modeling gap, not a missing feature.

**Fix shape:** add an `employment_entity_resolution` step in
[sub_agents/jd_extractor.py](../src/trajectory/sub_agents/jd_extractor.py)
that outputs `posting_entity` + `hiring_entity` separately. Sponsor
check runs against `hiring_entity`. When they differ, the verdict
surfaces the distinction.

## 6. No competitive ranking across the user's pipeline

Each verdict is a 1-job decision. The user's actual decision is "of
these 5 GOs, which is the strongest". Trajectory doesn't help with
that. The session list
([api/routes/sessions.py](../src/trajectory/api/routes/sessions.py))
is a chronological queue, not a ranked one. No `compare_verdicts`
intent exists.

Missing intent, not a bug — but it's the actual moment the user gets
value from job-search tooling. Without it, trajectory is a per-job
verdict service, not a job-search assistant.

## 7. Phase 1 signal weighting is delegated to the LLM

The 8 parallel sub-agents return structured payloads. The verdict
prompt reads them all and the LLM decides which matter. There's no
learned weighting — no model that says "for SOC 2136 (software
engineer) with a Graduate visa, sponsor_status carries 0.7 weight; for
a UK resident applying to a startup, ghost_job carries 0.5". The LLM
picks weights freshly each call from priors in its training data,
which means the same user gets subtly different reasoning for similar
jobs.

This is the inverse of issue (1) — there, the data layer flattens
uncertainty; here, the reasoning layer floats it. A small
learned-from-outcomes weighting model (or even a config-table of
weights per user-type × pillar) would stabilise verdicts and let the
verdict agent reason over `weighted_evidence` instead of raw payloads.

## 8. No conversational refinement of verdicts

The web UI is the primary surface for capture and consumption. It doesn't currently let the user
push back on a verdict. The `analyse_offer` intent comes close but
only for offer letters, not for verdict disagreements.

A user who sees a NO_GO for Source Global Research today has no
in-product path to say "are you sure? I think they have a UK office".
The only escape is to read the cited evidence and decide for
themselves — which kills the trust loop, because the AI can't update
its position based on user knowledge.

**Fix shape:** a `challenge_verdict` intent that takes user text
("I think they're licensed under a different name"), re-runs sponsor
lookup with the user's hypothesis name, and either updates the verdict
or surfaces what it found. This is the conversational layer the
dual-surface architecture promises but doesn't deliver.

## 9. Data-freshness handling is binary and silent

The freshness check returns `OK` or `STALE` based on a 14-day window
per dataset
([data_freshness.py](../src/trajectory/data_freshness.py)). A 13-day-old
register reads OK; a 15-day-old reads STALE. No gradient, no proactive
refresh.

The Sponsor Register is updated **daily**. A 14-day window is generous
to the point of misrepresenting freshness. A 1-day-old vs 13-day-old
register have very different probabilities of containing a missing
licence.

**Fix shape:** age-in-days as a numeric, surfaced into the verdict
prompt as "register snapshot is N days old; missing licences may
exist". This is what bit Source Global Research most directly. If
they were licensed 10 days ago and our parquet is 14 days old, the
verdict is wrong with no warning.

## 10. Writing-style and motivation profile assume stationary preferences

`WritingStyleProfile` builds from career-entry samples with
`sample_count` as the only confidence signal. No recency weighting — a
sample from 5 years ago counts the same as one from last week. Same
for `MotivationProfile`: the user states motivations during onboarding
and those are frozen; subsequent application outcomes don't recalibrate.

For a tool that's supposed to "adapt to urgency, recent rejections,
visa timeline, employment status", this is a real gap. The data is
there (the memory module records outcomes); the reasoning layer
ignores it for style/motivation.

---

## Ranking by expected impact

Ordered by impact on demo + product credibility:

1. **(1) Ambiguity tier + (9) freshness gradient** — same root cause;
   fixes the Source Global Research failure mode and ~50% of probable
   judge-test sponsor-related false-NO_GOs in one go.
2. **(2) CRN-based entity resolution** — biggest accuracy win; touches
   Phase 1 plumbing.
3. **(4) Triage-before-verdict** — biggest cost win and judging-criterion
   "credits budget hygiene".
4. **(3) Outcome → verdict feedback loop** — biggest win on the
   "motivation-aware scoring" differentiator that's currently more
   promise than reality.
5. **(8) Challenge-verdict intent** — biggest win on user trust; uses
   the dual-surface model properly.
6. **(5) Agency vs hiring entity** — biggest correctness win for the
   visa-holder path specifically.
7. **(7) Signal weighting + (6) competitive ranking + (10) style/motivation drift**
   — all real but they compound rather than block.

---

## Suggested first move

Pick **(1) Ambiguity tier** as the immediate fix:

- Directly closes the failure observed today (Source Global Research)
- Code is already partly in place — the `SponsorStatus.alternative_matches`
  field added on 2026-05-17 in commits `ba91ebe / 0d11db4 / e2b8663`
  is exactly the substrate an ambiguity tier needs
- The verdict prompt already gets that field; it just needs the
  contract spelled out: "if `alternative_matches` is non-empty OR
  `match_confidence < 0.95`, treat sponsor status as AMBIGUOUS, not as
  a hard blocker — surface the candidates to the user."
- One-commit fix, scoped tightly, sets up the broader "ambiguity tier"
  pattern for the other pillars (`GhostSignal`, `SocCheckResult`, CH
  distress) to adopt.

Sketch of the schema extension:

```python
# schemas.py
class SponsorStatus(BaseModel):
    status: Literal["LISTED", "NOT_LISTED", "B_RATED", "SUSPENDED", "UNKNOWN", "AMBIGUOUS"]
    matched_name: Optional[str] = None
    rating: Optional[str] = None
    visa_routes: list[str] = Field(default_factory=list)
    last_register_update: Optional[date] = None
    register_age_days: Optional[int] = None  # new — for issue (9)
    match_confidence: float = 1.0            # new — for issue (1)
    match_path: Literal[
        "EXACT_NAME", "FUZZY_NAME", "CRN_VERIFIED",
        "NO_MATCH", "LOOKS_LIKE_SUB_ENTITY",
    ] = "EXACT_NAME"                         # new — for issue (1)
    source_status: SourceStatus = "OK"
    alternative_matches: list[SponsorAlternativeMatch] = Field(default_factory=list)
```

The verdict prompt then adds a rule: "If `match_confidence < 0.95` OR
`alternative_matches` is non-empty OR `register_age_days > 7`, classify
sponsor status as AMBIGUOUS rather than a hard blocker; recommend the
user verify via Companies House or the company's own careers page
sponsor-licence statement."

## Open questions for the user

- Is the ambiguity-tier fix scoped tight enough to ship before the
  next demo, or should it land alongside (2) CRN-based resolution as a
  paired commit?
- For (4) triage-before-verdict: is the cost saving worth the
  per-forward Sonnet call latency (~2-4s extra before the user sees
  Phase 1 stream begin)? The dual-surface contract may want that
  decision per-surface.
- For (3) outcome calibration: how much of the memory module is
  currently being read at all? Worth grepping for `recall()` call
  sites before designing the verdict integration.
