# Trajectory — 3-Minute Demo Script (Remotion + Motion)

**Total: 3:00 · 30 fps · 5400 frames · 1920×1080 · ~430 words VO · Web-first with Telegram cameo**

Replaces the script in `SUBMISSION.md` §3.

---

## Tooling division

| Tool | Role |
|---|---|
| **Remotion** ([remotion.dev](https://remotion.dev)) | Composes the final `.mp4`. Owns the timeline (`<Composition>` + `<Sequence>`), programmatic overlays (`interpolate` / `spring` driven by `useCurrentFrame`), VO (`<Audio>`), screen-recording playback (`<OffthreadVideo>`), and music bed. |
| **Motion** ([motion.dev](https://motion.dev), formerly Framer Motion) | Drives in-app animations *inside* the Trajectory frontend — `Phase1Stream` ticks, `VerdictHeadline` reveal, `CitationLink` tooltip pop, `PackPicker` card lift, `SessionPack` violet ring on the cited career entry. Those UIs get screen-recorded; the recordings drop into Remotion as `<OffthreadVideo>` clips. |

**Why split it that way.** Remotion renders frame-by-frame in headless Chromium — Motion's runtime-driven animations (`whileHover`, `useEffect`-triggered `animate`) aren't frame-deterministic in that environment. So: Remotion's `interpolate`/`spring` for anything *composed in the video file*; Motion for anything *animated in the live product* that gets recorded.

---

## Remotion project layout — [YOU PROVIDE the assets in **bold**]

```text
demo/
├── package.json
├── remotion.config.ts
├── src/
│   ├── index.ts                    # registerRoot(RemotionRoot)
│   ├── Root.tsx                    # <Composition id="trajectory-demo" ... />
│   ├── DemoVideo.tsx               # top-level Series of Act1 / Act2 / Act3
│   ├── acts/
│   │   ├── Act1Fatigue.tsx         # 0:00–1:00  (frames 0–1800)
│   │   ├── Act2Product.tsx         # 1:00–2:20  (frames 1800–4200)
│   │   └── Act3Bet.tsx             # 2:20–3:00  (frames 4200–5400)
│   ├── scenes/                     # one file per beat (see Act tables below)
│   ├── overlays/
│   │   ├── RejectedStamp.tsx       # spring-driven slam + rotate
│   │   ├── HeadlineCard.tsx        # article screenshot + caption
│   │   ├── BlackTitleCard.tsx      # Act 1 closer + Act 3 quiet card
│   │   └── CitationTooltip.tsx     # for the Remotion-side cursor hovers
│   ├── primitives/
│   │   ├── FadeIn.tsx              # interpolate(frame, [in, in+15], [0,1])
│   │   ├── SlideUp.tsx
│   │   └── Cursor.tsx              # animated cursor sprite for screen-rec inserts
│   └── audio/
│       └── VOTrack.tsx             # <Audio src={vo}/> with per-act volumes
└── public/
    ├── vo/
    │   ├── act1.wav                # **VO recording, Act 1 (~22s)**
    │   ├── act2.wav                # **VO recording, Act 2 (~62s)**
    │   └── act3.wav                # **VO recording, Act 3 (~28s)**
    ├── music/
    │   └── bed.mp3                 # **sparse piano → synth → ambient pad**
    ├── screenrec/
    │   ├── dashboard.mp4           # **Dashboard.tsx screen-rec (5s)**
    │   ├── phase1-stream.mp4       # **Phase1Stream.tsx screen-rec (~12s)**
    │   ├── verdict-citation.mp4    # **VerdictHeadline + CitationLink hover (8s)**
    │   ├── pack-picker.mp4         # **PackPicker card click (3s)**
    │   ├── session-pack.mp4        # **SessionPack split-pane CV writing (~14s)**
    │   ├── routing-flicks.mp4      # **3× Greenhouse/Workday/Oracle labels (4s)**
    │   ├── telegram-handheld.mov   # **iPhone shot of @TrajectoryBot (8s)**
    │   └── sessions-list.mp4       # **GO/NO_GO list with cost ticker (4s)**
    ├── headlines/
    │   ├── ai-screeners-prefer-ai.png   # **screenshot, real publication**
    │   ├── recruiters-spot-ai-cv.png    # **screenshot, real publication**
    │   ├── 770-applications.png         # **screenshot, real source**
    │   └── ai-cv-instantly.png          # **screenshot, real publication**
    ├── rejections/
    │   └── inbox-{1..6}.png        # **6× rejection email subject-line crops**
    └── brand/
        ├── logomark.svg            # **Trajectory logomark**
        └── fonts/                  # **Inter or chosen display face**
```

### `Root.tsx` shape

```tsx
import { Composition } from "remotion";
import { DemoVideo } from "./DemoVideo";

export const RemotionRoot = () => (
  <Composition
    id="trajectory-demo"
    component={DemoVideo}
    durationInFrames={5400}   // 3:00 @ 30fps
    fps={30}
    width={1920}
    height={1080}
  />
);
```

### `DemoVideo.tsx` shape

```tsx
import { AbsoluteFill, Audio, Sequence, Series, staticFile } from "remotion";
import { Act1Fatigue } from "./acts/Act1Fatigue";
import { Act2Product } from "./acts/Act2Product";
import { Act3Bet } from "./acts/Act3Bet";

// Frame ranges where VO is speaking. Music ducks inside these windows
// and rests at the bed level outside. Tune end-frames to match the
// real VO file lengths once act{1,2,3}.wav are recorded.
const VO_WINDOWS: Array<[number, number]> = [
  [0, 660],      // Act 1 ~22s of VO inside the 60s act
  [1800, 3660],  // Act 2 ~62s of VO inside the 80s act
  [4200, 5040],  // Act 3 ~28s of VO inside the 40s act
];
const MUSIC_BED = 0.18;
const MUSIC_DUCKED = 0.06;
const duckMusic = (frame: number) =>
  VO_WINDOWS.some(([s, e]) => frame >= s && frame < e)
    ? MUSIC_DUCKED
    : MUSIC_BED;

export const DemoVideo = () => (
  <AbsoluteFill style={{ backgroundColor: "#0b0b0c" }}>
    <Series>
      <Series.Sequence durationInFrames={1800}><Act1Fatigue /></Series.Sequence>
      <Series.Sequence durationInFrames={2400}><Act2Product /></Series.Sequence>
      <Series.Sequence durationInFrames={1200}><Act3Bet /></Series.Sequence>
    </Series>

    {/* Music bed — frame-aware volume ducks under VO. */}
    <Audio src={staticFile("music/bed.mp3")} volume={duckMusic} />

    {/* Each VO file plays at its act's start. <Audio> has no
        `trimBefore` — wrap in <Sequence from={...}> to delay playback. */}
    <Sequence from={0}>
      <Audio src={staticFile("vo/act1.wav")} />
    </Sequence>
    <Sequence from={1800}>
      <Audio src={staticFile("vo/act2.wav")} />
    </Sequence>
    <Sequence from={4200}>
      <Audio src={staticFile("vo/act3.wav")} />
    </Sequence>
  </AbsoluteFill>
);
```

> Frame math: 30 fps. 1 sec = 30 frames. Act 1 = 1800. Act 2 = 2400. Act 3 = 1200.

---

## ACT 1 — Job-Search Fatigue (0:00–1:00 · frames 0–1800)
H
**VO direction** — direct, slightly worn ("I've been you").

| Beat | Frames | Scene component | Asset(s) — [YOU PROVIDE] | Animation (Remotion) |
|---|---|---|---|---|
| 1A — Headline cold open | 0–180 | `HeadlineCard` (×2 stacked, cursor scrolls) | `headlines/ai-screeners-prefer-ai.png`, `headlines/ai-cv-instantly.png` | `FadeIn` 0→15. `interpolate(frame, [60, 180], [0, -240])` for cursor scroll. |
| 1B — "770 applications" | 180–360 | `BigStat` | (procedural — number 770, label) | `spring({fps,frame:frame-180})` on the digit count-up; subtle weight on the period. |
| 1C — Rejection burst | 360–810 | `RejectionBurst` (Series of 6 inboxes) | `rejections/inbox-1.png` … `inbox-6.png` | Each child = `Sequence from={n*60} durationInFrames={75}`. `RejectedStamp` overlay slams in via `spring({fps, frame, config:{damping:8, stiffness:200}})` rotated 8°. Cuts accelerate: durations 80, 70, 60, 50, 40, 30. Snap to black at 810. |
| 1D — VO over burst | 360–810 | (audio only) | (VO covers the visuals) | — |
| 1E — Second headline pair | 810–1380 | `HeadlineCard` (×2) | `headlines/recruiters-spot-ai-cv.png`, `headlines/ai-screeners-prefer-ai.png` | Cross-fade: `interpolate(frame, [810, 870], [0, 1])`, second card in at 1080. |
| 1F — "AI paradox" VO | 870–1380 | (audio + visuals continue) | — | — |
| 1G — Black title card | 1380–1800 | `BlackTitleCard` | text: *"Trajectory doesn't fix the job market. It helps you navigate it."* | Letter-by-letter typewriter via `interpolate(frame, [1410, 1620], [0, text.length])` + `slice()`. Hold to 1800. |

**VO script (Act 1)** — keep verbatim from prior version:

> "Over 770 applications. That's not a hypothetical — that's the folder on this machine.
> More than 6 months years. Most of it on a visa — ten times the work, every application. Sponsor licence. SOC threshold. Salary floor. All to maybe hear back.
> And the AI tools? Caught in their own contradiction. Studies show AI screeners *prefer* AI-written CVs. Hiring managers bin them on sight. Use AI, you clear the bot and lose the human. Don't use AI, you drown in the volume."

---

## ACT 2 — Trajectory in 80 Seconds (1:00–2:20 · frames 1800–4200)

**VO direction** — product-confident, no oversell.

This act is mostly real product footage. Each `Scene*` wraps an `<OffthreadVideo>` plus Remotion-side caption overlays. The screen recordings themselves carry the **Motion-driven** in-app animations.

| Beat | Frames | Scene component | Screen-rec asset | Motion animations IN the recording — [YOU IMPLEMENT in the frontend] |
|---|---|---|---|---|
| 2A — Onboarded dashboard | 1800–1950 | `SceneDashboard` | `screenrec/dashboard.mp4` | Sidebar list items: `motion.li` with `variants` parent + `staggerChildren: 0.06`. Profile card: `whileHover={{ y: -2 }}`. |
| 2B — Forward URL form | 1950–2070 | `SceneForward` | embedded in `dashboard.mp4` tail | `ForwardJobForm` Analyse button: `whileTap={{ scale: 0.97 }}`, `transition={{ type:"spring", stiffness:400, damping:25 }}`. |
| 2C — Phase 1 stream (8 agents tick) | 2070–2430 | `ScenePhase1` | `screenrec/phase1-stream.mp4` | Each agent row: `<AnimatePresence>` exit + `layout` for the reorder when complete. Tick icon: `initial={{scale:0, rotate:-30}} animate={{scale:1, rotate:0}}` spring. Progress bar fill: `motion.div animate={{ width: \`${pct}%\` }}`. |
| 2D — VO: "8 agents fan out" | 2070–2430 | (audio) | — | — |
| 2E — Verdict + citation hover | 2430–2670 | `SceneVerdict` | `screenrec/verdict-citation.mp4` | `VerdictHeadline` reveal: `variants` with parent `delayChildren: 0.2, staggerChildren: 0.08` for badge → headline → confidence. `CitationLink` hover: `whileHover={{ y:-1 }}`, tooltip via `<AnimatePresence mode="wait">` with `initial={{opacity:0, y:6}} animate={{opacity:1, y:0}} exit={{opacity:0, y:6}}`. |
| 2F — PackPicker click | 2670–2760 | `ScenePackPicker` | `screenrec/pack-picker.mp4` | 4 cards: parent `variants` with `staggerChildren: 0.05`. Each card: `whileHover={{ y:-4, scale:1.01 }}`. Selected card: `layoutId="active-pack"` so it can morph into the next scene's header. |
| 2G — SessionPack split-pane CV | 2760–3180 | `SceneSessionPack` | `screenrec/session-pack.mp4` | Left pane career-entry cards: `motion.div layout` so the cited entry can re-order. Cited entry violet ring: `animate={{ boxShadow: "0 0 0 3px #8b5cf6" }} transition={{ duration:0.4 }}`. Right pane CV bullets stream-typing: per-line `motion.span` with `initial={{opacity:0}} animate={{opacity:1}}` triggered as the SSE token chunk arrives. |
| 2H — Multi-provider routing flicks | 3180–3300 | `SceneRouting` | `screenrec/routing-flicks.mp4` | 3 quick labels (Greenhouse→OpenAI / Workday→Anthropic / Oracle→Cohere): `<AnimatePresence mode="wait">` with `initial={{opacity:0, x:20}} animate={{opacity:1, x:0}} exit={{opacity:0, x:-20}}`. 30 frames each. |
| 2I — Telegram handheld | 3300–3960 | `SceneTelegram` | `screenrec/telegram-handheld.mov` | (Real device — no Motion. Remotion just plays the clip at the right moment.) |
| 2J — Beat to Act 3 | 3960–4200 | (audio rest) | — | Subtle Remotion vignette: `interpolate(frame, [3960, 4200], [0, 0.4])` on a radial mask opacity. |

**VO script (Act 2)** — keep verbatim:

> "You onboard once. Career history. Motivations. Deal-breakers. A few writing samples — your real voice. From then on, you forward a job URL.
> Eight research agents fan out in parallel. Sponsor Register, SOC going rates, Companies House, ONS earnings data, ghost-job signals, employee reviews. All live. All cited.
> Every claim links back to a real source. Sponsor Register, A-rated. Salary above the SOC 2136 floor. Click any badge — you land on gov.uk.
> Click any bullet — it rings the exact career entry that backs it. No invention. Just your story, restructured.
> This is the AI-paradox answer. The CV gets written by whichever model best clears that ATS — Greenhouse routes to OpenAI, Workday to Anthropic, Oracle to Cohere. But every line is anchored in your career entries and shaped by your writing samples. AI through the bot. *You* through the human.
> Same engine on Telegram. Forward a URL on the Tube, the verdict's waiting before your stop."

---

## ACT 3 — The Bigger Bet (2:20–3:00 · frames 4200–5400)

**VO direction** — quiet. Let "never auto-applies" land without flourish.

| Beat | Frames | Scene component | Asset — [YOU PROVIDE] | Animation |
|---|---|---|---|---|
| 3A — Sessions list + cost | 4200–4500 | `SceneSessions` | `screenrec/sessions-list.mp4` | (Motion in app) Each session row: `motion.div layout`. Cost ticker: `motion.span key={cost}` with `initial={{opacity:0, y:-6}} animate={{opacity:1, y:0}}` to make the £0.40 update feel earned. |
| 3B — "Trajectory will never auto-apply" VO | 4380–4860 | (audio) | — | — |
| 3C — Closing card | 4860–5280 | `BlackTitleCard` | text + `brand/logomark.svg` + URL + GitHub | Logomark `spring({fps, frame:frame-4860, config:{damping:14}})` from scale 0.8→1. Text fades in 30 frames after. |
| 3D — Hold black | 5280–5400 | (silence + ambient pad tail) | — | `interpolate(frame, [5280, 5400], [1, 0])` on master opacity. |

**VO script (Act 3)** — keep verbatim:

> "Trajectory will never auto-apply. You stay in the loop. We give you a verdict you can defend, a CV you'd recognise, and a pack you'd actually send.
> Built on Anthropic Opus 4.7. Grounded in UK government data. Open-source. I built this because I needed it — open-source if you do too."

**END CARD** — `trajectory.app · github.com/your-repo`

---

## Concrete Remotion patterns used

```tsx
// primitives/FadeIn.tsx
import { interpolate, useCurrentFrame } from "remotion";
export const FadeIn: React.FC<{from: number; durationInFrames?: number; children: React.ReactNode}> =
  ({from, durationInFrames = 15, children}) => {
  const frame = useCurrentFrame();
  const opacity = interpolate(frame, [from, from + durationInFrames], [0, 1], {
    extrapolateLeft: "clamp", extrapolateRight: "clamp",
  });
  return <div style={{ opacity }}>{children}</div>;
};

// overlays/RejectedStamp.tsx — physics slam
import { spring, useCurrentFrame, useVideoConfig } from "remotion";
export const RejectedStamp = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const scale = spring({ fps, frame, config: { damping: 8, stiffness: 220 } });
  return (
    <div style={{
      transform: `translate(-50%, -50%) rotate(-8deg) scale(${1 + (1 - scale) * 0.4})`,
      position: "absolute", top: "50%", left: "50%",
      color: "#e23", border: "6px solid #e23", padding: "8px 24px",
      fontWeight: 800, letterSpacing: 4, fontSize: 64,
    }}>REJECTED</div>
  );
};

// scenes/ScenePhase1.tsx — wraps screen-rec + Remotion caption
import { AbsoluteFill, OffthreadVideo, Sequence, staticFile } from "remotion";
import { FadeIn } from "../primitives/FadeIn";
export const ScenePhase1 = () => (
  <AbsoluteFill>
    <OffthreadVideo src={staticFile("screenrec/phase1-stream.mp4")} />
    <Sequence from={45} durationInFrames={120}>
      <FadeIn from={0}>
        <div style={{ position: "absolute", bottom: 80, left: 80, fontSize: 28 }}>
          8 agents · live · cited
        </div>
      </FadeIn>
    </Sequence>
  </AbsoluteFill>
);
```

## Concrete Motion patterns used (in the Trajectory frontend)

```tsx
// frontend/src/components/Phase1Stream.tsx — staggered ticks
import { motion, AnimatePresence } from "motion/react";

const list = { animate: { transition: { staggerChildren: 0.08 } } };
const row  = {
  initial: { opacity: 0, x: -8 },
  animate: { opacity: 1, x: 0, transition: { type: "spring", stiffness: 300, damping: 24 } },
};

<motion.ul variants={list} initial="initial" animate="animate">
  {agents.map(a => (
    <motion.li key={a.id} variants={row} layout>
      <AnimatePresence mode="wait">
        {a.status === "done" && (
          <motion.span key="tick" initial={{scale:0, rotate:-30}}
                       animate={{scale:1, rotate:0}}
                       transition={{type:"spring", stiffness:400, damping:18}}>✓</motion.span>
        )}
      </AnimatePresence>
    </motion.li>
  ))}
</motion.ul>

// frontend/src/components/CitationLink.tsx — tooltip pop
<AnimatePresence mode="wait">
  {hover && (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: 6 }}
      transition={{ duration: 0.15 }}
    >{snippet}</motion.div>
  )}
</AnimatePresence>

// frontend/src/components/PackPicker.tsx — shared layout morph into SessionPack
<motion.div layoutId="active-pack" whileHover={{ y: -4, scale: 1.01 }} />
```

---

## Build & render checklist — [YOU DO]

1. `npx create-video@latest demo --template hello-world` (TypeScript). Drop the layout above into `src/`.
2. `npm i motion` in `frontend/` (Trajectory app); wire the Motion patterns into `Phase1Stream`, `VerdictHeadline`, `CitationLink`, `PackPicker`, `SessionPack`, `SessionList`.
3. Record one **real** end-to-end session against the live stack; capture each `screenrec/*.mp4` clip *independently* (per Scene), against pre-seeded fixture data, so Phase 1 ticks, the verdict reveal, and the bullet→career-entry highlight all time cleanly. Capture at native 1920×1080 — if your display is HiDPI, set the recorder to 1× scaling so `<OffthreadVideo>` doesn't downscale-then-upscale. Don't pad — let actual numbers (770 count, 87% confidence, SOC 2136, ≤£0.40) stand.
4. Record VO (Act 1 / Act 2 / Act 3 separately so volume can duck under the music bed independently). Place under `public/vo/`.
5. Source music bed (sparse piano → low pulsing synth → ambient pad). Place at `public/music/bed.mp3`.
6. Source headline screenshots from real publications (UW / Northwestern, Bloomberg, FT, BBC, HBR). Redact bylines if needed.
7. `npx remotion preview` to scrub. `npx remotion render trajectory-demo out/trajectory-demo.mp4 --codec=h264 --crf=18`.

## Production notes (carried over)

- **770 figure** — verify and update before recording. Use the current count.
- **Tube line** — assumes UK audience and a real iPhone shot. If you record at a desk, swap to *"Forward it from your phone, the verdict's waiting when you sit down."*
- **Voice direction** — Act 1 direct/worn, Act 2 product-confident, Act 3 quiet.

## Intentional omissions

The current product does more than the script shows. Cut so the demo doesn't dilute:

- Verdict ensemble + deep-research toggle
- Story-bank retrieval weighting
- Batch job queue
- Offer analyser
- Cross-application memory (recruiter interactions, negotiation outcomes)
- Onboarding wizard internals

Each could be a 5–10s cameo if a re-cut is needed — drop a new `Series.Sequence` into `DemoVideo.tsx` with a fresh screen-rec.
