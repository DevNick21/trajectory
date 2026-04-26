import { AbsoluteFill, spring, useCurrentFrame, useVideoConfig } from "remotion";

/** 180–360 (0:06–0:12). Procedural number animation — counts up from
 *  0 to 770 with a spring, label below. No external asset needed. */
export const BigStat770: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Spring from 0→1 over the first ~60 frames; multiply by 770.
  const progress = spring({
    fps,
    frame,
    config: { damping: 18, stiffness: 90, mass: 0.9 },
  });
  const value = Math.round(progress * 770);

  return (
    <AbsoluteFill
      style={{
        backgroundColor: "#0b0b0c",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: 24,
      }}
    >
      <span
        style={{
          fontFamily: "Inter, sans-serif",
          fontSize: 320,
          fontWeight: 700,
          color: "#fafafa",
          letterSpacing: -8,
          fontVariantNumeric: "tabular-nums",
          lineHeight: 1,
        }}
      >
        {value.toLocaleString("en-GB")}
      </span>
      <span
        style={{
          fontFamily: "Inter, sans-serif",
          fontSize: 36,
          color: "rgba(255,255,255,0.5)",
          letterSpacing: 4,
          textTransform: "uppercase",
        }}
      >
        applications · one year · still searching
      </span>
    </AbsoluteFill>
  );
};
