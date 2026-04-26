import { Series } from "remotion";
import { SceneDashboard } from "../scenes/act2/SceneDashboard";
import { ScenePhase1 } from "../scenes/act2/ScenePhase1";
import { SceneVerdict } from "../scenes/act2/SceneVerdict";
import { ScenePackPicker } from "../scenes/act2/ScenePackPicker";
import { SceneSessionPack } from "../scenes/act2/SceneSessionPack";
import { SceneTelegram } from "../scenes/act2/SceneTelegram";

// Frames 1800–4200 (80s). Beat boundaries locked to actual Act 2 VO
// (75s file). Each cut lands at the end of a VO line:
//   1800–2160 SceneDashboard    (dashboard.mp4)         12s — "…the whole interface."
//   2160–2610 ScenePhase1       (phase1-stream.mp4)     15s — "…No AI slop."
//   2610–3060 SceneVerdict      (verdict-citation.mp4)  15s — "…No invention."
//   3060–3150 ScenePackPicker   (pack-picker.mp4)        3s — "Pick a pack."
//   3150–3780 SceneSessionPack  (session-pack.mp4)      21s — "…what's already there."
//                               + ProviderRoutingChip overlay (scene-local 140→260)
//   3780–4200 SceneTelegram     (telegram-screencap.mov) 14s — VO ends 4050; 5s silent tail
//
// VO ends at frame 4050. Last 150 frames of Telegram play silent (or held
// last frame); music bed swells from 0.06 → 0.18 over that tail.
export const Act2Product: React.FC = () => (
  <Series>
    <Series.Sequence durationInFrames={360}>
      <SceneDashboard />
    </Series.Sequence>
    <Series.Sequence durationInFrames={450}>
      <ScenePhase1 />
    </Series.Sequence>
    <Series.Sequence durationInFrames={450}>
      <SceneVerdict />
    </Series.Sequence>
    <Series.Sequence durationInFrames={90}>
      <ScenePackPicker />
    </Series.Sequence>
    <Series.Sequence durationInFrames={630}>
      <SceneSessionPack />
    </Series.Sequence>
    <Series.Sequence durationInFrames={420}>
      <SceneTelegram />
    </Series.Sequence>
  </Series>
);
