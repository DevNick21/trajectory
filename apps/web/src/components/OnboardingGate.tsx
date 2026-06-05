// Redirects to /onboarding when no profile exists for profile-dependent pages.
// The dashboard stays open so first-session users can paste a JD or URL before
// completing a large profile.

import { useEffect } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { ApiError, getProfile } from "@/lib/api";
import { Skeleton } from "@/components/ui/skeleton";

interface Props {
  children: React.ReactNode;
}

export default function OnboardingGate({ children }: Props) {
  const location = useLocation();
  const isOnboarding = location.pathname.startsWith("/onboarding");
  const isJdFirstPath = location.pathname === "/";

  const { isPending, isError, error } = useQuery({
    queryKey: ["profile"],
    queryFn: getProfile,
    retry: false,
  });

  const profileMissing =
    isError && error instanceof ApiError && error.code === "profile_not_found";

  // Toast-free redirect — the wizard itself explains what's happening.
  useEffect(() => {
    if (profileMissing && !isOnboarding && !isJdFirstPath) {
      // Navigate handles this declaratively; the effect just exists to
      // avoid flashing the page contents for one frame.
    }
  }, [profileMissing, isOnboarding, isJdFirstPath]);

  if (isPending) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-20 w-full" />
        <Skeleton className="h-10 w-2/3" />
      </div>
    );
  }

  if (profileMissing && !isOnboarding && !isJdFirstPath) {
    return <Navigate to="/onboarding" replace />;
  }

  return <>{children}</>;
}
