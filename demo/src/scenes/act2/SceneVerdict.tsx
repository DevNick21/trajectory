import { AbsoluteFill, OffthreadVideo, Sequence, staticFile } from "remotion";
import { FadeIn } from "../../primitives/FadeIn";

/** 2430–2670 (1:21–1:29). GO verdict for Capital on Tap with
 *  citations hovered. The recording has the VerdictHeadline cascade
 *  and the CitationLink hover tooltip — we add a small label calling
 *  out the citation discipline. */
export const SceneVerdict: React.FC = () => (
  <AbsoluteFill>
    <OffthreadVideo src={staticFile("screenrec/verdict-citation.mp4")} />
    <Sequence from={60} durationInFrames={150}>
      <FadeIn
        from={0}
        style={{
          position: "absolute",
          top: 80,
          right: 80,
          fontSize: 24,
          color: "rgba(139, 92, 246, 0.95)",
          fontFamily: "JetBrains Mono, monospace",
          padding: "8px 16px",
          backgroundColor: "rgba(0,0,0,0.5)",
          backdropFilter: "blur(8px)",
          borderRadius: 8,
          border: "1px solid rgba(139, 92, 246, 0.3)",
        }}
      >
        Every line clickable · gov.uk-grounded
      </FadeIn>
    </Sequence>
  </AbsoluteFill>
);
