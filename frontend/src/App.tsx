import { Link, NavLink, Route, Routes } from "react-router-dom";
import { Toaster } from "sonner";
import ChatDrawer from "@/components/ChatDrawer";
import Dashboard from "@/pages/Dashboard";
import Offer from "@/pages/Offer";
import Onboarding from "@/pages/Onboarding";
import Queue from "@/pages/Queue";
import SessionDetail from "@/pages/SessionDetail";
import SessionPack from "@/pages/SessionPack";
import { cn } from "@/lib/utils";

const navLink = ({ isActive }: { isActive: boolean }) =>
  cn(
    "text-sm transition-colors",
    isActive
      ? "text-foreground font-medium"
      : "text-foreground/60 hover:text-foreground",
  );

export default function App() {
  return (
    <div className="min-h-screen flex flex-col">
      <header className="border-b border-canvas">
        <div className="container flex h-14 items-center justify-between">
          <Link to="/" className="flex items-center gap-2">
            <span
              aria-hidden
              className="flex h-7 w-7 items-center justify-center rounded-full bg-primary text-primary-foreground text-sm font-bold"
            >
              T
            </span>
            <span className="font-semibold tracking-tight">Trajectory</span>
          </Link>
          <nav className="flex items-center gap-5">
            <NavLink to="/" end className={navLink}>
              Dashboard
            </NavLink>
            <NavLink to="/queue" className={navLink}>
              Queue
            </NavLink>
            <NavLink to="/offer" className={navLink}>
              Offer
            </NavLink>
            <NavLink to="/onboarding" className={navLink}>
              Profile
            </NavLink>
          </nav>
        </div>
      </header>
      <main className="flex-1 container py-8">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/queue" element={<Queue />} />
          <Route path="/offer" element={<Offer />} />
          <Route path="/sessions/:id" element={<SessionDetail />} />
          <Route path="/sessions/:id/:pack" element={<SessionPack />} />
          <Route path="/onboarding" element={<Onboarding />} />
        </Routes>
      </main>
      {/* App-wide toast surface. richColors maps the four
          (success / info / warning / error) variants to the colors in
          the mockup. */}
      <Toaster theme="dark" richColors closeButton position="top-right" />
      <ChatDrawer />
    </div>
  );
}
