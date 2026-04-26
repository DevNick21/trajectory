import { interpolate, useCurrentFrame } from "remotion";

interface Waypoint {
  frame: number;
  x: number;
  y: number;
}

interface Props {
  /** Sorted by frame ascending. Linear interpolation between waypoints. */
  path: Waypoint[];
  /** Optional click pulse — circle expands at the given frame. */
  clickAt?: number;
}

/** Animated cursor sprite for screen-rec inserts where you need to
 *  point at something the recording missed. Most scenes won't need this
 *  — the live screen-recs already have a real cursor. */
export const Cursor: React.FC<Props> = ({ path, clickAt }) => {
  const frame = useCurrentFrame();
  if (path.length === 0) return null;

  const frames = path.map((p) => p.frame);
  const xs = path.map((p) => p.x);
  const ys = path.map((p) => p.y);

  const x = interpolate(frame, frames, xs, {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const y = interpolate(frame, frames, ys, {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  const clickScale =
    clickAt !== undefined
      ? interpolate(frame, [clickAt, clickAt + 12], [0, 2.5], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
        })
      : 0;
  const clickOpacity =
    clickAt !== undefined
      ? interpolate(frame, [clickAt, clickAt + 18], [0.5, 0], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
        })
      : 0;

  return (
    <>
      {clickAt !== undefined && (
        <div
          style={{
            position: "absolute",
            left: x - 20,
            top: y - 20,
            width: 40,
            height: 40,
            borderRadius: 20,
            background: "rgba(139, 92, 246, 0.4)",
            transform: `scale(${clickScale})`,
            opacity: clickOpacity,
            pointerEvents: "none",
          }}
        />
      )}
      <div
        style={{
          position: "absolute",
          left: x,
          top: y,
          width: 0,
          height: 0,
          borderLeft: "12px solid transparent",
          borderRight: "12px solid transparent",
          borderTop: "20px solid #fff",
          transform: "rotate(-30deg)",
          filter: "drop-shadow(0 2px 4px rgba(0,0,0,0.5))",
          pointerEvents: "none",
        }}
      />
    </>
  );
};
