# Trajectory demo — what *you* need to do (non-code)

Companion to [`demo_script.md`](./demo_script.md). Everything outside the codebase that has to happen before `npx remotion render` produces the final `.mp4`.

Motion patterns are already wired into the frontend — see [`demo_script.md`](./demo_script.md) §"Concrete Motion Patterns". This list is what's left.

Organised by work-session, not by act — that's how it actually gets done.

---

## 1. Pre-flight verifications

Five-minute checks. Do these first. If anything fails, fix before any recording starts.

- [ ] **`PHASE_1_AGENTS` constant order** in `frontend/src/lib/constants.ts` matches the VO list: *"Sponsor Register, Companies House, salary, reviews, ghost-job signals"*. Constant order = visual tick order. If they don't match, change the constant (not the VO).
- [ ] **Capital on Tap A-rated status** — download the gov.uk Sponsor Register CSV on recording day, search for "Capital on Tap" or its legal entity, confirm "A (Premium)" or "A (SME+)". Sponsor ratings change.
- [ ] **Capital on Tap job URL still live** — `https://job-boards.greenhouse.io/capitalontap/jobs/8520481002`. If posting was filled, swap to another role on their Greenhouse board (any non-senior tech role works).
- [ ] **No console errors** when running a real Phase 1 → verdict → CV cycle locally. Motion animations fire reliably. No race conditions in the SSE stream.

---

## 2. ElevenLabs voice clone

### Calibration (15 minutes, do once)

- [ ] Generate a 15s test clip with this paragraph at your chosen voice settings:
      *"Trajectory is a job-search assistant. It runs research agents in parallel, grounds every claim in a live source, and writes a CV in your voice. Built for the U-K market."*
- [ ] Time it. If ~14–16s → you're at ~140 wpm and the script will time correctly. Adjust speed if not.
- [ ] **Phonetic landmine pass** — generate each of these in isolation, confirm pronunciation:
  - [ ] "U-R-L" → "you-are-ell"
  - [ ] "C-V" → "see-vee"
  - [ ] "A-I" → "ay-eye"
  - [ ] "gov dot you-kay"
  - [ ] "Opus four-point-seven"
  - [ ] "U-K" → "you-kay"
  - [ ] "Seven hundred and seventy"

If any one is broken, rewrite that line in the script before generating the full act.

### Generate the three acts → `demo/public/vo/`

48 kHz / 24-bit if your plan allows. Otherwise the default ElevenLabs export is fine.

- [ ] `act1.wav` — Act 1 VO (~37s of speech). Tone: direct, slightly worn.
- [ ] `act2.wav` — Act 2 VO (~78s). Tone: product-confident, no oversell.
- [ ] `act3.wav` — Act 3 VO (~24s). Tone: quiet. Let *"never auto-applies"* land.

Generate 3 takes per act. Pick the best. Keep the others until final render is locked.

### After recording — update Remotion timing

- [ ] Measure each `.wav` file's actual duration (in milliseconds).
- [ ] Convert to frames: `frames = ceil(ms / 1000 * 30)`.
- [ ] Update `VO_WINDOWS` in `demo/src/DemoVideo.tsx`:
      ```tsx
      const VO_WINDOWS: Array<[number, number]> = [
        [0, ACT1_VO_FRAMES],
        [1800, 1800 + ACT2_VO_FRAMES],
        [4200, 4200 + ACT3_VO_FRAMES],
      ];
      ```
- [ ] Preview in Remotion to verify music ducks under speech and rests in the gaps.

---

## 3. Music bed → `demo/public/music/`

- [ ] Generate via ElevenLabs Music using the **Music Bed Prompt** in [`demo_script.md`](./demo_script.md). Generate 3 takes.
- [ ] Pick the best. If after 5 generations nothing lands, fall back to **Pixabay Music** — search "tech documentary build", "warm corporate cinematic", or "minimal corporate build 3 minute".
- [ ] Reference targets: Tycho "Awake" intro, Bonobo "Cirrus" intro, Hammock's quieter moments. If the AI gives you something that sounds like Ólafur Arnalds or a memorial, regenerate.
- [ ] Save as `bed.mp3` (MP3, 192kbps+ is fine — Remotion ducks the volume programmatically).

---

## 4. Article-headline screenshots → `demo/public/headlines/`

Real publications. PNG, ≥1200px wide. Crop tight: headline, byline, publication name, date. No paywalls or ad rails visible.

- [ ] `ai-screeners-prefer-ai.png` — research finding that AI résumé screeners prefer AI-written CVs. Search: "AI screeners prefer AI-written CVs UW Northwestern study" or Bloomberg coverage.
- [ ] `ai-cv-instantly.png` — second "hiring managers spot AI" piece, used in Act 1's second-headline-pair beat. Wired or HBR-style angle.

**If you can't find perfect matches:** the VO already works with two strong headlines — don't pad with weak ones. Delete the third asset reference from the Remotion scene if needed.

---

## 5. Rejection email crops → `demo/public/rejections/`

- [ ] Six PNGs (`inbox-1.png` … `inbox-6.png`) from your real `Applications_Archive` folder.
- [ ] Crop format: ~1200×120 strips showing one inbox row each — sender name, subject line, date, snippet preview.
- [ ] Greyscale optional but more cinematic.
- [ ] Redact your email address. Keep the sender domains (Capital on Tap, KnowBe4, etc. — *real* company names land harder than redacted ones).
- [ ] **The script claim is *"that's the folder on this machine."* These have to be real.**

---

## 6. Brand → `demo/public/brand/`

- [ ] `logomark.svg` — Trajectory logomark, white-on-transparent so it sits on the closing black card.
- [ ] `fonts/` — display face (Inter, Söhne, or chosen). TTF/WOFF2 + CSS `@font-face` declarations.

---

## 7. Recording environment setup (one-time)

Do these once, before any recording. Skipping causes 80% of common screen-rec failures.

### Hardware & display

- [ ] Display set to 1920×1080 native resolution. No scaling.
- [ ] If HiDPI/Retina: configure OBS to capture at 1× pixel ratio (not 2×).
- [ ] External monitor preferred. Disconnect laptop screen if you can.
- [ ] System audio muted. Notifications globally silenced. Do Not Disturb on.
- [ ] Wallpaper set to solid `#0b0b0c` or pure black (matches Remotion bg if anything flashes).
- [ ] Dock / taskbar set to auto-hide.

### Cursor highlight tool (single biggest visual upgrade)

Pick one based on platform:

- [ ] **macOS**: Cursor Pro (free) or Mouseposé. Settings: ~30px circle, 30% opacity, click-flash enabled, no key visualisation.
- [ ] **Windows**: Mouseinc or PointerFocus. Same settings.
- [ ] **Linux**: key-mon or custom xdotool overlay.

### Browser

- [ ] Chrome or Brave. Fresh profile. **Zero extensions** (1Password, Grammarly, etc. inject UI that ruins takes).
- [ ] Zoom set to exactly 100% (Cmd/Ctrl+0).
- [ ] Bookmark bar populated with: Trajectory localhost, Capital on Tap Greenhouse URL, gov.uk Sponsor Register page, Companies House search.

### Recording software

- [ ] **OBS Studio** installed (not QuickTime, not Game Bar).
- [ ] OBS settings:
  - Output mode: Advanced
  - Recording format: MP4
  - Encoder: x264 (or hardware H.264)
  - Rate Control: CRF, value 18
  - FPS: **30** (must match Remotion)
  - Resolution (Base + Output): **1920×1080** for both
  - Audio: **disable all audio inputs** — VO is separate

### Take-naming convention

Save every take as: `trajectory-{shotname}-{takenum}.mp4`
e.g. `trajectory-phase1-stream-04.mp4`. Keep all takes until final render is locked.

---

## 8. Fixture data prep (before any recording)

- [ ] **Build SSE replay flag** for `streamForwardJob` (~30 min):
      Read events from a JSON fixture file when `import.meta.env.VITE_REPLAY_PHASE1=true`. Run one good Capital on Tap session live, capture the SSE event stream to a fixture file, replay deterministically. Saves you from API-timeout hell across 6+ takes.
- [ ] **Onboarding complete** — career history, motivations, deal-breakers, writing samples all populated.
- [ ] **`SessionList` populated** with 6+ prior sessions, mixed GO/NO_GO verdicts.
- [ ] **One Capital on Tap CV pack pre-generated** with bullets that have known `career_entry` citations. Verify which bullets bind to which entries via React DevTools or console — you'll need to click those specific bullets during the SessionPack take.

---

## 9. Screen recordings → `demo/public/screenrec/`

Capture independently per scene. Native 1920×1080. Plan for 3–6 takes per shot, more for the hero shots. **Do them in the suggested order** — emotional intensity climbs gradually, dependencies make sense.

### Order of recording

- [ ] **`dashboard.mp4`** (5s) — warm-up shot. Hard refresh, capture the stagger fire-on-load.
- [ ] **`pack-picker.mp4`** (3s) — easy. Hover lift on Tailored CV card → click Generate → navigation.
- [ ] **`sessions-list.mp4`** (4s) — easy. Hover GO/NO_GO badges. **No cost ticker** (cut from spec).
- [ ] **`phase1-stream.mp4`** (~12s) — hero shot. Paste URL, click Check, capture all 9 agents ticking through. Use the SSE replay flag.
- [ ] **`verdict-citation.mp4`** (8s) — hover a `gov_data` citation chip → click → gov.uk opens. Then hover a `url_snippet` chip → tooltip pops with verbatim quote → click → source opens.
- [ ] **`session-pack.mp4`** (~14s) — hardest. Click Generate → CV bullets cascade in → click a bullet with `career_entry` citation → violet ring jumps to the cited career entry on the left → click a *different* bullet → ring moves.
- [ ] **`telegram-screencap.mov`** (8s) — separate session. iPhone via QuickTime → File → New Movie Recording → select iPhone. Telegram chat with `@TrajectoryBot`. Paste URL → bot replies with verdict via message edits.

### Critical setup details per shot

- [ ] **Phase 1 shot:** confirm agent ordering matches VO before recording.
- [ ] **Verdict shot:** pre-load gov.uk in the browser tab cache before recording so the second load is near-instant.
- [ ] **SessionPack shot:** identify which CV bullets have `career_entry` citations *before* recording. Plan cursor path to land on those specific bullets.
- [ ] **Telegram shot:** clear chat history first. Phone brightness max. Status bar should show normal time of day (not 3am).

### Common failure modes to watch for

- [ ] Toast notifications covering content mid-take → shorten toast duration to 1500ms or move position.
- [ ] Browser dev tools visible → close before each take.
- [ ] Autofocus on URL input → blinking cursor on first frame ruins the cold open. Remove autofocus.
- [ ] OS notifications mid-take → DND on, system sounds muted.
- [ ] HiDPI capture artifacts → confirm OBS is at 1× scaling.

---

## 10. Remotion build (once recordings are in)

- [ ] `npx create-video@latest demo --template hello-world` (TypeScript) at the repo root.
- [ ] Drop the layout from [`demo_script.md`](./demo_script.md) §"Remotion Project Layout" into `demo/src/`.
- [ ] Implement scene components per the Act tables (one file per beat in `demo/src/scenes/`).
- [ ] Implement primitives (`FadeIn`, `SlideUp`, `Cursor`) in `demo/src/primitives/`.
- [ ] Implement overlays (`RejectedStamp`, `HeadlineCard`, `BlackTitleCard`, `ProviderRoutingChip`) in `demo/src/overlays/`.
- [ ] Drop screen-recs, headline PNGs, rejection PNGs, VO files, music bed, brand assets into `demo/public/` per the layout.
- [ ] Update `VO_WINDOWS` in `DemoVideo.tsx` to actual VO durations (see §2 above).
- [ ] `npx remotion preview` → scrub every act, fix timing collisions.
- [ ] `npx remotion render trajectory-demo out/trajectory-demo.mp4 --codec=h264 --crf=18`.

---

## 11. Final taste calls

Decide before recording, not during.

- [ ] **End-card URLs** — `trajectory.app` and `github.com/<your-repo>`. Replace `<your-repo>` with the real org/name.
- [ ] **Headline screenshot publications** — pick three real ones before recording so the visuals match the VO's "studies show" framing.
- [ ] **Music bed sign-off** — generate and approve before VO recording so you can read into its rhythm.

---

## 12. Pre-flight before final render

Last check before hitting `npx remotion render`.

- [ ] All assets in `demo/public/` per the layout.
- [ ] All Motion patterns wired in the frontend and visible in a real session.
- [ ] All seven `screenrec/*.mp4` clips captured at 1920×1080 (note: only 7, not 8 — `routing-flicks.mp4` was cut).
- [ ] `telegram-screencap.mov` captured.
- [ ] All three `vo/act*.wav` files recorded; `VO_WINDOWS` updated to match.
- [ ] Music bed in place at `public/music/bed.mp3`.
- [ ] `npx remotion preview` — every act scrubs cleanly, music ducks under VO, end-card lands at frame 5400.
- [ ] One full render at `--crf=18` — watch end-to-end for collisions, audio sync, off-by-one timing.

---

## Time estimate

| Phase | Hours |
|---|---|
| ElevenLabs VO (calibration + 3 acts) | 1.5 |
| Music bed generation | 0.5 |
| Source headlines + rejection crops | 1.0 |
| Recording environment setup | 0.5 |
| SSE replay flag + fixture data | 1.0 |
| 7 screen recordings (with retakes) | 4.0 |
| Telegram recording | 0.5 |
| Remotion scaffold + scene implementation | 2.0 |
| Asset wiring + VO_WINDOWS tuning | 1.0 |
| Preview + iterate | 1.5 |
| Final render + revision pass | 1.5 |
| **Total** | **~15 hours** |

Spread across however many days you have. Bulk is in recording (4 hours) and Remotion implementation (3.5 hours).

---

## Out of scope for v1

Cut intentionally. Don't add unless you re-cut:

- Multi-provider routing screen-rec (replaced by `ProviderRoutingChip` overlay)
- Cost-per-session ticker (Option B — drop entirely)
- Verdict ensemble + deep-research toggle
- Story-bank retrieval weighting
- Batch job queue
- Offer analyser
- Cross-application memory (recruiter interactions, negotiation outcomes)
- Onboarding wizard internals
- 12-second timing claim (no longer in VO; visual carries it)