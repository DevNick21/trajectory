import { motion, AnimatePresence } from "motion/react";
import { useEffect, useState } from "react";

export default function MatrixTransition({ show }: { show: boolean }) {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    if (show) {
      setVisible(true);
      const timer = setTimeout(() => setVisible(false), 2000);
      return () => clearTimeout(timer);
    }
  }, [show]);

  return (
    <AnimatePresence>
      {visible && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 z-[100] pointer-events-none overflow-hidden"
        >
          {/* Matrix-style green/blue wash */}
          <motion.div 
            initial={{ y: "-100%" }}
            animate={{ y: "100%" }}
            transition={{ duration: 1.5, ease: "linear" }}
            className="absolute inset-0 bg-gradient-to-b from-transparent via-primary/20 to-transparent h-[200%]"
          />
          
          {/* Glitch lines */}
          {[...Array(10)].map((_, i) => (
            <motion.div
              key={i}
              initial={{ x: "-100%" }}
              animate={{ x: "100%" }}
              transition={{ 
                duration: 0.5, 
                delay: i * 0.1, 
                repeat: 3, 
                repeatType: "reverse" 
              }}
              className="absolute h-px w-full bg-primary/40"
              style={{ top: `${Math.random() * 100}%` }}
            />
          ))}

          {/* Flash */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: [0, 0.5, 0] }}
            transition={{ duration: 0.3, times: [0, 0.5, 1] }}
            className="absolute inset-0 bg-white"
          />
        </motion.div>
      )}
    </AnimatePresence>
  );
}
