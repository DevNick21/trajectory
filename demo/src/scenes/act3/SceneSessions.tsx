import { AbsoluteFill, OffthreadVideo, staticFile } from "remotion";

/** 4200–4860 (2:20–2:42). Populated session list, no cost ticker.
 *  Holds for ~6s of silence before the "never auto-apply" VO line
 *  begins, so the eye lingers on the implied work-product. */
export const SceneSessions: React.FC = () => (
  <AbsoluteFill style={{ backgroundColor: "#0b0b0c" }}>
    <OffthreadVideo
      src={staticFile("screenrec/sessions-list.mp4")}
      // The screenrec is short; if it ends before this scene does,
      // Remotion holds the last frame automatically when looped:false
      // (default). For a "freeze on last frame" feel, re-export the
      // recording with 1s of held tail or rely on default behaviour.
    />
  </AbsoluteFill>
);
