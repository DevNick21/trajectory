import { Series } from "remotion";
import { SceneSessions } from "../scenes/act3/SceneSessions";
import { ClosingCard } from "../scenes/act3/ClosingCard";

// Frames 4200–5400 (40s).
//   4200–4860 SceneSessions  (sessions-list.mp4 + held last frame for VO)
//   4860–5400 ClosingCard    (logomark + URL + master fade in DemoVideo)
export const Act3Bet: React.FC = () => (
  <Series>
    <Series.Sequence durationInFrames={660}>
      <SceneSessions />
    </Series.Sequence>
    <Series.Sequence durationInFrames={540}>
      <ClosingCard />
    </Series.Sequence>
  </Series>
);
