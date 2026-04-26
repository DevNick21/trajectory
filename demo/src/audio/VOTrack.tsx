import { Audio, staticFile } from "remotion";

interface Props {
  /** Filename under public/vo/ (e.g. "act1.mp3"). */
  src: string;
  /** Per-act volume override. Default 1.0 — VO is recorded at target level. */
  volume?: number;
}

/** Thin wrapper around <Audio> for the per-act VO files. Kept as its
 *  own primitive so future changes (e.g. compressor / limiter sidechain)
 *  have one place to land. */
export const VOTrack: React.FC<Props> = ({ src, volume = 1 }) => (
  <Audio src={staticFile(`vo/${src}`)} volume={volume} />
);
