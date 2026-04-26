import { AbsoluteFill, OffthreadVideo, staticFile } from "remotion";

/** 2670–2760 (1:29–1:32). 3 seconds — barely a beat. Just plays
 *  pack-picker.mp4: stagger reveal of the 4 cards + click on one.
 *  No Remotion overlay; the recording does all the work. */
export const ScenePackPicker: React.FC = () => (
  <AbsoluteFill>
    <OffthreadVideo src={staticFile("screenrec/pack-picker.mp4")} />
  </AbsoluteFill>
);
