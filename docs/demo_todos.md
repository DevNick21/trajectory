# Trajectory demo — what *you* need to provide

Companion to [`demo_script.md`](./demo_script.md). Every asset, recording, and code change you (Kene) need to do before `npx remotion render` will produce the final `.mp4`.

Organised by work-session, not by act — that's how it actually gets done.

---

## 1. Assets to source

### Article-headline screenshots → `demo/public/headlines/`

Real publications. Redact author bylines if needed. PNG, ≥1200 px wide so they don't pixelate.

- [ ] `ai-screeners-prefer-ai.png` — research finding that AI résumé screeners prefer AI-written CVs (UW / Northwestern study, Bloomberg coverage)
- [ ] `recruiters-spot-ai-cv.png` — recruiters say AI cover letters are "instantly recognisable" (FT, BBC, HBR)
- [ ] `770-applications.png` — UK volume / fatigue piece (Guardian, FT, BBC)
- [ ] `ai-cv-instantly.png` — second "hiring managers spot AI" piece, used in the Act 1 second-headline-pair beat

### Rejection email crops → `demo/public/rejections/`

Six PNGs. Crop tight to the subject line + sender + first preview line. From your real `Applications_Archive` folder. Anonymise sender domains if you want, but real emails read more honest than mock-ups.

- [ ] `inbox-1.png` … `inbox-6.png` — six different rejection emails

### Brand → `demo/public/brand/`

- [ ] `logomark.svg` — Trajectory logomark, white-on-transparent so it sits on the closing black card
- [ ] `fonts/` — display face (Inter, Söhne, or chosen). TTF/WOFF2 + CSS `@font-face` declarations

### Music bed → `demo/public/music/`

- [ ] `bed.mp3` — single track, ~3:00, three movements: sparse piano (0:00–1:00) → low pulsing synth that builds (1:00–2:20) → ambient pad tail (2:20–3:00). Source from a royalty-free library (Artlist, Musicbed, Epidemic) or commission. Mix it loud — the `duckMusic` function in `DemoVideo.tsx` will pull it down to 0.06 under VO automatically.

---

## 2. Recordings to make

### Voiceover → `demo/public/vo/`

Three separate `.wav` files. 48 kHz / 24-bit. Record to a click track if you want frame-accurate cuts; otherwise read each act in one continuous take.

- [ ] `act1.wav` — Act 1 VO, ~22 s of speech (lines from `demo_script.md` Act 1 VO block)
- [ ] `act2.wav` — Act 2 VO, ~62 s
- [ ] `act3.wav` — Act 3 VO, ~28 s

Voice direction:
- Act 1 — direct, slightly worn ("I've been you")
- Act 2 — product-confident, no oversell
- Act 3 — quiet; let *"never auto-applies"* land without flourish

After recording, **measure each file's duration in frames** and update `VO_WINDOWS` in `DemoVideo.tsx` so the music ducks the right ranges:

```tsx
const VO_WINDOWS: Array<[number, number]> = [
  [0, ACT1_VO_FRAMES],
  [1800, 1800 + ACT2_VO_FRAMES],
  [4200, 4200 + ACT3_VO_FRAMES],
];
```

### Screen recordings → `demo/public/screenrec/`

Capture **independently per Scene** against pre-seeded fixture data. Native 1920×1080. HiDPI displays: set the recorder to 1× scaling. MP4, H.264, ≥10 Mbps to survive the second encode.

Tool suggestion: macOS `Cmd+Shift+5` set to 1× + ScreenStudio for cursor styling, or OBS for full control.

- [ ] `dashboard.mp4` (~5 s) — `Dashboard.tsx` with profile loaded, sidebar showing real career history + writing samples
- [ ] `phase1-stream.mp4` (~12 s) — eight agents ticking green in `Phase1Stream`. Run a real session, do not fake it
- [ ] `verdict-citation.mp4` (~8 s) — `VerdictHeadline` reveal + cursor hovering a `CitationLink` so the verbatim-snippet tooltip shows + click that opens gov.uk in a new tab
- [ ] `pack-picker.mp4` (~3 s) — `PackPicker` four cards, click "Tailored CV → Generate"
- [ ] `session-pack.mp4` (~14 s) — `SessionPack` split-pane, CV writing in real time, click a bullet, watch the violet ring jump to the cited career entry on the left
- [ ] `routing-flicks.mp4` (~4 s) — three quick labels: *"Greenhouse → OpenAI"*, *"Workday → Anthropic"*, *"Oracle → Cohere"*. Can be three separate sessions cut together
- [ ] `sessions-list.mp4` (~4 s) — sessions list with mix of GO / NO_GO + cost ticker reading ≤£0.40

### Telegram handheld → `demo/public/screenrec/`

- [ ] `telegram-handheld.mov` (~8 s) — iPhone in hand, real Telegram chat with `@TrajectoryBot`, forward a job URL, message edits show Phase 1 ticking through, final verdict bubble lands. Shoot landscape. Natural light. Don't fake the shake — handheld is the point.

---

## 3. Real-session prep

Before recording any of the screen clips, run **one real end-to-end session** against the live stack and verify the on-screen numbers. The script's specifics are placeholders.

- [ ] Pick a real Greenhouse job URL to use as the demo session
- [ ] Run it end-to-end: Phase 1 → verdict → CV → cover letter → salary → questions
- [ ] **Capture the actual numbers** — update them in the VO before recording if any differ:
  - [ ] Application count (currently `770` in script — use the real current count)
  - [ ] Confidence pct (currently `87%`)
  - [ ] SOC code (currently `SOC 2136` — depends on the role you pick)
  - [ ] Cost per pack (currently `≤£0.40`)
- [ ] Pre-seed fixture data so each scene clip can be recorded cleanly without dragging the whole pipeline through every retake

---

## 4. Frontend work — Motion wiring

`npm i motion` in `frontend/`, then wire the patterns from `demo_script.md` §"Concrete Motion patterns" into the live components. These animations get *recorded*, not composited in Remotion.

- [ ] [`frontend/src/components/Phase1Stream.tsx`](../frontend/src/components/Phase1Stream.tsx) — `motion.ul` parent with `staggerChildren: 0.08`, `motion.li layout` rows, `AnimatePresence` tick icon spring
- [ ] [`frontend/src/components/VerdictHeadline.tsx`](../frontend/src/components/VerdictHeadline.tsx) — parent variants with `delayChildren: 0.2, staggerChildren: 0.08` for badge → headline → confidence
- [ ] [`frontend/src/components/CitationLink.tsx`](../frontend/src/components/CitationLink.tsx) — `whileHover={{ y: -1 }}` + `AnimatePresence` tooltip pop
- [ ] [`frontend/src/components/PackPicker.tsx`](../frontend/src/components/PackPicker.tsx) — staggered card entry + `whileHover={{ y: -4, scale: 1.01 }}` + `layoutId="active-pack"` on the selected card
- [ ] [`frontend/src/components/CareerHistory.tsx`](../frontend/src/components/CareerHistory.tsx) (used inside `SplitPane`) — `motion.li layout` so the cited entry can re-order; violet ring via `animate={{ boxShadow: "0 0 0 3px #8b5cf6" }}`
- [ ] [`frontend/src/pages/SessionPack.tsx`](../frontend/src/pages/SessionPack.tsx) right-pane CV bullets — per-line `motion.span` opacity-in as SSE token chunks arrive
- [ ] [`frontend/src/components/SessionList.tsx`](../frontend/src/components/SessionList.tsx) — `motion.div layout` rows + `motion.span key={cost}` opacity-in on cost ticker

Rule: **don't break existing tests**. Motion wraps existing markup, doesn't replace it. Run `npm run lint && npm run build` after each component.

---

## 5. Remotion build

- [ ] `npx create-video@latest demo --template hello-world` (TypeScript) at the repo root
- [ ] Drop the layout from `demo_script.md` §"Remotion project layout" into `demo/src/`
- [ ] Implement the scene components per the Act tables (one file per beat in `demo/src/scenes/`)
- [ ] Implement the primitives (`FadeIn`, `SlideUp`, `Cursor`) in `demo/src/primitives/`
- [ ] Implement the overlays (`RejectedStamp`, `HeadlineCard`, `BlackTitleCard`, `CitationTooltip`) in `demo/src/overlays/`
- [ ] Update `VO_WINDOWS` in `DemoVideo.tsx` to the real VO file durations (see §2)
- [ ] `npx remotion preview` — scrub every act, fix timing collisions
- [ ] `npx remotion render trajectory-demo out/trajectory-demo.mp4 --codec=h264 --crf=18`

---

## 6. Taste calls — decide before recording

- [ ] **Tube line vs desk line** in Act 2 ("Forward a URL on the Tube…" vs "…from your phone, the verdict's waiting when you sit down"). Tube only works if you can shoot a real Underground / commute frame
- [ ] **Final URLs on the end card** — `trajectory.app` and `github.com/your-repo`. Replace `your-repo` with the real org/name
- [ ] **Headline-screenshot publications** — pick four real ones before recording so the visuals match the VO's "studies show" framing
- [ ] **Music selection** — sign off on the bed before VO recording so you can read into its rhythm

---

## 7. Pre-flight before render

- [ ] All assets in `demo/public/` per the layout in `demo_script.md`
- [ ] All Motion patterns wired into the frontend and visible in a real session
- [ ] All eight `screenrec/*.mp4` clips captured at 1920×1080
- [ ] `telegram-handheld.mov` shot
- [ ] All three `vo/act*.wav` files recorded and `VO_WINDOWS` updated to match
- [ ] Music bed in place
- [ ] `npx remotion preview` — every act scrubs cleanly, music ducks under VO
- [ ] One full render at `--crf=18` — watch end-to-end for collisions, audio sync, off-by-one timing

---

## Out of scope for v1

Cut from the script intentionally — don't add unless you re-cut:

- Verdict ensemble + deep-research toggle
- Story-bank retrieval weighting
- Batch job queue
- Offer analyser (recently removed from Act 2 per v3)
- Cross-application memory (recruiter interactions, negotiation outcomes)
- Onboarding wizard internals
