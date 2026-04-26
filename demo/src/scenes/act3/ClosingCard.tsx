import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";

/** 4860–5400 (2:42–3:00). Final card: logomark draws itself in, then
 *  wordmark + tag + URL fade in. Hold to frame 5400; the master fade
 *  in DemoVideo.tsx (5280–5400) takes the screen to black.
 *
 *  The logomark SVG is inlined (not loaded via <Img>) because Remotion
 *  renders headlessly, frame-by-frame — SMIL <animate> tags don't
 *  progress between frames. The draw-on motion is ported to
 *  interpolate() driving strokeDashoffset; the dot pulses are sine
 *  waves driven by useCurrentFrame(). */
export const ClosingCard: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Wrapper spring (lifts the whole logomark in)
  const logoScale = spring({
    fps,
    frame,
    config: { damping: 14, stiffness: 110, mass: 0.8 },
  });
  const logoOpacity = interpolate(frame, [0, 18], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  // Path draw-on. pathLength=1 normalises so we can drive strokeDashoffset
  // 1 → 0 in lockstep with progress. Path 1 draws over frames 6–60;
  // path 2 trails by 15 frames (matches the SMIL begin="0.5s").
  const drawT1 = interpolate(frame, [6, 60], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const drawT2 = interpolate(frame, [21, 75], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  // Dot pulse: 5 ↔ 7 over a 45-frame (1.5s) cycle, with 15-frame phase
  // offsets per dot — matches the original SMIL begin offsets.
  const pulse = (offsetFrames: number) => {
    const phase = (((frame + offsetFrames) % 45) / 45) * Math.PI * 2;
    return 5 + Math.sin(phase) + 1;
  };

  const textOpacity = interpolate(frame, [30, 60], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const tagOpacity = interpolate(frame, [90, 120], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <AbsoluteFill
      style={{
        backgroundColor: "#0b0b0c",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: 32,
      }}
    >
      <div
        style={{
          transform: `scale(${0.8 + logoScale * 0.2})`,
          opacity: logoOpacity,
        }}
      >
        <svg
          width={200}
          height={200}
          viewBox="0 0 200 200"
          xmlns="http://www.w3.org/2000/svg"
        >
          <defs>
            <linearGradient
              id="trajectoryGradient1"
              x1="0%"
              y1="0%"
              x2="100%"
              y2="100%"
            >
              <stop offset="0%" stopColor="rgb(60,150,255)" />
              <stop offset="100%" stopColor="rgb(0,200,200)" />
            </linearGradient>
            <linearGradient
              id="trajectoryGradient2"
              x1="0%"
              y1="0%"
              x2="100%"
              y2="100%"
            >
              <stop offset="0%" stopColor="rgb(0,200,200)" />
              <stop offset="100%" stopColor="rgb(60,150,255)" />
            </linearGradient>
          </defs>

          <path
            d="M 30 170 Q 70 110 100 100 T 170 30"
            stroke="url(#trajectoryGradient1)"
            strokeWidth={8}
            fill="none"
            strokeLinecap="round"
            strokeLinejoin="round"
            pathLength={1}
            strokeDasharray={1}
            strokeDashoffset={1 - drawT1}
          />
          <path
            d="M 40 160 Q 80 120 110 110 T 160 40"
            stroke="url(#trajectoryGradient2)"
            strokeWidth={4}
            fill="none"
            strokeLinecap="round"
            strokeLinejoin="round"
            opacity={0.7}
            pathLength={1}
            strokeDasharray={1}
            strokeDashoffset={1 - drawT2}
          />

          <circle
            cx={30}
            cy={170}
            r={pulse(0)}
            fill="white"
            opacity={drawT1}
          />
          <circle
            cx={100}
            cy={100}
            r={pulse(15)}
            fill="white"
            opacity={drawT1}
          />
          <circle
            cx={170}
            cy={30}
            r={pulse(30)}
            fill="white"
            opacity={drawT1}
          />
        </svg>
      </div>

      <h1
        style={{
          opacity: textOpacity,
          fontFamily: "Inter, sans-serif",
          fontSize: 72,
          fontWeight: 700,
          color: "#fafafa",
          letterSpacing: -2,
          margin: 0,
        }}
      >
        Trajectory
      </h1>

      <p
        style={{
          opacity: tagOpacity,
          fontFamily: "JetBrains Mono, monospace",
          fontSize: 22,
          color: "rgba(255,255,255,0.6)",
          letterSpacing: 1,
          margin: 0,
        }}
      >
        open source · built on Opus 4.7
      </p>
      <p
        style={{
          opacity: tagOpacity,
          fontFamily: "JetBrains Mono, monospace",
          fontSize: 18,
          color: "rgba(255,255,255,0.45)",
          letterSpacing: 0.5,
          margin: 0,
        }}
      >
        github.com/DevNick21/trajectory
      </p>
    </AbsoluteFill>
  );
};
