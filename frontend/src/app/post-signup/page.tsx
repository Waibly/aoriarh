"use client";

import { useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { useSession } from "next-auth/react";
import { Loader2 } from "lucide-react";
import { apiFetch } from "@/lib/api";
import type { Organisation } from "@/types/api";

// Callback page hit after a Google OAuth round-trip. Never shown for long —
// just checks if the user already has an organisation and dispatches:
//   - has org : run the requested Stripe checkout (if any) or land on /chat
//   - no org  : redirect to /register?onboard=1 which shows the org-only step
//
// The actual onboarding form lives in /register so we never have two visible
// "create your organisation" screens.

const PAID_PLANS = ["solo", "equipe", "groupe"] as const;
const BILLING_CYCLES = ["monthly", "yearly"] as const;

function readCookie(name: string): string | null {
  const match = document.cookie.match(
    new RegExp("(?:^|; )" + name.replace(/[.$?*|{}()[\]\\/+^]/g, "\\$&") + "=([^;]*)"),
  );
  return match ? decodeURIComponent(match[1]) : null;
}

function clearCookie(name: string) {
  document.cookie = `${name}=; max-age=0; path=/; samesite=lax`;
}

export default function PostSignupPage() {
  const router = useRouter();
  const session = useSession();
  const hasRunRef = useRef(false);

  useEffect(() => {
    if (hasRunRef.current) return;
    if (session.status === "loading") return;

    hasRunRef.current = true;

    if (session.status !== "authenticated" || !session.data?.access_token) {
      router.replace("/login");
      return;
    }

    const token = session.data.access_token;

    apiFetch<Organisation[]>("/organisations/", { token })
      .then((orgs) => {
        if (!orgs || orgs.length === 0) {
          // No org yet → onboarding flow lives in /register so the user
          // sees a single, consistent screen. Plan/cycle/profil/callback
          // cookies stay in place; /register reads them when it submits.
          router.replace("/register?onboard=1");
          return;
        }
        continueAfterOrg(token);
      })
      .catch(() => {
        // If we can't list orgs, default to the onboarding screen so the
        // user is never dropped in /chat without an org.
        router.replace("/register?onboard=1");
      });
  }, [router, session]);

  function continueAfterOrg(token: string) {
    const plan = readCookie("aoria_signup_plan");
    const cycle = readCookie("aoria_signup_cycle");
    const callback = readCookie("aoria_post_signup_callback");
    clearCookie("aoria_signup_plan");
    clearCookie("aoria_signup_cycle");
    clearCookie("aoria_post_signup_callback");
    clearCookie("aoria_signup_profil");

    const planValid = plan && (PAID_PLANS as readonly string[]).includes(plan);
    const cycleValid =
      cycle && (BILLING_CYCLES as readonly string[]).includes(cycle);
    const safeCallback =
      callback && callback.startsWith("/") ? callback : null;

    if (!planValid || !cycleValid) {
      router.replace(safeCallback ?? "/chat");
      return;
    }

    apiFetch<{ checkout_url: string }>("/billing/checkout", {
      method: "POST",
      token,
      body: JSON.stringify({ plan, cycle }),
    })
      .then((data) => {
        if (data?.checkout_url) {
          window.location.href = data.checkout_url;
        } else {
          router.replace(safeCallback ?? "/chat");
        }
      })
      .catch(() => {
        router.replace("/billing");
      });
  }

  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-3 bg-background px-4 text-center">
      <Loader2 className="text-primary h-8 w-8 animate-spin" />
      <p className="text-foreground text-sm font-medium">
        Préparation de votre espace…
      </p>
    </div>
  );
}
