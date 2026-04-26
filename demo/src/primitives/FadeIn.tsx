import { interpolate, useCurrentFrame } from "remotion";

interface Props {
  from: number;
  durationInFrames?: number;
  to?: number;
  toDurationInFrames?: number;
  children: React.ReactNode;
  style?: React.CSSProperties;
}

export const FadeIn: React.FC<Props> = ({
  from,
  durationInFrames = 15,
  to,
  toDurationInFrames = 15,
  children,
  style,
}) => {
  const frame = useCurrentFrame();

  const fadeOutFrames =
    to !== undefined
      ? interpolate(frame, [to, to + toDurationInFrames], [1, 0], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
        })
      : 1;

  const fadeIn = interpolate(
    frame,
    [from, from + durationInFrames],
    [0, 1],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
  );

  return <div style={{ ...style, opacity: fadeIn * fadeOutFrames }}>{children}</div>;
};
