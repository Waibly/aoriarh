"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useSession } from "next-auth/react";
import { Loader2 } from "lucide-react";
import { apiFetch } from "@/lib/api";
import type { Organisation, User } from "@/types/api";
import { Button } from "@/components/ui/button";
import { useErrorState } from "@/hooks/use-error-state";
import {
  readSignupCookie as readCookie,
  clearSignupCookie as clearCookie,
  safeAppCallback,
  redeemPendingPlan,
} from "@/lib/signup-flow";

// Callback page hit after a Google OAuth round-trip. Never shown for long —
// just checks if the user already has an organisation and dispatches:
//   - has org : run the requested Stripe checkout (if any) or land on /chat
//   - no org  : redirect to /register?onboard=1 which shows the org-only step
//
// The actual onboarding form lives in /register so we never have two visible
// "create your organisation" screens.

const PAID_PLANS = ["solo", "equipe", "groupe"] as const;
const BILLING_CYCLES = ["monthly", "yearly"] as const;

export default function PostSignupPage() {
  const router = useRouter();
  const session = useSession();
  const hasRunRef = useRef(false);
  const [error, setError] = useErrorState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  const continueAfterOrg = useCallback(
    async (token: string) => {
      await redeemPendingPlan(token);

      const plan = readCookie("aoria_signup_plan");
      const cycle = readCookie("aoria_signup_cycle");
      const callback = readCookie("aoria_post_signup_callback");

      const planValid =
        plan && (PAID_PLANS as readonly string[]).includes(plan);
      const cycleValid =
        cycle && (BILLING_CYCLES as readonly string[]).includes(cycle);
      const safeCallback = safeAppCallback(callback);

      if (!planValid || !cycleValid) {
        clearCookie("aoria_post_signup_callback");
        clearCookie("aoria_signup_profil");
        router.replace(safeCallback ?? "/chat");
        return;
      }

      const checkout = await apiFetch<{ checkout_url: string }>(
        "/billing/checkout",
        {
          method: "POST",
          token,
          body: JSON.stringify({ plan, cycle }),
        }
      );
      if (!checkout.checkout_url)
        throw new Error("Le paiement n'a pas pu être préparé. Réessayez.");
      clearCookie("aoria_signup_plan");
      clearCookie("aoria_signup_cycle");
      clearCookie("aoria_post_signup_callback");
      clearCookie("aoria_signup_profil");
      window.location.href = checkout.checkout_url;
    },
    [router]
  );

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
      .then(async (orgs) => {
        if (!orgs || orgs.length === 0) {
          // No org yet. Special case: if the callback points at an invitation
          // acceptance page, respect it directly — the accept flow creates the
          // membership/org, so an onboarding here would make the user create a
          // dangling empty org instead of joining the inviter's workspace.
          const callback = readCookie("aoria_post_signup_callback");
          if (callback && callback.startsWith("/invite/accept/")) {
            clearCookie("aoria_post_signup_callback");
            router.replace(callback);
            return;
          }
          const user = await apiFetch<User>("/users/me", { token });
          if (user.pending_invitation_token) {
            router.replace(`/invite/accept/${user.pending_invitation_token}`);
            return;
          }
          // Otherwise show the onboarding screen. Plan/cycle/profil cookies
          // stay in place; /register reads them when it submits.
          router.replace("/register?onboard=1");
          return;
        }
        await continueAfterOrg(token);
      })
      .catch((error) => {
        setError(
          error instanceof Error
            ? error.message
            : "Impossible de préparer votre espace."
        );
      });
  }, [router, session, attempt, setError, continueAfterOrg]);

  return (
    <div className="bg-background flex min-h-screen flex-col items-center justify-center gap-3 px-4 text-center">
      {!error && <Loader2 className="text-primary h-8 w-8 animate-spin" />}
      <p className="text-foreground text-sm font-medium">
        {error
          ? "Votre inscription demande une nouvelle tentative"
          : "Préparation de votre espace…"}
      </p>
      {error && (
        <>
          <p role="alert" className="text-destructive max-w-md text-sm">
            {error}
          </p>
          <Button
            onClick={() => {
              setError(null);
              hasRunRef.current = false;
              setAttempt((value) => value + 1);
            }}
          >
            Réessayer
          </Button>
          <Button variant="outline" onClick={() => router.push("/billing")}>
            Consulter mon accès et mes offres
          </Button>
        </>
      )}
    </div>
  );
}
