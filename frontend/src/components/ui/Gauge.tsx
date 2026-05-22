import { motion } from "motion/react";
import { cn } from "@/lib/utils";

interface Props {
  value: number; // 0 to 1
  label: string;
  sublabel?: string;
  className?: string;
  color?: "primary" | "success" | "destructive" | "warning";
}

export default function Gauge({ value, label, sublabel, className, color = "primary" }: Props) {
  const angle = value * 180 - 90;
  
  const colors = {
    primary: "stroke-primary",
    success: "stroke-success",
    destructive: "stroke-destructive",
    warning: "stroke-warning",
  };

  return (
    <div className={cn("flex flex-col items-center justify-center p-4 rounded-2xl bg-secondary/20 border border-canvas", className)}>
      <div className="relative w-32 h-20 overflow-hidden">
        {/* Track */}
        <svg viewBox="0 0 100 50" className="w-full h-full">
          <path
            d="M 10 50 A 40 40 0 0 1 90 50"
            fill="none"
            stroke="currentColor"
            strokeWidth="8"
            className="text-muted/20"
            strokeLinecap="round"
          />
          {/* Progress */}
          <motion.path
            d="M 10 50 A 40 40 0 0 1 90 50"
            fill="none"
            stroke="currentColor"
            strokeWidth="8"
            strokeLinecap="round"
            className={colors[color]}
            initial={{ pathLength: 0 }}
            animate={{ pathLength: value }}
            transition={{ duration: 1.5, ease: "easeOut" }}
          />
        </svg>

        {/* Needle */}
        <motion.div
          className="absolute bottom-0 left-1/2 w-1 h-12 bg-foreground origin-bottom -translate-x-1/2"
          initial={{ rotate: -90 }}
          animate={{ rotate: angle }}
          transition={{ duration: 1.5, ease: "easeOut" }}
        />
        
        {/* Center hub */}
        <div className="absolute bottom-0 left-1/2 w-4 h-2 bg-foreground -translate-x-1/2 rounded-t-full" />
      </div>

      <div className="mt-2 text-center">
        <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-muted-foreground">{label}</p>
        <p className="text-sm font-serif font-bold tracking-tight">{sublabel ?? `${Math.round(value * 100)}%`}</p>
      </div>
    </div>
  );
}
