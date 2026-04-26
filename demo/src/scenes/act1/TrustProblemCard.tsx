import { AbsoluteFill } from "remotion";
import { BlackTitleCard } from "../../overlays/BlackTitleCard";

/** 1110–1800 (0:37–1:00). Typewriter reveal of the recorded Act 1 closer:
 *  "Trajectory doesn't fix the job market. It helps you navigate it."
 *
 *  Timing locked to actual VO: line begins at 0:37 (demo frame 1110 =
 *  scene local frame 0), ends at 0:42 (demo frame 1260 = scene local
 *  frame 150). Reveal happens over 150 frames in lockstep with audio.
 *  Card holds visible 1260–1800 (18s) so the line breathes; music bed
 *  swells in that silence. */
export const TrustProblemCard: React.FC = () => (
  <AbsoluteFill>
    <BlackTitleCard
      text="Trajectory doesn't fix the job market. It helps you navigate it."
      typeFrom={0}
      typeDurationInFrames={150}
      fontSize={56}
    />
  </AbsoluteFill>
);
