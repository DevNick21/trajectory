// Redirects to /onboarding when no profile exists for the demo user.
//
// Single-user demo: there is no real auth — the "auth" is whether the
// DEMO_USER_ID has a profile row. Without one, every other surface is
// useless (forwarding a URL needs motivations + style, drafting a CV
// needs career_entries, etc.) so we hard-redirect to the wizard
// instead of letting the user wander into disabled forms.

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

  const { isPending, isError, error } = useQuery({
    queryKey: ["profile"],
    queryFn: getProfile,
    retry: false,
  });

  const profileMissing =
    isError && error instanceof ApiError && error.code === "profile_not_found";

  // Toast-free redirect — the wizard itself explains what's happening.
  useEffect(() => {
    if (profileMissing && !isOnboarding) {
      // Navigate handles this declaratively; the effect just exists to
      // avoid flashing the page contents for one frame.
    }
  }, [profileMissing, isOnboarding]);

  if (isPending) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-20 w-full" />
        <Skeleton className="h-10 w-2/3" />
      </div>
    );
  }

  if (profileMissing && !isOnboarding) {
    return <Navigate to="/onboarding" replace />;
  }

  return <>{children}</>;
}
