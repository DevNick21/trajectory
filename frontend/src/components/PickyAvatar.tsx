import { motion, useAnimationControls } from "motion/react";
import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";

export type PickyState = "idle" | "thinking" | "go" | "no_go" | "error";

interface Props {
  state?: PickyState;
  className?: string;
}

export default function PickyAvatar({ state = "idle", className }: Props) {
  const [blink, setBlink] = useState(false);
  const controls = useAnimationControls();

  // Handle blinking logic
  useEffect(() => {
    const blinkInterval = setInterval(() => {
      if (state === "idle") {
        setBlink(true);
        setTimeout(() => setBlink(false), 150);
      }
    }, 4000);
    return () => clearInterval(blinkInterval);
  }, [state]);

  // Drive the body animation through useAnimationControls so reactions
  // and the ambient breathing share a single `animate` prop. Previous
  // version had two animate props on the same motion.div — JSX kept
  // only the last, which silently killed the go/no_go reactions.
  useEffect(() => {
    if (state === "go") {
      controls.start({
        scale: [1, 1.3, 0.9, 1.1, 1],
        rotate: [0, 10, -10, 5, 0],
        borderRadius: "35%",
        transition: { duration: 0.6, ease: "easeOut" },
      });
    } else if (state === "no_go") {
      controls.start({
        scale: [1, 0.8, 1.1, 0.95, 1],
        y: [0, 5, -2, 1, 0],
        borderRadius: "35%",
        transition: { duration: 0.5 },
      });
    } else if (state === "thinking") {
      controls.start({
        scale: [1, 1.05, 1],
        borderRadius: "30% 70% 70% 30% / 30% 30% 70% 70%",
        transition: { duration: 0.3, repeat: Infinity, ease: "easeInOut" },
      });
    } else {
      // idle / error — gentle breathing
      controls.start({
        scale: [1, 1.02, 1],
        borderRadius: "35%",
        transition: { duration: 3, repeat: Infinity, ease: "easeInOut" },
      });
    }
  }, [state, controls]);

  return (
    <div className={cn("relative flex items-center justify-center", className)}>
      {/* The Body - Squishy & Breathing */}
      <motion.div
        initial={false}
        animate={controls}
        className={cn(
          "relative h-full w-full rounded-[inherit] bg-primary flex items-center justify-center shadow-lg",
          state === "no_go" && "bg-destructive",
          state === "go" && "bg-success"
        )}
      >
        {/* The Eye */}
        <div className="relative h-[40%] w-[40%] rounded-full bg-white flex items-center justify-center overflow-hidden">
          {/* Pupil */}
          <motion.div
            className="h-[50%] w-[50%] rounded-full bg-black"
            animate={{
              x: state === "thinking" ? [-4, 4, -4] : 0,
              y: state === "idle" ? [0, 1, 0] : 0,
              scaleY: blink ? 0 : 1,
            }}
            transition={{
              x: { duration: 0.4, repeat: Infinity, ease: "linear" },
              scaleY: { duration: 0.1 },
              y: { duration: 2, repeat: Infinity },
            }}
          />

          {/* Eyelid (Blink) */}
          <motion.div
            className="absolute inset-0 bg-primary"
            initial={{ scaleY: 0 }}
            animate={{ scaleY: blink ? 1 : 0 }}
            style={{ originY: 0 }}
            transition={{ duration: 0.1 }}
          />
        </div>

        {/* Thinking Aura */}
        {state === "thinking" && (
          <motion.div
            className="absolute inset-0 rounded-2xl border-2 border-primary/30"
            animate={{ scale: [1, 1.4], opacity: [0.5, 0] }}
            transition={{ duration: 1, repeat: Infinity }}
          />
        )}
      </motion.div>

      {/* Playful indicator for NO_GO */}
      {state === "no_go" && (
        <motion.span 
          initial={{ opacity: 0, y: 0 }}
          animate={{ opacity: 1, y: -25 }}
          className="absolute text-destructive font-mono font-bold text-xs"
        >
          UGH.
        </motion.span>
      )}
    </div>
  );
}
