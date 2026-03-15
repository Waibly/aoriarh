"use client";

import { useSession, signOut } from "next-auth/react";
import { useEffect, useRef } from "react";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

export function SessionGuard({ children }: { children: React.ReactNode }) {
  const { data: session, status } = useSession();
  const checkedRef = useRef(false);

  useEffect(() => {
    if (session?.error === "RefreshTokenExpired") {
      signOut({ callbackUrl: "/login" });
    }
  }, [session?.error]);

  // Verify user still exists in backend on first load
  useEffect(() => {
    if (status !== "authenticated" || !session?.access_token || checkedRef.current) return;
    checkedRef.current = true;

    fetch(`${API_BASE_URL}/users/me`, {
      headers: { Authorization: `Bearer ${session.access_token}` },
    }).then((res) => {
      if (res.status === 401) {
        signOut({ callbackUrl: "/login" });
      }
    }).catch(() => {
      // Network error — don't sign out
    });
  }, [status, session?.access_token]);

  return <>{children}</>;
}
