import { AbsoluteFill, OffthreadVideo, Sequence, staticFile } from "remotion";
import { FadeIn } from "../../primitives/FadeIn";

/** 1800–2070 (1:00–1:09). Onboarded dashboard — sessions list visible,
 *  user pastes a URL into ForwardJobForm. The Motion staggers in the
 *  recording carry the in-app animation; we add a single caption tag. */
export const SceneDashboard: React.FC = () => (
  <AbsoluteFill>
    <OffthreadVideo src={staticFile("screenrec/dashboard.mp4")} />
    <Sequence from={45} durationInFrames={150}>
      <FadeIn
        from={0}
        style={{
          position: "absolute",
          top: 80,
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
        Onboarded once · style profile + career history
      </FadeIn>
    </Sequence>
  </AbsoluteFill>
);
