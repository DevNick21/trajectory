import { Link, Route, Routes } from "react-router-dom";
import Dashboard from "@/pages/Dashboard";
import SessionDetail from "@/pages/SessionDetail";
import Onboarding from "@/pages/Onboarding";
import Queue from "@/pages/Queue";

export default function App() {
  return (
    <div className="min-h-screen flex flex-col">
      <header className="border-b">
        <div className="container flex h-14 items-center justify-between">
          <Link to="/" className="font-semibold tracking-tight">
            Trajectory
          </Link>
          <nav className="flex items-center gap-4 text-sm">
            <Link to="/" className="hover:underline">
              Dashboard
            </Link>
            <Link to="/queue" className="hover:underline">
              Queue
            </Link>
            <Link to="/onboarding" className="hover:underline">
              Onboarding
            </Link>
          </nav>
        </div>
      </header>
      <main className="flex-1 container py-8">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/queue" element={<Queue />} />
          <Route path="/sessions/:id" element={<SessionDetail />} />
          <Route path="/onboarding" element={<Onboarding />} />
        </Routes>
      </main>
    </div>
  );
}
