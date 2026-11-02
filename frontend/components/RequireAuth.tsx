"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";
import { Spinner } from "@/components/ui";
import { useAuth } from "@/lib/auth";

export function RequireAuth({ children, permission }: { children: React.ReactNode; permission?: string }) {
  const { user, loading, can } = useAuth();
  const router = useRouter();
  const path = usePathname();
  useEffect(() => {
    if (!loading && !user) router.replace(`/login?next=${encodeURIComponent(path)}`);
  }, [loading, user, router, path]);
  if (loading || !user) {
    return <div className="flex min-h-dvh items-center justify-center"><Spinner /></div>;
  }
  if (permission && !can(permission)) {
    return (
      <div className="flex min-h-dvh items-center justify-center px-4 text-center text-dim">
        Your role ({user.role_name}) does not include access to this area.
      </div>
    );
  }
  return <>{children}</>;
}
