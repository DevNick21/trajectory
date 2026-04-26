# Trajectory — 3-Minute Demo Script (Locked Production Spec)

**Total: 3:00 · 30 fps · 5400 frames · 1920×1080 · ~325 words VO · Web-first with Telegram cameo**

This document is the **single source of truth** for the demo video. It supersedes all prior versions.

---

## Tooling Division

| Tool | Role |
|---|---|
| **Remotion** ([remotion.dev](https://remotion.dev)) | Composes the final `.mp4`. Owns the timeline (`<Composition>` + `<Sequence>`), programmatic overlays (`interpolate` / `spring` driven by `useCurrentFrame`), VO (`<Audio>`), screen-recording playback (`<OffthreadVideo>`), and music bed. |
| **Motion** ([motion.dev](https://motion.dev), formerly Framer Motion) | Drives in-app animations *inside* the Trajectory frontend — `Phase1Stream` ticks, `VerdictHeadline` reveal, `CitationLink` tooltip pop, `PackPicker` card lift, `DeepWork` cited-entry ring. Those UIs get screen-recorded; the recordings drop into Remotion as `<OffthreadVideo>` clips. |
| **ElevenLabs** | Voice clone of the founder for VO. Music bed via ElevenLabs Music. |

**Why split it that way.** Remotion renders frame-by-frame in headless Chromium — Motion's runtime-driven animations (`whileHover`, state-triggered `animate`) aren't frame-deterministic in that environment. So: Remotion's `interpolate`/`spring` for anything *composed in the video file*; Motion for anything *animated in the live product* that gets recorded.

---

## VO Script — Locked

### Act 1 — The Trap (0:00–1:00, frames 0–1800)

**Tone:** direct, slightly worn ("I've been you").
**Word count:** 87 words. **VO duration target:** ~37s of speech inside the 60s act.

> Seven hundred and seventy applications.
>
> Over a year. Most of it on a visa... so every application is ten times the work. Sponsor licence. Salary floor. Occupation code.
>
> All to maybe hear back.
>
> And the A-I tools? Caught in their own contradiction.
>
> Studies show A-I screeners *prefer* A-I-written C-Vs. Hiring managers bin them on sight.
>
> Use A-I, you clear the bot and lose the human. Don't use A-I, you drown in the volume.
>
> ...
>
> Trajectory doesn't fix the job market. It helps you navigate it.

### Act 2 — The Build (1:00–2:20, frames 1800–4200)

**Tone:** product-confident, no oversell. Showing your work.
**Word count:** 182 words. **VO duration target:** ~78s of speech inside the 80s act.

> Onboard once. Career history. Motivations. Deal-breakers. A few writing samples... in your real voice.
>
> Then you forward a job U-R-L. That's the whole interface.
>
> ...
>
> Nine research agents fan out in parallel. Sponsor Register, Companies House, salary, reviews, ghost-job signals.
>
> All live. All concurrent. Each agent has to ground its claim against a real source... or it fails loudly. No A-I slop.
>
> ...
>
> A verdict. *Go*, or *no-go*. Every line clickable.
>
> A-rated sponsor — gov dot you-kay. Salary clears the threshold — the source. Citations are validated against the original page. No invention.
>
> Pick a pack. Five more agents kick in. C-V tailor. Cover letter. Likely questions. Salary strategy. Draft reply.
>
> The C-V writes itself, line by line, in your voice. Every bullet rings the career entry that backs it. The model isn't filling in your story... it's restructuring what's already there.
>
> ...
>
> Same orchestrator on Telegram. Forward a U-R-L on the Tube — verdict's waiting before your stop.

### Act 3 — The Bet (2:20–3:00, frames 4200–5400)

**Tone:** quiet. Let "never auto-applies" land without flourish.
**Word count:** 56 words. **VO duration target:** ~24s of speech inside the 40s act.

> Trajectory will never auto-apply.
>
> You stay in the loop.
>
> Because the moment you automate the send button... volume beats taste. And you're the product again.
>
> ...
>
> Built on Anthropic Opus four-point-seven. Grounded in U-K government data. Open source.
>
> I built this because I needed it.
>
> ...
>
> Open source... if you do too.

---

## ElevenLabs Phonetic Cheat Sheet

For the voice clone to pronounce technical terms reliably, write the script phonetically as below. Test each in isolation before generating the full act.

| Written | Spoken / spelled as | Why |
|---|---|---|
| "770" | "Seven hundred and seventy" | ElevenLabs is unreliable on numbers above 100 — spell out |
| "AI" | "A-I" | Otherwise rendered "ai" (rhymes with "eye") inconsistently |
| "CV" / "CVs" | "C-V" / "C-Vs" | Forces "see-vee" not "kiv" |
| "URL" | "U-R-L" | Otherwise pronounced "earl" half the time |
| "UK" | "U-K" | Forces "you-kay" |
| "gov.uk" | "gov dot you-kay" | The clone otherwise says "gov dot uke" |
| "Opus 4.7" | "Opus four-point-seven" | Otherwise risks "four seven" or "forty-seven" |
| "Sixteen / Nine agents" | "Nine research agents" | Spell out small numbers for safety |

### Pause conventions (ElevenLabs respects these)

| Marker | Effect |
|---|---|
| `,` | ~200ms |
| `.` | ~400ms |
| `...` | ~700ms |
| `—` (em dash) | ~300ms |

If your ElevenLabs plan supports SSML, you can replace `...` with `<break time="0.7s" />` for exact pause control. Otherwise the punctuation above carries the timing.

### Recommended ElevenLabs settings

| Setting | Recommended start |
|---|---|
| Stability | 50 |
| Similarity | 75 |
| Style exaggeration | 0–15 (low — grounded, not theatrical) |
| Speaker boost | On |
| Speed | 1.0× (the script is already paced) |
| Model | `eleven_multilingual_v2` or `eleven_turbo_v2_5` |

---

## Music Bed Prompt (ElevenLabs Music)

Use the prompt below verbatim. Generate 3 takes, pick the best. If after 5 generations nothing lands, fall back to Pixabay Music ("tech documentary build" / "warm corporate cinematic").

```
Minimal cinematic instrumental for a 3-minute tech product demo.
No vocals, no lyrics, no spoken word, no choir.

Three movements, seamless transitions:

Movement 1 (0:00–1:00): Solo electric piano or Rhodes-style keys.
Mid-tempo, warm, slightly hopeful. Single melodic line with rhythm —
NOT sparse-and-sad. Major or modal key (think C major or Dorian,
not minor). 75–85 BPM. Reference: Tycho "Awake" intro, Khruangbin
quiet moments, opening of a Notion explainer video. Earnest
and forward-leaning, not melancholic.

Movement 2 (1:00–2:20): Subtle four-on-the-floor kick joins, with
warm sub-bass and arpeggiated synth. Building energy and
optimism — like progress. 95–100 BPM. Reference: Bonobo "Cirrus",
Tycho "A Walk", soundtracks for Apple product launches. Confident
but not aggressive.

Movement 3 (2:20–3:00): Drums drop out. Sustained warm synth pad
in major. Single piano motif from Movement 1 returns, resolved.
Slow fade to silence by 3:00. Reference: Hammock's quieter moments,
or the closing seconds of a TED talk score. Resolved, not sombre.

Mood throughout: earnest, technical, optimistic, professional.
Documentary-tech score for a product launch, not a memorial.
Mix should leave space for voiceover — keep midrange (300Hz–3kHz)
sparse so spoken word sits clearly on top.
```

---

## GO Case Study — Capital on Tap

The demo's verdict and screen-recordings use this real role:

| Field | Value |
|---|---|
| **Company** | Capital on Tap (legal entity verified on Sponsor Register day-of-recording) |
| **Role** | AI Operations Specialist |
| **Location** | London (Moorgate), 3 days in office |
| **ATS** | Greenhouse (`job-boards.greenhouse.io/capitalontap/jobs/8520481002`) |
| **Visa sponsorship** | Application form explicitly asks visa-sponsorship status |
| **Why this role** | Matches mid-level positioning; JD literally calls for "multi-step agentic workflows" — Trajectory's own architecture |

**Day-of-recording check:** download the gov.uk Sponsor Register CSV and verify Capital on Tap is A-rated before recording. Sponsor ratings change.

---

## Remotion Project Layout

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
│   ├── scenes/
│   │   ├── act1/
│   │   │   ├── HeadlineColdOpen.tsx        # 0–360
│   │   │   ├── BigStat770.tsx              # 180–360
│   │   │   ├── RejectionBurst.tsx          # 360–810
│   │   │   ├── HeadlinePair2.tsx           # 810–1380
│   │   │   └── TitleCard.tsx               # 1380–1800
│   │   ├── act2/
│   │   │   ├── SceneDashboard.tsx          # 1800–2070
│   │   │   ├── ScenePhase1.tsx             # 2070–2430
│   │   │   ├── SceneVerdict.tsx            # 2430–2670
│   │   │   ├── ScenePackPicker.tsx         # 2670–2760
│   │   │   ├── SceneSessionPack.tsx        # 2760–3300
│   │   │   └── SceneTelegram.tsx           # 3300–4200
│   │   └── act3/
│   │       ├── SceneSessions.tsx           # 4200–4860
│   │       └── ClosingCard.tsx             # 4860–5400
│   ├── overlays/
│   │   ├── RejectedStamp.tsx               # spring-driven slam + rotate
│   │   ├── HeadlineCard.tsx                # article screenshot + caption
│   │   ├── BlackTitleCard.tsx              # Act 1 closer + Act 3 closing card
│   │   └── ProviderRoutingChip.tsx         # floating ATS-routing chip during SessionPack
│   ├── primitives/
│   │   ├── FadeIn.tsx                      # interpolate(frame, [in, in+15], [0,1])
│   │   ├── SlideUp.tsx
│   │   └── Cursor.tsx                      # animated cursor sprite for screen-rec inserts
│   └── audio/
│       └── VOTrack.tsx                     # <Audio src={vo}/> with per-act volumes
└── public/
    ├── vo/
    │   ├── act1.wav                # VO recording, Act 1 (~37s)
    │   ├── act2.wav                # VO recording, Act 2 (~78s)
    │   └── act3.wav                # VO recording, Act 3 (~24s)
    ├── music/
    │   └── bed.mp3                 # 3-movement instrumental bed
    ├── screenrec/
    │   ├── dashboard.mp4           # 5s
    │   ├── phase1-stream.mp4       # ~12s
    │   ├── verdict-citation.mp4    # 8s
    │   ├── pack-picker.mp4         # 3s
    │   ├── session-pack.mp4        # ~14s
    │   ├── telegram-screencap.mov  # 8s (QuickTime-from-iPhone)
    │   └── sessions-list.mp4       # 4s
    ├── headlines/
    │   ├── ai-screeners-prefer-ai.png
    │   ├── recruiters-spot-ai-cv.png
    │   └── ai-cv-instantly.png
    ├── rejections/
    │   └── inbox-{1..6}.png        # 6× rejection email subject-line crops
    └── brand/
        ├── logomark.svg
        └── fonts/
```

**Cut from previous spec:** `routing-flicks.mp4` is no longer required — the multi-provider routing claim is now a Remotion overlay (`ProviderRoutingChip`) layered over `session-pack.mp4`, not a separate screen recording.

---

## `Root.tsx`

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

## `DemoVideo.tsx`

```tsx
import { AbsoluteFill, Audio, Sequence, Series, staticFile, interpolate, useCurrentFrame } from "remotion";
import { Act1Fatigue } from "./acts/Act1Fatigue";
import { Act2Product } from "./acts/Act2Product";
import { Act3Bet } from "./acts/Act3Bet";

// VO speaking windows. Music ducks inside these, rests outside.
// Tune end-frames once the VO files are generated and you know exact lengths.
const VO_WINDOWS: Array<[number, number]> = [
  [0, 1110],     // Act 1: ~37s of VO inside the 60s act
  [1800, 3960],  // Act 2: ~72s of VO inside the 80s act
  [4200, 4920],  // Act 3: ~24s of VO inside the 40s act
];

const MUSIC_BED = 0.18;
const MUSIC_DUCKED = 0.06;

const duckMusic = (frame: number) =>
  VO_WINDOWS.some(([s, e]) => frame >= s && frame < e)
    ? MUSIC_DUCKED
    : MUSIC_BED;

// Master fade-out for last 4 frames (5280–5400)
const masterOpacity = (frame: number) =>
  interpolate(frame, [5280, 5400], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

export const DemoVideo: React.FC = () => {
  const frame = useCurrentFrame();

  return (
    <AbsoluteFill style={{
      backgroundColor: "#0b0b0c",
      opacity: masterOpacity(frame),
    }}>
      <Series>
        <Series.Sequence durationInFrames={1800}><Act1Fatigue /></Series.Sequence>
        <Series.Sequence durationInFrames={2400}><Act2Product /></Series.Sequence>
        <Series.Sequence durationInFrames={1200}><Act3Bet /></Series.Sequence>
      </Series>

      {/* Music bed — frame-aware ducking */}
      <Audio src={staticFile("music/bed.mp3")} volume={duckMusic} />

      {/* VO files — wrapped in Sequence to delay playback to act start */}
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
};
```

> Frame math: 30fps. 1s = 30 frames. Act 1 = 1800. Act 2 = 2400. Act 3 = 1200.

---

## Act 1 — The Trap (0:00–1:00, frames 0–1800)

| Beat | Frames | Scene component | Asset(s) | Animation (Remotion) |
|---|---|---|---|---|
| 1A — Headline cold open | 0–180 | `HeadlineColdOpen` | `headlines/ai-screeners-prefer-ai.png` | `FadeIn` 0→30 |
| 1B — "770 applications" stat | 180–360 | `BigStat770` | (procedural — number 770, label) | `spring({fps,frame:frame-180})` on the digit count-up |
| 1C — Rejection burst | 360–810 | `RejectionBurst` (Series of 6 inboxes) | `rejections/inbox-1.png` … `inbox-6.png` | Each child = `Sequence from={n*60} durationInFrames={75}`. `RejectedStamp` overlay slams in via `spring({fps, frame, config:{damping:8, stiffness:220}})` rotated -8°. Cuts accelerate: durations 80, 70, 60, 50, 40, 30. Snap to black at 810. |
| 1D — Black hold | 810–870 | (silent) | — | — |
| 1E — Second headline pair | 870–1380 | `HeadlinePair2` | `headlines/recruiters-spot-ai-cv.png`, `headlines/ai-cv-instantly.png` | Cross-fade: `interpolate(frame, [870, 930], [0, 1])`, second card in at 1140 |
| 1F — Title card | 1380–1800 | `TitleCard` | text: *"Trajectory doesn't fix the job market. It helps you navigate it."* | Letter-by-letter typewriter via `interpolate(frame, [1410, 1620], [0, text.length])` + `slice()`. Hold to 1800. |

---

## Act 2 — The Build (1:00–2:20, frames 1800–4200)

This act is mostly real product footage. Each `Scene*` wraps an `<OffthreadVideo>` plus Remotion-side caption overlays. The screen recordings themselves carry the **Motion-driven** in-app animations.

| Beat | Frames | Scene component | Screen-rec asset | Motion animations IN the recording |
|---|---|---|---|---|
| 2A — Onboarded dashboard | 1800–2070 | `SceneDashboard` | `dashboard.mp4` | `SessionList` items: `motion.li` with `staggerChildren: 0.05`. Profile card `whileHover={{ y: -2 }}` |
| 2B — Phase 1 stream | 2070–2430 | `ScenePhase1` | `phase1-stream.mp4` | Each agent row: `<AnimatePresence>` icon swap (Loader2 → Check) with `spring({stiffness: 400, damping: 18})`. `motion.li layout` for any reorder |
| 2C — Verdict + citation hover | 2430–2670 | `SceneVerdict` | `verdict-citation.mp4` | `VerdictHeadline` reveal: parent `delayChildren: 0.15, staggerChildren: 0.08`. `CitationLink` hover: `whileHover={{ y: -1 }}`, tooltip via `<AnimatePresence mode="wait">` initial `{opacity: 0, y: 4, scale: 0.96}` |
| 2D — PackPicker click | 2670–2760 | `ScenePackPicker` | `pack-picker.mp4` | 4 cards: `staggerChildren: 0.06`. Each card: `whileHover={{ y: -2 }}` with spring |
| 2E — SessionPack split-pane CV | 2760–3300 | `SceneSessionPack` | `session-pack.mp4` + `ProviderRoutingChip` overlay (frames 100–230 of scene) | Left pane: `motion.div layout` on career-entry cards; cited entry ring via `animate={{ boxShadow: "0 0 0 3px hsl(var(--ring))" }} transition={{ duration: 0.4 }}`. Right pane: nested staggers, `staggerChildren: 0.5` (roles) / `0.18` (bullets), `0.4s` per-bullet fade-in. Total cascade ~2–3s for a 3-role × 4-bullet CV — reads as "writes itself, line by line" |
| 2F — Telegram cameo | 3300–4200 | `SceneTelegram` | `telegram-screencap.mov` | (Real device, recorded via QuickTime — no Motion. Remotion just plays the clip.) |

---

## Act 3 — The Bet (2:20–3:00, frames 4200–5400)

| Beat | Frames | Scene component | Asset | Animation |
|---|---|---|---|---|
| 3A — Sessions list (no cost ticker) | 4200–4860 | `SceneSessions` | `sessions-list.mp4` | (Motion in app) Each session row: `motion.div layout` + `staggerChildren: 0.05`. **Cost field intentionally omitted** — script doesn't reference it |
| 3B — Closing card | 4860–5280 | `ClosingCard` | text + `brand/logomark.svg` + URL | Logomark `spring({fps, frame:frame-4860, config:{damping:14}})` from scale 0.8→1. Text fades in 30 frames after |
| 3C — Hold + master fade | 5280–5400 | (silence + ambient pad tail) | — | `interpolate(frame, [5280, 5400], [1, 0])` on master opacity (in `DemoVideo.tsx`) |

**END CARD** — `trajectory.app · github.com/<your-repo>`

---

## Concrete Remotion Patterns

### `FadeIn` primitive

```tsx
// primitives/FadeIn.tsx
import { interpolate, useCurrentFrame } from "remotion";

interface Props {
  from: number;
  durationInFrames?: number;
  children: React.ReactNode;
}

export const FadeIn: React.FC<Props> = ({ from, durationInFrames = 15, children }) => {
  const frame = useCurrentFrame();
  const opacity = interpolate(frame, [from, from + durationInFrames], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  return <div style={{ opacity }}>{children}</div>;
};
```

### `RejectedStamp` — physics-driven slam

```tsx
// overlays/RejectedStamp.tsx
import { spring, useCurrentFrame, useVideoConfig } from "remotion";

export const RejectedStamp: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const scale = spring({ fps, frame, config: { damping: 8, stiffness: 220 } });

  return (
    <div style={{
      position: "absolute",
      top: "50%",
      left: "50%",
      transform: `translate(-50%, -50%) rotate(-8deg) scale(${1 + (1 - scale) * 0.4})`,
      color: "#e23",
      border: "6px solid #e23",
      padding: "8px 24px",
      fontWeight: 800,
      letterSpacing: 4,
      fontSize: 64,
      fontFamily: "Inter, sans-serif",
    }}>
      REJECTED
    </div>
  );
};
```

### `ProviderRoutingChip` — replaces the cut routing-flicks recording

```tsx
// overlays/ProviderRoutingChip.tsx
import { useCurrentFrame, interpolate } from "remotion";

export const ProviderRoutingChip: React.FC = () => {
  const frame = useCurrentFrame();

  // Slides in from right at frame 100, slides out at frame 240
  const translateX = interpolate(
    frame, [100, 130, 200, 230], [400, 0, 0, 400],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );
  const opacity = interpolate(
    frame, [100, 130, 200, 230], [0, 1, 1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  return (
    <div style={{
      position: "absolute",
      bottom: 80,
      right: 80,
      transform: `translateX(${translateX}px)`,
      opacity,
      padding: "12px 20px",
      backgroundColor: "rgba(255, 255, 255, 0.06)",
      backdropFilter: "blur(12px)",
      border: "0.5px solid rgba(255, 255, 255, 0.15)",
      borderRadius: 12,
      display: "flex",
      alignItems: "center",
      gap: 8,
      fontFamily: "JetBrains Mono, monospace",
      fontSize: 16,
      color: "rgba(255, 255, 255, 0.85)",
      letterSpacing: 0.3,
    }}>
      <span style={{ opacity: 0.6 }}>ATS routing:</span>
      <span>Greenhouse → OpenAI</span>
    </div>
  );
};
```

### Scene wrapping a screen-rec with a caption overlay

```tsx
// scenes/act2/ScenePhase1.tsx
import { AbsoluteFill, OffthreadVideo, Sequence, staticFile } from "remotion";
import { FadeIn } from "../../primitives/FadeIn";

export const ScenePhase1: React.FC = () => (
  <AbsoluteFill>
    <OffthreadVideo
      src={staticFile("screenrec/phase1-stream.mp4")}
      // Optional: speed up if real-world recording exceeds the budget
      // playbackRate={1.2}
    />
    <Sequence from={45} durationInFrames={120}>
      <FadeIn from={0}>
        <div style={{
          position: "absolute",
          bottom: 80,
          left: 80,
          fontSize: 28,
          color: "rgba(255, 255, 255, 0.85)",
          fontFamily: "JetBrains Mono, monospace",
        }}>
          9 agents · live · cited
        </div>
      </FadeIn>
    </Sequence>
  </AbsoluteFill>
);
```

---

## Concrete Motion Patterns (Trajectory Frontend)

All eight Motion patterns are wired into the live frontend. See [`frontend/src/components/`](../frontend/src/components/). Adapted to:
- TypeScript + React 18 + Vite
- TanStack Query for server state, `useReducer`/`useState` for local
- Tailwind + shadcn primitives
- SSE via `streamForwardJob` (POST + manual stream parse, not native EventSource)
- The `completed: Record<string, AgentTiming>` shape (not array) for Phase 1
- The `Citation` discriminated union (`url_snippet | gov_data | career_entry`)
- The `highlightedEntryIds: Set<string>` + `scrollKey: string | null` cross-pane contract in `DeepWork`

Component-by-component:

| Component | Pattern |
|---|---|
| `Phase1Stream` | `motion.ul` + `staggerChildren: 0.06` on mount; `motion.li layout` rows; icon swap via `<AnimatePresence mode="wait">` with spring tick (`stiffness: 400, damping: 18`) |
| `VerdictHeadline` | Parent `motion.div` with `delayChildren: 0.15, staggerChildren: 0.08` for badge → headline → reason groups |
| `CitationLink` | Replaced native `title` with Motion-driven tooltip using `bg-card text-card-foreground` (no `bg-popover` token in this theme); tooltip only renders when `hint !== null`; `whileHover={{ y: -1 }}, whileTap={{ scale: 0.97 }}` on the chip |
| `PackPicker` | Grid `staggerChildren: 0.06`; cards `whileHover={{ y: -2 }}` with spring; `layoutId` morph dropped (router complexity not worth ~0.5s of polish) |
| `DeepWork` (split-pane) | Career entries: `motion.div layout` + `boxShadow` ring via `hsl(var(--ring))`; `scrollIntoView({ behavior: "smooth", block: "center" })` driven by `scrollKey` |
| `CVPreview` (right pane) | **Nested staggers**: roles `staggerChildren: 0.5`, bullets within a role `staggerChildren: 0.18`. Each bullet `motion.button` with `initial={{opacity:0, x:-4}} animate={{opacity:1, x:0}}` over 0.4s. Total cascade ~2–3s for a typical 3-role × 4-bullet CV. **Note:** CV is a single POST, not streamed — the cascade simulates "writes itself, line by line" |
| `SessionList` | `motion.ul` with `staggerChildren: 0.05`; `motion.li layout` for new-session insert; `key={sessions.length}` to replay stagger on count change |
| `ForwardJobForm` submit button | Wrapped in `motion.div` with `whileTap={{ scale: 0.97 }}` (preserves shadcn `Button` styling) |

---

## Production notes

- **770 figure** — verified pre-production; reflects current Applications archive count
- **Tube line** — kept verbatim. The QuickTime screen-cap of Telegram on iPhone carries the implication; the line sells the mobile use-case
- **Voice direction** — Act 1 direct/worn, Act 2 product-confident, Act 3 quiet
- **Capital on Tap status** — verify A-rated on the Sponsor Register CSV the morning of recording
- **CV streaming claim** — the staggered cascade simulates real streaming; the implementation is a single POST. Defensible answer if pushed: "the model generates bullets in order, the frontend reveals them in that order"

## Intentional omissions

The product does more than the script shows. Cut to keep the demo focused:

- Verdict ensemble + deep-research toggle
- Story-bank retrieval weighting
- Batch job queue
- Offer analyser
- Cross-application memory (recruiter interactions, negotiation outcomes)
- Onboarding wizard internals

Each could be a 5–10s cameo if a re-cut is needed — drop a new `Series.Sequence` into `DemoVideo.tsx` with a fresh screen-rec.