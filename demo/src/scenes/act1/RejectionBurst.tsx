import { AbsoluteFill, Img, Sequence, Series, staticFile } from "remotion";
import { RejectedStamp } from "../../overlays/RejectedStamp";

// 360–810 (0:12–0:27). Six inbox stills slam in with REJECTED stamps;
// cuts accelerate. 75-frame children in a Series — totals 450 frames.
//
// Cuts: 80, 70, 60, 50, 40, 30 = 330; pad with a final 120-frame
// black snap to fill the 450 budget. Inboxes hold 1.0s → 0.4s as the
// cuts compress, mirroring the user's accelerating dread.
const SLIDE_DURATIONS = [80, 70, 60, 50, 40, 30] as const;

interface InboxProps {
  index: number;
}

const InboxSlide: React.FC<InboxProps> = ({ index }) => (
  <AbsoluteFill style={{ backgroundColor: "#111" }}>
    <Img
      src={staticFile(`rejections/inbox-${index}.png`)}
      style={{
        width: "100%",
        height: "100%",
        objectFit: "cover",
        opacity: 0.7,
      }}
    />
    <Sequence from={4}>
      <RejectedStamp />
    </Sequence>
  </AbsoluteFill>
);

const BlackSnap: React.FC = () => (
  <AbsoluteFill style={{ backgroundColor: "#000" }} />
);

export const RejectionBurst: React.FC = () => (
  <Series>
    {SLIDE_DURATIONS.map((duration, i) => (
      <Series.Sequence key={i} durationInFrames={duration}>
        <InboxSlide index={i + 1} />
      </Series.Sequence>
    ))}
    <Series.Sequence durationInFrames={120}>
      <BlackSnap />
    </Series.Sequence>
  </Series>
);
