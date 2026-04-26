# Trajectory — 3-minute demo (Remotion)

Renders the hackathon submission video as a single 1920×1080 @ 30fps `.mp4`. Source-of-truth spec: [`../docs/demo_script.md`](../docs/demo_script.md).

## Quickstart

```bash
cd demo
npm install
npm run dev          # remotion preview — scrub frames live in the browser
npm run build        # final render → out/trajectory-demo.mp4 (CRF 18)
npm run build:draft  # faster draft render (CRF 28) for iteration
```

## What's wired vs. what you provide

| Area | State |
| --- | --- |
| Composition (`src/`) | ✅ Wired. All 13 scenes, 4 overlays, 3 primitives, top-level `DemoVideo`. |
| Frame budgets | ✅ Wired (5400 frames total = 3:00 @ 30fps). Tune `VO_WINDOWS` in `DemoVideo.tsx` after recording VO. |
| Public assets | ⏳ You generate / capture. See per-folder `README.md` in `public/*` for filenames + specs. |

Source spec: [`../docs/demo_script.md`](../docs/demo_script.md). Don't edit composition logic without re-checking that doc — the VO timings, scene names, and frame counts are interlocked.

## Dependencies

Vanilla Remotion 4. No FFmpeg side-car install needed (Remotion bundles it). First `npm install` will pull a Chromium for headless rendering (~150 MB).

## Asset checklist before render

- [ ] `public/vo/act1.mp3` `act2.mp3` `act3.mp3`
- [ ] `public/music/bed.mp3`
- [ ] `public/screenrec/{dashboard,phase1-stream,verdict-citation,pack-picker,session-pack,sessions-list}.mp4`
- [ ] `public/screenrec/telegram-screencap.mov`
- [ ] `public/headlines/{ai-screeners-prefer-ai,ai-cv-instantly}.png`
- [ ] `public/rejections/inbox-{1..6}.png`
- [ ] `public/brand/logomark.svg`
- [ ] Sponsor Register CSV check — Capital on Tap A-rated on recording day

## Tuning after VO is recorded

1. Drop `act1.mp3`, `act2.mp3`, `act3.mp3` into `public/vo/`.
2. Open the file in any audio editor — note the exact length of each take in seconds.
3. Convert to frames: `seconds * 30 = end_frame`.
4. Update the second value of each tuple in `VO_WINDOWS` in `src/DemoVideo.tsx` so music ducking matches actual VO duration. (E.g. if Act 1 VO is 35.4s, set `[0, 1062]`.)
5. Run `npm run dev` and scrub Act boundaries. If a beat lands too early/late, adjust the matching `Series.Sequence durationInFrames` in the relevant `acts/Act*.tsx`.

## Known intentional simplifications

- **CV cascade is not real streaming.** The CV API returns the full `CVOutput` in one POST; the Motion stagger in `frontend/src/components/CVPreview.tsx` simulates token-by-token reveal. The "writes itself, line by line" VO line is supported by this perceived behaviour.
- **`ProviderRoutingChip`** replaces the cut routing-flicks recording. It overlays `session-pack.mp4` to land the multi-provider claim without an extra take.
- **No cost ticker** in `SceneSessions`. The script does not reference cost; the field is intentionally omitted.
