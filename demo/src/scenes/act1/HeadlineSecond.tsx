import { AbsoluteFill, Sequence } from "remotion";
import { HeadlineCard } from "../../overlays/HeadlineCard";

// 810–1110 inside Act 1 (a 300-frame slot, 10s). Single headline —
// previously a pair, but the second source-image was cut.
//
// VO underneath: "...Hiring managers bin them on sight... Use A-I,
// you clear the bot, and lose the human. Don't use A-I, you drown
// in the volume." Closing-line typewriter card cuts in at frame 1110.
//
// Layout (local frames):
//   0–30    brief black hold
//   30–280  ai-cv-instantly.png  (fade in 30–50, hold, fade out 260–280)
//   280–300 black tail before TrustProblemCard
export const HeadlineSecond: React.FC = () => (
  <AbsoluteFill style={{ backgroundColor: "#0b0b0c" }}>
    <Sequence from={30} durationInFrames={250}>
      <HeadlineCard
        image="ai-cv-instantly.png"
        caption="Hiring managers bin them on sight"
        fadeInFrom={0}
        fadeOutAt={230}
      />
    </Sequence>
  </AbsoluteFill>
);
