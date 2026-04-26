import { Composition } from "remotion";
import { DemoVideo } from "./DemoVideo";

export const RemotionRoot: React.FC = () => (
  <>
    <Composition
      id="trajectory-demo"
      component={DemoVideo}
      durationInFrames={5400}
      fps={30}
      width={1920}
      height={1080}
    />
  </>
);
