import { motion, AnimatePresence } from "motion/react";
import { cn } from "@/lib/utils";

export type PickyState = "idle" | "thinking" | "go" | "no_go" | "error" | "scrutinizing";

interface Props {
  state?: PickyState;
  className?: string;
  size?: "sm" | "md" | "lg";
}

export default function PickyAvatar({ state = "idle", className }: Props) {
  const isThinking = state === "thinking" || state === "scrutinizing";

  // Animation variants for the Fox parts
  const headVariants = {
    idle: { rotate: 0, y: 0 },
    scrutinizing: { rotate: [-3, 3, -3], transition: { repeat: Infinity, duration: 2 } },
    thinking: { rotate: [0, -5, 5, 0], transition: { repeat: Infinity, duration: 2 } },
    go: { y: -5, rotate: 0, scale: 1.05 },
    no_go: { rotate: 15, y: 2 },
    error: { x: [-2, 2, -2, 2, 0], transition: { duration: 0.2, repeat: 5 } }
  };

  const earVariants = {
    idle: { rotate: 0 },
    scrutinizing: { rotate: [-5, 5, -5], transition: { repeat: Infinity, duration: 1.5 } },
    thinking: { rotate: [0, -10, 0], transition: { repeat: Infinity, duration: 1, delay: 0.5 } },
    no_go: { rotate: -20 }
  };

  const monocleVariants = {
    idle: { opacity: 0.4, scale: 1 },
    scrutinizing: { 
      opacity: [0.4, 1, 0.6], 
      scale: [1, 1.15, 1],
      transition: { repeat: Infinity, duration: 1.2 } 
    },
    thinking: { 
      opacity: [0.4, 1, 0.4], 
      scale: [1, 1.2, 1],
      transition: { repeat: Infinity, duration: 1.5 } 
    },
    go: { opacity: 1, scale: 1.3, color: "#10b981" }, // Success green
    no_go: { opacity: 1, scale: 1, color: "#ef4444" } // Destructive red
  };

  return (
    <motion.div 
      layoutId="picky-avatar"
      className={cn("relative flex items-center justify-center", className)}
      transition={{ type: "spring", stiffness: 300, damping: 30 }}
    >
      <motion.svg
        viewBox="0 0 100 100"
        className="w-full h-full drop-shadow-2xl"
        initial="idle"
        animate={state}
      >
        {/* Tail - Wags on GO */}
        <motion.path
          d="M20,70 Q10,60 15,50 T25,40"
          stroke="currentColor"
          strokeWidth="8"
          strokeLinecap="round"
          fill="none"
          className="text-primary/40"
          animate={state === "go" ? { rotate: [0, 20, 0], transition: { repeat: Infinity, duration: 0.5 } } : {}}
        />

        {/* Body / Trench Coat */}
        <path
          d="M30,90 L70,90 L75,60 L25,60 Z"
          fill="#1e293b" // Slate-800
        />
        <path
          d="M35,60 L45,90 M65,60 L55,90"
          stroke="#475569" // Slate-600
          strokeWidth="1"
          strokeOpacity="0.3"
        />

        {/* Neck / Collar */}
        <path
          d="M40,60 L60,60 L65,50 L35,50 Z"
          fill="#334155" // Slate-700
        />

        {/* Head Puppet Group */}
        <motion.g variants={headVariants}>
          {/* Ears */}
          <motion.path
            variants={earVariants}
            d="M35,35 L30,15 L45,25 Z"
            fill="var(--primary)"
          />
          <motion.path
            variants={earVariants}
            d="M65,35 L70,15 L55,25 Z"
            fill="var(--primary)"
          />

          {/* Face Base */}
          <path
            d="M30,35 L70,35 L75,55 L50,75 L25,55 Z"
            fill="var(--primary)"
          />
          
          {/* White Snout Accent */}
          <path
            d="M40,55 L60,55 L50,75 Z"
            fill="white"
            fillOpacity="0.2"
          />

          {/* Nose */}
          <motion.circle
            cx="50" cy="72" r="3"
            fill="black"
            animate={isThinking ? { scale: [1, 1.2, 1], transition: { repeat: Infinity, duration: 0.8 } } : {}}
          />

          {/* Right Eye (Normal) */}
          <motion.circle
            cx="38" cy="45" r="3"
            fill="black"
            animate={{ scaleY: [1, 1, 0.1, 1, 1], transition: { repeat: Infinity, duration: 4 } }}
          />

          {/* Left Eye (Cybernetic Monocle) */}
          <g transform="translate(62, 45)">
            <motion.circle
              variants={monocleVariants}
              r="8"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              className={cn(
                "text-slate-200",
                state === "go" && "text-success",
                state === "no_go" && "text-destructive"
              )}
            />
            <motion.circle
              r="3"
              fill="black"
              animate={isThinking ? { x: [-1, 1, -1] } : {}}
            />
            {/* HUD Scanning Lines */}
            <AnimatePresence>
              {isThinking && (
                <motion.path
                  initial={{ opacity: 0 }}
                  animate={{ opacity: [0, 1, 0], y: [-5, 5] }}
                  exit={{ opacity: 0 }}
                  transition={{ repeat: Infinity, duration: 1.5 }}
                  d="M-5,0 L5,0"
                  stroke="white"
                  strokeWidth="0.5"
                />
              )}
            </AnimatePresence>
          </g>
        </motion.g>

        {/* Thinking HUD Elements (Floating around head) */}
        <AnimatePresence>
          {isThinking && (
            <motion.g
              initial={{ opacity: 0, scale: 0.8 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.8 }}
            >
              <circle cx="85" cy="30" r="1.5" fill="var(--primary)" className="animate-pulse" />
              <circle cx="15" cy="25" r="1" fill="var(--primary)" className="animate-pulse" />
              <motion.path
                d="M80,20 L90,20"
                stroke="var(--primary)"
                strokeWidth="0.5"
                strokeOpacity="0.4"
                animate={{ width: [0, 10, 0] }}
                transition={{ repeat: Infinity, duration: 2 }}
              />
            </motion.g>
          )}
        </AnimatePresence>
      </motion.svg>

      {/* Speech Bubble Overlay (Optional for micro-copy) */}
      {state === "error" && (
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          className="absolute -top-12 left-1/2 -translate-x-1/2 bg-destructive text-destructive-foreground text-[10px] font-mono px-2 py-1 rounded-md whitespace-nowrap"
        >
          SIGNAL LOST
        </motion.div>
      )}
    </div>
  );
}
