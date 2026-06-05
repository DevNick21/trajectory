import { ReactNode } from "react";
import { motion } from "motion/react";
import { cn } from "@/lib/utils";

interface AnimatedBorderCardProps {
  children: ReactNode;
  className?: string;
  containerClassName?: string;
  colorFrom?: string;
  colorTo?: string;
}

export function AnimatedBorderCard({
  children,
  className,
  containerClassName,
  colorFrom = "hsl(var(--primary))",
  colorTo = "hsl(var(--success))"
}: AnimatedBorderCardProps) {
  return (
    <div className={cn("relative overflow-hidden rounded-xl p-[2px] group", containerClassName)}>
      <motion.div
        animate={{ rotate: 360 }}
        transition={{ ease: "linear", duration: 4, repeat: Infinity }}
        className="absolute inset-[-100%] w-[300%] h-[300%] origin-center"
        style={{
          background: `conic-gradient(from 0deg, transparent 0%, transparent 60%, ${colorFrom} 80%, ${colorTo} 100%)`,
        }}
      />
      <div className={cn("relative h-full w-full bg-card rounded-xl overflow-hidden z-10", className)}>
        {children}
      </div>
    </div>
  );
}
