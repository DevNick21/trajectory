import { interpolate, useCurrentFrame } from "remotion";

interface Props {
  from: number;
  durationInFrames?: number;
  distance?: number;
  children: React.ReactNode;
  style?: React.CSSProperties;
}

export const SlideUp: React.FC<Props> = ({
  from,
  durationInFrames = 20,
  distance = 24,
  children,
  style,
}) => {
  const frame = useCurrentFrame();

  const opacity = interpolate(
    frame,
    [from, from + durationInFrames],
    [0, 1],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
  );
  const translateY = interpolate(
    frame,
    [from, from + durationInFrames],
    [distance, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
  );

  return (
    <div style={{ ...style, opacity, transform: `translateY(${translateY}px)` }}>
      {children}
    </div>
  );
};
