import {
  AbsoluteFill,
  Audio,
  Sequence,
  Series,
  staticFile,
  interpolate,
  useCurrentFrame,
} from "remotion";
import { Act1Fatigue } from "./acts/Act1Fatigue";
import { Act2Product } from "./acts/Act2Product";
import { Act3Bet } from "./acts/Act3Bet";

// VO speaking windows. Music ducks inside these, rests outside.
// Tune end-frames once VO files are generated and exact lengths are known.
const VO_WINDOWS: Array<[number, number]> = [
  [0, 1260],
  [1800, 4050],
  [4200, 4920],
];

const MUSIC_BED = 0.18;
const MUSIC_DUCKED = 0.06;

const duckMusic = (frame: number) =>
  VO_WINDOWS.some(([s, e]) => frame >= s && frame < e)
    ? MUSIC_DUCKED
    : MUSIC_BED;

const masterOpacity = (frame: number) =>
  interpolate(frame, [5280, 5400], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

export const DemoVideo: React.FC = () => {
  const frame = useCurrentFrame();

  return (
    <AbsoluteFill
      style={{
        backgroundColor: "#0b0b0c",
        opacity: masterOpacity(frame),
      }}
    >
      <Series>
        <Series.Sequence durationInFrames={1800}>
          <Act1Fatigue />
        </Series.Sequence>
        <Series.Sequence durationInFrames={2400}>
          <Act2Product />
        </Series.Sequence>
        <Series.Sequence durationInFrames={1200}>
          <Act3Bet />
        </Series.Sequence>
      </Series>

      <Audio src={staticFile("music/bed.mp3")} volume={duckMusic} />

      <Sequence from={0}>
        <Audio src={staticFile("vo/act1.mp3")} />
      </Sequence>
      <Sequence from={1800}>
        <Audio src={staticFile("vo/act2.mp3")} />
      </Sequence>
      <Sequence from={4200}>
        <Audio src={staticFile("vo/act3.mp3")} />
      </Sequence>
    </AbsoluteFill>
  );
};
