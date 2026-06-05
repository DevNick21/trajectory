import React, { createContext, useContext, useState, ReactNode } from "react";
import { PickyState } from "./PickyAvatar";
import { AnimatePresence } from "motion/react";

type MascotPosition = "sidebar" | "dashboard" | "onboarding" | "verdict";

interface MascotContextType {
  state: PickyState;
  position: MascotPosition;
  setState: (state: PickyState) => void;
  setPosition: (pos: MascotPosition) => void;
}

const MascotContext = createContext<MascotContextType | undefined>(undefined);

const PickyAvatarLazy = React.lazy(() => import("./PickyAvatar"));

export function MascotProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<PickyState>("idle");
  const [position, setPosition] = useState<MascotPosition>("sidebar");

  return (
    <MascotContext.Provider value={{ state, position, setState, setPosition }}>
      {children}
    </MascotContext.Provider>
  );
}

export function useMascot() {
  const context = useContext(MascotContext);
  if (!context) throw new Error("useMascot must be used within MascotProvider");
  return context;
}

/**
 * A "Slot" for the Mascot. Only renders if the Mascot position matches.
 * Uses Framer Motion layoutId for seamless transitions between slots.
 */
export function MascotSlot({ 
  position, 
  className,
  size = "md"
}: { 
  position: MascotPosition; 
  className?: string;
  size?: "sm" | "md" | "lg";
}) {
  const { position: currentPos, state } = useMascot();

  return (
    <div className={className}>
      <AnimatePresence mode="popLayout">
        {currentPos === position && (
          <React.Suspense fallback={null}>
            <PickyAvatarLazy state={state} size={size} />
          </React.Suspense>
        )}
      </AnimatePresence>
    </div>
  );
}
