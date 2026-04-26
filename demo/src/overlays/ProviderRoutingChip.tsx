import { interpolate, useCurrentFrame } from "remotion";

interface Props {
  /** Frame inside the parent Sequence at which to start sliding in. */
  slideInAt?: number;
  /** Frame at which to start sliding out. */
  slideOutAt?: number;
}

/** Floating "ATS routing: Greenhouse → OpenAI" chip overlaid on the
 *  SessionPack screen-rec. Replaces the cut routing-flicks recording —
 *  visible engineering evidence without an extra take. */
export const ProviderRoutingChip: React.FC<Props> = ({
  slideInAt = 100,
  slideOutAt = 200,
}) => {
  const frame = useCurrentFrame();

  const translateX = interpolate(
    frame,
    [slideInAt, slideInAt + 30, slideOutAt, slideOutAt + 30],
    [400, 0, 0, 400],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
  );
  const opacity = interpolate(
    frame,
    [slideInAt, slideInAt + 30, slideOutAt, slideOutAt + 30],
    [0, 1, 1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
  );

  return (
    <div
      style={{
        position: "absolute",
        bottom: 80,
        right: 80,
        transform: `translateX(${translateX}px)`,
        opacity,
        padding: "12px 20px",
        backgroundColor: "rgba(255, 255, 255, 0.06)",
        backdropFilter: "blur(12px)",
        WebkitBackdropFilter: "blur(12px)",
        border: "0.5px solid rgba(255, 255, 255, 0.15)",
        borderRadius: 12,
        display: "flex",
        alignItems: "center",
        gap: 8,
        fontFamily: "JetBrains Mono, monospace",
        fontSize: 16,
        color: "rgba(255, 255, 255, 0.85)",
        letterSpacing: 0.3,
      }}
    >
      <span style={{ opacity: 0.6 }}>ATS routing:</span>
      <span>Greenhouse → OpenAI</span>
    </div>
  );
};
