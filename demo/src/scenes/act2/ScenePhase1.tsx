import { AbsoluteFill, OffthreadVideo, Sequence, staticFile } from "remotion";
import { FadeIn } from "../../primitives/FadeIn";

/** 2070–2430 (1:09–1:21). Phase 1 fan-out — 9 agents, parallel,
 *  cited. The recording has Motion-driven row reveals + spring tick
 *  pops on agent_complete. We layer a "9 agents · live · cited"
 *  caption mid-scene to anchor the VO line. */
export const ScenePhase1: React.FC = () => (
  <AbsoluteFill>
    <OffthreadVideo
      src={staticFile("screenrec/phase1-stream.mp4")}
      // playbackRate={1.2}  // uncomment if real recording exceeds 12s
    />
    <Sequence from={45} durationInFrames={150}>
      <FadeIn
        from={0}
        style={{
          position: "absolute",
          bottom: 80,
          left: 80,
          fontSize: 28,
          color: "rgba(255, 255, 255, 0.85)",
          fontFamily: "JetBrains Mono, monospace",
          padding: "8px 16px",
          backgroundColor: "rgba(0,0,0,0.4)",
          backdropFilter: "blur(8px)",
          borderRadius: 8,
        }}
      >
        9 agents · live · cited
      </FadeIn>
    </Sequence>
  </AbsoluteFill>
);
