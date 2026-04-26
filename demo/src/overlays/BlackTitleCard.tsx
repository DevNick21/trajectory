import { interpolate, useCurrentFrame } from "remotion";

interface Props {
  /** Full text. Letters reveal one at a time via slice() between
   *  `typeFrom` and `typeFrom + typeDuration`. */
  text: string;
  typeFrom?: number;
  typeDurationInFrames?: number;
  fontSize?: number;
}

/** Black background, single line of white text typed letter-by-letter.
 *  Used for the Act 1 closer ("That's not a CV problem...") and could
 *  drop into Act 3 if needed. */
export const BlackTitleCard: React.FC<Props> = ({
  text,
  typeFrom = 30,
  typeDurationInFrames = 210,
  fontSize = 56,
}) => {
  const frame = useCurrentFrame();
  const charsRevealed = Math.floor(
    interpolate(
      frame,
      [typeFrom, typeFrom + typeDurationInFrames],
      [0, text.length],
      { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
    ),
  );
  const visible = text.slice(0, charsRevealed);
  const cursorVisible = frame > typeFrom && frame < typeFrom + typeDurationInFrames + 30
    ? Math.floor(frame / 15) % 2 === 0
    : false;

  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        backgroundColor: "#0b0b0c",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: "0 120px",
      }}
    >
      <p
        style={{
          color: "#fafafa",
          fontFamily: "Inter, sans-serif",
          fontSize,
          fontWeight: 600,
          letterSpacing: -0.5,
          lineHeight: 1.25,
          textAlign: "center",
          maxWidth: 1400,
        }}
      >
        {visible}
        {cursorVisible && (
          <span style={{ color: "#8b5cf6", marginLeft: 4 }}>▍</span>
        )}
      </p>
    </div>
  );
};
