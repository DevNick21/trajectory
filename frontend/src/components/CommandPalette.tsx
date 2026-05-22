import { motion, AnimatePresence } from "motion/react";
import { useEffect, useState } from "react";
import { Search, Command, X, Briefcase } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { listSessions } from "@/lib/api";
import { useNavigate } from "react-router-dom";

export default function CommandPalette() {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const navigate = useNavigate();

  const sessions = useQuery({
    queryKey: ["sessions"],
    queryFn: () => listSessions(),
    enabled: open,
  });

  useEffect(() => {
    const down = (e: KeyboardEvent) => {
      if (e.key === "k" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        setOpen((open) => !open);
      }
    };
    document.addEventListener("keydown", down);
    return () => document.removeEventListener("keydown", down);
  }, []);

  const filtered = (sessions.data?.sessions ?? []).filter(s => {
    const role = (s.role_title ?? "").toLowerCase();
    const company = (s.company_name ?? "").toLowerCase();
    return role.includes(query.toLowerCase()) || company.includes(query.toLowerCase());
  }).slice(0, 5);

  const handleSelect = (id: string) => {
    navigate(`/sessions/${id}`);
    setOpen(false);
    setQuery("");
  };

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label="Open quick search (Cmd+K)"
        className="h-9 px-3 rounded-xl bg-secondary/50 flex items-center gap-3 text-xs text-muted-foreground border border-canvas cursor-pointer hover:bg-secondary/80 transition-all group"
      >
        <Search className="h-3.5 w-3.5 group-hover:text-primary transition-colors" />
        <span className="flex-1 text-left">Quick Search</span>
        <div className="flex items-center gap-1 opacity-40 font-mono">
          <Command className="h-3 w-3" />
          <span>K</span>
        </div>
      </button>

      <AnimatePresence>
        {open && (
          <div className="fixed inset-0 z-50 flex items-start justify-center pt-[15vh] p-4">
            <motion.div 
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={() => setOpen(false)}
              className="absolute inset-0 bg-background/80 backdrop-blur-sm"
            />
            
            <motion.div
              initial={{ opacity: 0, scale: 0.95, y: -20 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95, y: -20 }}
              className="relative w-full max-w-xl bg-card border border-canvas shadow-2xl rounded-3xl overflow-hidden"
            >
              <div className="flex items-center px-4 h-14 border-b border-canvas gap-3">
                <Search className="h-5 w-5 text-muted-foreground" />
                <input 
                  autoFocus
                  placeholder="Search case files, companies, roles..."
                  className="flex-1 bg-transparent border-none outline-none text-sm placeholder:text-muted-foreground/50"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Escape") setOpen(false);
                  }}
                />
                <button
                  type="button"
                  aria-label="Close command palette"
                  onClick={() => setOpen(false)}
                  className="p-1 hover:bg-secondary rounded-lg"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>

              <div className="p-2">
                {query.length > 0 && filtered.length === 0 ? (
                  <div className="py-12 text-center text-sm text-muted-foreground italic">
                    No matching signal found in local repository.
                  </div>
                ) : (
                  <div className="space-y-1">
                    {filtered.map(s => (
                      <button
                        type="button"
                        key={s.id}
                        onClick={() => handleSelect(s.id)}
                        className="w-full flex items-center justify-between p-3 rounded-2xl hover:bg-primary/10 group transition-all text-left"
                      >
                        <div className="flex items-center gap-3">
                          <div className="p-2 rounded-xl bg-secondary group-hover:bg-primary/20 group-hover:text-primary transition-colors">
                            <Briefcase className="h-4 w-4" />
                          </div>
                          <div>
                            <p className="font-serif text-sm leading-tight">{s.role_title ?? "Unknown role"}</p>
                            <p className="text-[10px] font-mono text-muted-foreground uppercase">{s.company_name ?? "Unknown company"}</p>
                          </div>
                        </div>
                        <ChevronRight className="h-4 w-4 opacity-0 group-hover:opacity-100 transition-opacity" />
                      </button>
                    ))}
                  </div>
                )}
              </div>

              <div className="px-4 py-3 bg-secondary/30 border-t border-canvas flex items-center justify-between text-[10px] text-muted-foreground font-mono">
                <div className="flex gap-4">
                  <span className="flex items-center gap-1"><Command className="h-3 w-3" />K to Toggle</span>
                  <span className="flex items-center gap-1">↑↓ to Navigate</span>
                </div>
                <span>Case File Search</span>
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>
    </>
  );
}

function ChevronRight({ className }: { className?: string }) {
  return (
    <svg 
      xmlns="http://www.w3.org/2000/svg" 
      width="24" 
      height="24" 
      viewBox="0 0 24 24" 
      fill="none" 
      stroke="currentColor" 
      strokeWidth="2" 
      strokeLinecap="round" 
      strokeLinejoin="round" 
      className={className}
    >
      <path d="m9 18 6-6-6-6"/>
    </svg>
  );
}
