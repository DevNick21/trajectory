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

  const textColors = {
    primary: "text-primary",
    success: "text-success",
    destructive: "text-destructive",
    warning: "text-warning",
  };

  return (
    <div className={cn("flex flex-col items-center justify-center p-4 rounded-2xl bg-secondary/5 border border-canvas relative overflow-hidden group", className)}>
      <div className="absolute top-0 left-0 w-full h-0.5 bg-gradient-to-r from-transparent via-canvas to-transparent opacity-50" />
      
      <div className="relative w-40 h-24 flex items-center justify-center">
        {/* Track and Ticks */}
        <svg viewBox="0 0 100 60" className="w-full h-full drop-shadow-[0_0_8px_rgba(0,0,0,0.5)]">
          <defs>
            <linearGradient id="gaugeGradient" x1="0%" y1="0%" x2="100%" y2="0%">
              <stop offset="0%" stopColor="currentColor" stopOpacity="0.2" />
              <stop offset="50%" stopColor="currentColor" stopOpacity="0.5" />
              <stop offset="100%" stopColor="currentColor" stopOpacity="0.2" />
            </linearGradient>
          </defs>
          
          {/* Main Track */}
          <path
            d="M 15 50 A 35 35 0 0 1 85 50"
            fill="none"
            stroke="currentColor"
            strokeWidth="1"
            className="text-muted/20"
          />

          {/* Ticks */}
          {[...Array(11)].map((_, i) => {
            const tickAngle = (i * 18) * (Math.PI / 180);
            const x1 = 50 - 38 * Math.cos(tickAngle);
            const y1 = 50 - 38 * Math.sin(tickAngle);
            const x2 = 50 - 32 * Math.cos(tickAngle);
            const y2 = 50 - 32 * Math.sin(tickAngle);
            return (
              <line
                key={i}
                x1={x1}
                y1={y1}
                x2={x2}
                y2={y2}
                stroke="currentColor"
                strokeWidth={i % 5 === 0 ? "1" : "0.5"}
                className={i / 10 <= value ? colors[color] : "text-muted/20"}
              />
            );
          })}
          
          {/* Progress Arc */}
          <motion.path
            d="M 15 50 A 35 35 0 0 1 85 50"
            fill="none"
            stroke="currentColor"
            strokeWidth="6"
            strokeLinecap="butt"
            className={cn(colors[color], "opacity-20")}
            initial={{ pathLength: 0 }}
            animate={{ pathLength: value }}
            transition={{ duration: 1.5, ease: "easeOut" }}
          />

          <motion.path
            d="M 15 50 A 35 35 0 0 1 85 50"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            className={colors[color]}
            initial={{ pathLength: 0 }}
            animate={{ pathLength: value }}
            transition={{ duration: 1.5, ease: "easeOut" }}
          />
        </svg>

        {/* Needle */}
        <div className="absolute bottom-[20%] left-1/2 -translate-x-1/2 w-full h-full pointer-events-none">
          <motion.div
            className={cn("absolute bottom-0 left-1/2 w-0.5 h-14 origin-bottom -translate-x-1/2 shadow-[0_0_10px_rgba(0,0,0,0.5)]", colors[color].replace('stroke-', 'bg-'))}
            initial={{ rotate: -90 }}
            animate={{ rotate: angle }}
            transition={{ duration: 1.5, ease: "backOut" }}
          >
            <div className="absolute -top-1 left-1/2 -translate-x-1/2 w-1.5 h-1.5 rounded-full bg-inherit" />
          </motion.div>
        </div>
        
        {/* Digital Readout In-Gauge */}
        <div className="absolute bottom-[10%] left-1/2 -translate-x-1/2 text-center">
           <motion.span 
             className={cn("text-lg font-mono font-bold tracking-tighter", textColors[color])}
             initial={{ opacity: 0 }}
             animate={{ opacity: 1 }}
           >
             {Math.round(value * 100)}
             <span className="text-[10px] ml-0.5 opacity-50">%</span>
           </motion.span>
        </div>
      </div>

      <div className="mt-1 text-center relative z-10">
        <p className="text-[9px] font-bold uppercase tracking-[0.3em] text-muted-foreground mb-0.5">{label}</p>
        <p className="text-xs font-mono opacity-80 uppercase tracking-tight">{sublabel}</p>
      </div>
      
      {/* Decorative scanning line */}
      <div className="absolute inset-0 bg-gradient-to-b from-transparent via-primary/5 to-transparent h-1/2 w-full -translate-y-full group-hover:animate-scan pointer-events-none" />
    </div>
  );
}
