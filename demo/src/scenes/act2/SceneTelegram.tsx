import { AbsoluteFill, OffthreadVideo, Sequence, staticFile } from "remotion";
import { FadeIn } from "../../primitives/FadeIn";

/** 3780–4200 (2:06–2:20). 14s. Real iPhone screen-cap of Telegram.
 *
 *  Recording approach (option B — locked): show the bot bubble with
 *  the verdict ALREADY received. No Phase 1 reveal, no live forward —
 *  the web pane already proved the streaming behaviour, Telegram just
 *  needs to land "same orchestrator, mobile-native". Short scroll
 *  through the verdict bubble + maybe a citation tap is plenty for 14s.
 *
 *  Caption fades in mid-scene. VO ends at frame 4050 (270 in scene-local
 *  frames); last 150 frames of Telegram play silent under swelling music. */
export const SceneTelegram: React.FC = () => (
  <AbsoluteFill style={{ backgroundColor: "#0b0b0c" }}>
    <OffthreadVideo
      src={staticFile("screenrec/telegram-screencap.mov")}
      // Recording came back at 16s; scene budget is 14s. 16/14 ≈ 1.143×
      // is below perceptual threshold for slow scroll motion. Swap to
      // playbackRate={1} + trim the .mov to 14s if you'd rather keep
      // native speed.
      playbackRate={16 / 14}
      style={{
        width: "100%",
        height: "100%",
        objectFit: "contain",
      }}
    />
    <Sequence from={60} durationInFrames={180}>
      <FadeIn
        from={0}
        style={{
          position: "absolute",
          top: 80,
          left: 80,
          fontSize: 28,
          color: "rgba(255, 255, 255, 0.85)",
          fontFamily: "JetBrains Mono, monospace",
          padding: "8px 16px",
          backgroundColor: "rgba(0,0,0,0.5)",
          backdropFilter: "blur(8px)",
          borderRadius: 8,
        }}
      >
        Same orchestrator · forwarded from the Tube
      </FadeIn>
    </Sequence>
  </AbsoluteFill>
);
