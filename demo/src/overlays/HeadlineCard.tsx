import { Img, staticFile } from "remotion";
import { FadeIn } from "../primitives/FadeIn";

interface Props {
  /** Path under public/headlines/ (e.g. "ai-screeners-prefer-ai.png"). */
  image: string;
  /** Optional caption rendered below the image (cite the source). */
  caption?: string;
  /** Frame inside the parent Sequence at which to begin fading in. */
  fadeInFrom?: number;
  /** Frame inside the parent Sequence at which to begin fading out.
   *  Omit to hold to the end of the parent Sequence. */
  fadeOutAt?: number;
}

export const HeadlineCard: React.FC<Props> = ({
  image,
  caption,
  fadeInFrom = 0,
  fadeOutAt,
}) => (
  <FadeIn
    from={fadeInFrom}
    durationInFrames={20}
    to={fadeOutAt}
    toDurationInFrames={15}
    style={{
      position: "absolute",
      inset: 0,
      display: "flex",
      flexDirection: "column",
      alignItems: "center",
      justifyContent: "center",
      gap: 24,
    }}
  >
    <Img
      src={staticFile(`headlines/${image}`)}
      style={{
        maxWidth: "70%",
        maxHeight: "70%",
        boxShadow: "0 24px 48px rgba(0,0,0,0.6)",
        borderRadius: 8,
      }}
    />
    {caption && (
      <p
        style={{
          color: "rgba(255,255,255,0.6)",
          fontFamily: "JetBrains Mono, monospace",
          fontSize: 18,
          letterSpacing: 0.5,
        }}
      >
        {caption}
      </p>
    )}
  </FadeIn>
);
