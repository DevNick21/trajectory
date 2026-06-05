import CommandPalette from "@/components/CommandPalette";
import PickyAvatar from "@/components/PickyAvatar";
import SidebarStatus from "@/components/SidebarStatus";
import { Link, NavLink, Route, Routes } from "react-router-dom";
import { Toaster } from "sonner";
import ChatDrawer from "@/components/ChatDrawer";
import OnboardingGate from "@/components/OnboardingGate";
import Applications from "@/pages/Applications";
import Assist from "@/pages/Assist";
import Dashboard from "@/pages/Dashboard";
import Memory from "@/pages/Memory";
import Offer from "@/pages/Offer";
import Onboarding from "@/pages/Onboarding";
import Queue from "@/pages/Queue";
import SessionDetail from "@/pages/SessionDetail";
import SessionPack from "@/pages/SessionPack";
import { cn } from "@/lib/utils";

const navLink = ({ isActive }: { isActive: boolean }) =>
  cn(
    "flex items-center gap-3 px-3 py-2 text-sm rounded-lg transition-all duration-200 group",
    isActive
      ? "bg-primary text-primary-foreground shadow-lg shadow-primary/20 font-medium"
      : "text-muted-foreground hover:bg-secondary hover:text-foreground",
  );

export default function App() {
  return (
    <div className="min-h-screen flex bg-background text-foreground overflow-hidden">
      <aside className="w-64 border-r border-canvas flex flex-col bg-card/30 backdrop-blur-xl">
        <div className="p-6">
          <Link to="/" className="flex items-center gap-3 group">
            <div className="h-10 w-10 rounded-xl overflow-hidden shadow-2xl shadow-primary/20">
              <PickyAvatar />
            </div>
            <div className="flex flex-col">
              <span className="font-serif text-xl leading-tight">AskPicky</span>
              <span className="text-[10px] uppercase tracking-widest text-muted-foreground font-bold">
                Research Lab
              </span>
            </div>
          </Link>
        </div>

        <nav className="flex-1 px-3 py-4 space-y-1">
          <NavLink to="/" end className={navLink}>
            Dashboard
          </NavLink>
          <NavLink to="/applications" className={navLink}>
            Applications
          </NavLink>
          <NavLink to="/assist" className={navLink}>
            Assist
          </NavLink>
          <NavLink to="/queue" className={navLink}>
            Queue
          </NavLink>
          <NavLink to="/offer" className={navLink}>
            Offer
          </NavLink>
          <div className="pt-4 mt-4 border-t border-canvas">
            <NavLink to="/onboarding" className={navLink}>
              User Profile
            </NavLink>
            <NavLink to="/memory" className={navLink}>
              Memory Inbox
            </NavLink>
          </div>
        </nav>

        <div className="p-4 border-t border-canvas">
          <SidebarStatus />
        </div>
      </aside>

      <div className="flex-1 flex flex-col overflow-hidden">
        <header className="h-14 border-b border-canvas flex items-center px-8 justify-between bg-background/50 backdrop-blur-md z-10">
          <div className="flex items-center gap-4">
            <span className="text-xs text-muted-foreground font-mono">system.status == "ALIVE"</span>
          </div>
          <div className="flex items-center gap-2">
            <CommandPalette />
          </div>
        </header>

        <main className="flex-1 overflow-y-auto p-8 relative">
          <OnboardingGate>
            <Routes>
              <Route path="/" element={<Dashboard />} />
              <Route path="/applications" element={<Applications />} />
              <Route path="/assist" element={<Assist />} />
              <Route path="/queue" element={<Queue />} />
              <Route path="/offer" element={<Offer />} />
              <Route path="/sessions/:id" element={<SessionDetail />} />
              <Route path="/sessions/:id/:pack" element={<SessionPack />} />
              <Route path="/onboarding" element={<Onboarding />} />
              <Route path="/memory" element={<Memory />} />
            </Routes>
          </OnboardingGate>
        </main>
      </div>

      {/* Toaster sits top-right so it doesn't collide with the
          ChatDrawer floating launcher in the bottom-right corner. */}
      <Toaster theme="dark" richColors closeButton position="top-right" />
      <ChatDrawer />
    </div>
  );
}
