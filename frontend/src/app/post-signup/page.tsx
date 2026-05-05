"use client";

import { useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { useSession } from "next-auth/react";
import { Loader2 } from "lucide-react";
import { apiFetch } from "@/lib/api";

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
  // Guard against React StrictMode double-invoking the effect, which would
  // create two Stripe Checkout sessions for the same signup.
  const hasRunRef = useRef(false);

  useEffect(() => {
    if (hasRunRef.current) return;
    if (session.status === "loading") return;

    hasRunRef.current = true;

    const plan = readCookie("aoria_signup_plan");
    const cycle = readCookie("aoria_signup_cycle");
    clearCookie("aoria_signup_plan");
    clearCookie("aoria_signup_cycle");

    const planValid = plan && (PAID_PLANS as readonly string[]).includes(plan);
    const cycleValid =
      cycle && (BILLING_CYCLES as readonly string[]).includes(cycle);

    if (
      session.status !== "authenticated" ||
      !planValid ||
      !cycleValid ||
      !session.data?.access_token
    ) {
      router.replace("/chat");
      return;
    }

    apiFetch<{ checkout_url: string }>("/billing/checkout", {
      method: "POST",
      token: session.data.access_token,
      body: JSON.stringify({ plan, cycle }),
    })
      .then((data) => {
        if (data?.checkout_url) {
          window.location.href = data.checkout_url;
        } else {
          router.replace("/chat");
        }
      })
      .catch(() => {
        // Stripe can't be reached or the plan is mis-configured. The user
        // already has a free trial account, so funnel them to the in-app
        // billing page where they can retry with a clear error context.
        router.replace("/billing");
      });
  }, [router, session]);

  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-3 bg-background px-4 text-center">
      <Loader2 className="text-primary h-8 w-8 animate-spin" />
      <p className="text-foreground text-sm font-medium">
        Préparation de votre paiement…
      </p>
      <p className="text-muted-foreground text-xs">
        Vous allez être redirigé vers la page sécurisée Stripe.
      </p>
    </div>
  );
}
