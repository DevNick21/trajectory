import { spring, useCurrentFrame, useVideoConfig } from "remotion";

/** Physics-driven slam-in stamp for the rejection burst. Used per-inbox
 *  in RejectionBurst — each child sequence resets `frame` to 0 inside
 *  its own Sequence, so the stamp animates from scratch on every cut. */
export const RejectedStamp: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const scale = spring({
    fps,
    frame,
    config: { damping: 8, stiffness: 220 },
  });

  return (
    <div
      style={{
        position: "absolute",
        top: "50%",
        left: "50%",
        transform: `translate(-50%, -50%) rotate(-8deg) scale(${1 + (1 - scale) * 0.4})`,
        color: "#e23",
        border: "6px solid #e23",
        padding: "8px 24px",
        fontWeight: 800,
        letterSpacing: 4,
        fontSize: 64,
        fontFamily: "Inter, sans-serif",
        textTransform: "uppercase",
        opacity: scale,
      }}
    >
      Rejected
    </div>
  );
};
