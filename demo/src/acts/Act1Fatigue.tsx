import { Series } from "remotion";
import { HeadlineColdOpen } from "../scenes/act1/HeadlineColdOpen";
import { BigStat770 } from "../scenes/act1/BigStat770";
import { RejectionBurst } from "../scenes/act1/RejectionBurst";
import { HeadlineSecond } from "../scenes/act1/HeadlineSecond";
import { TrustProblemCard } from "../scenes/act1/TrustProblemCard";

// Frames 0–1800 (60s). Beat budget locked to actual Act 1 VO (42s):
//   0–180     HeadlineColdOpen    (cold open)
//   180–360   BigStat770          (count-up to 770)
//   360–810   RejectionBurst      (6 inboxes, accelerating)
//   810–1110  HeadlineSecond      (single article-thumbnail card; the
//                                  recruiters-spot image was cut, so just
//                                  ai-cv-instantly.png lands here)
//   1110–1800 TrustProblemCard    (690 frames — typewriter reveals 1110–1260
//                                  in sync with the closing VO line
//                                  "Trajectory doesn't fix the job market...";
//                                  card holds visible 1260–1800)
//
// VO ends at frame 1260. Card stays visible 1260–1800 (18s held) so the
// final line breathes before Act 2 cuts in. Music bed swells in that
// silence (VO_WINDOWS[0] = [0,1260]; duck releases at 1260).
export const Act1Fatigue: React.FC = () => (
  <Series>
    <Series.Sequence durationInFrames={180}>
      <HeadlineColdOpen />
    </Series.Sequence>
    <Series.Sequence durationInFrames={180}>
      <BigStat770 />
    </Series.Sequence>
    <Series.Sequence durationInFrames={450}>
      <RejectionBurst />
    </Series.Sequence>
    <Series.Sequence durationInFrames={300}>
      <HeadlineSecond />
    </Series.Sequence>
    <Series.Sequence durationInFrames={690}>
      <TrustProblemCard />
    </Series.Sequence>
  </Series>
);
