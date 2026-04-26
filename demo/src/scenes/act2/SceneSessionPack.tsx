import { AbsoluteFill, OffthreadVideo, Sequence, staticFile } from "remotion";
import { ProviderRoutingChip } from "../../overlays/ProviderRoutingChip";

/** 2760–3300 (1:32–1:50). Split-pane Deep Work view — career entries
 *  ringing on the left as bullets cascade in on the right. The
 *  ProviderRoutingChip overlays mid-scene to land the multi-provider
 *  ATS-routing claim without an extra take. */
export const SceneSessionPack: React.FC = () => (
  <AbsoluteFill>
    <OffthreadVideo src={staticFile("screenrec/session-pack.mp4")} />
    <Sequence from={0} durationInFrames={540}>
      <ProviderRoutingChip slideInAt={140} slideOutAt={260} />
    </Sequence>
  </AbsoluteFill>
);
