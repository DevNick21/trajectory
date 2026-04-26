import { AbsoluteFill } from "remotion";
import { HeadlineCard } from "../../overlays/HeadlineCard";

/** 0–180 (0:00–0:06). First headline fades in cold against pure black.
 *  No VO yet — first VO line lands at frame ~30 over the headline. */
export const HeadlineColdOpen: React.FC = () => (
  <AbsoluteFill style={{ backgroundColor: "#0b0b0c" }}>
    <HeadlineCard
      image="ai-screeners-prefer-ai.png"
      caption="Source: anthropic.com / studies cited in Act 1 brief"
      fadeInFrom={0}
    />
  </AbsoluteFill>
);
