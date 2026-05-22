"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useSession } from "next-auth/react";
import { Loader2, Building2 } from "lucide-react";
import { apiFetch } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { PROFIL_METIER_OPTIONS } from "@/types/api";
import type { Organisation } from "@/types/api";
import {
  OrgFormFields,
  emptyOrgFormFields,
  type OrgFormFieldsValues,
} from "@/components/org/org-form-fields";

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

type Phase = "checking" | "needs-org" | "submitting" | "done";

export default function PostSignupPage() {
  const router = useRouter();
  const session = useSession();
  const hasRunRef = useRef(false);

  const [phase, setPhase] = useState<Phase>("checking");
  const [orgValues, setOrgValues] = useState<OrgFormFieldsValues>(
    emptyOrgFormFields(),
  );
  const [profilMetier, setProfilMetier] = useState<string>("");
  const [error, setError] = useState<string | null>(null);

  // 1. After auth, check if the user already has an organisation.
  //    If yes → proceed straight to checkout/chat as before.
  //    If no → show the inline onboarding form (case for Google signups).
  useEffect(() => {
    if (hasRunRef.current) return;
    if (session.status === "loading") return;

    hasRunRef.current = true;

    if (session.status !== "authenticated" || !session.data?.access_token) {
      router.replace("/login");
      return;
    }

    // Pre-fill profil from the signup cookie (set by /register on Google flow)
    const profilFromCookie = readCookie("aoria_signup_profil");
    if (profilFromCookie) {
      setProfilMetier(profilFromCookie);
      clearCookie("aoria_signup_profil");
    }

    const token = session.data.access_token;
    apiFetch<Organisation[]>("/organisations/", { token })
      .then((orgs) => {
        if (orgs && orgs.length > 0) {
          continueAfterOrg(token);
        } else {
          setPhase("needs-org");
        }
      })
      .catch(() => {
        // If org listing fails, ask the user to create one anyway —
        // safer than dropping them in /chat without any org.
        setPhase("needs-org");
      });
  }, [router, session]);

  function continueAfterOrg(token: string) {
    const plan = readCookie("aoria_signup_plan");
    const cycle = readCookie("aoria_signup_cycle");
    const callback = readCookie("aoria_post_signup_callback");
    clearCookie("aoria_signup_plan");
    clearCookie("aoria_signup_cycle");
    clearCookie("aoria_post_signup_callback");

    const planValid = plan && (PAID_PLANS as readonly string[]).includes(plan);
    const cycleValid =
      cycle && (BILLING_CYCLES as readonly string[]).includes(cycle);
    // callback must be a relative URL to avoid open-redirect
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

  async function handleSubmitOrg(e: React.FormEvent) {
    e.preventDefault();
    if (!orgValues.name.trim()) return;
    const token = session.data?.access_token;
    if (!token) return;

    setPhase("submitting");
    setError(null);

    try {
      // 1. Save profil métier (if provided)
      if (profilMetier) {
        await apiFetch("/users/me", {
          method: "PATCH",
          token,
          body: JSON.stringify({ profil_metier: profilMetier }),
        }).catch(() => {});
      }

      // 2. Create organisation
      const ccnLabel = orgValues.notSubjectToCcn
        ? null
        : orgValues.selectedCcn.length > 0
          ? orgValues.selectedCcn
              .map((c) => `${c.titre_court || c.titre} (IDCC ${c.idcc})`)
              .join(", ")
          : null;
      const org = await apiFetch<Organisation>("/organisations/", {
        method: "POST",
        token,
        body: JSON.stringify({
          name: orgValues.name.trim(),
          forme_juridique: orgValues.formeJuridique || null,
          taille: orgValues.taille || null,
          secteur_activite: orgValues.secteurActivite.trim() || null,
          convention_collective: ccnLabel,
          not_subject_to_ccn: orgValues.notSubjectToCcn,
        }),
      });

      // 3. Install CCNs (fire & forget, the KALI sync is async)
      if (!orgValues.notSubjectToCcn && orgValues.selectedCcn.length > 0) {
        for (const ccn of orgValues.selectedCcn) {
          apiFetch(`/conventions/organisations/${org.id}`, {
            method: "POST",
            token,
            body: JSON.stringify({ idcc: ccn.idcc }),
          }).catch(() => {});
        }
      }

      // 4. Continue — checkout if plan, else chat
      continueAfterOrg(token);
    } catch {
      setPhase("needs-org");
      setError(
        "Impossible de créer votre organisation. Vérifiez vos informations puis réessayez.",
      );
    }
  }

  if (phase === "checking" || phase === "done") {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-3 bg-background px-4 text-center">
        <Loader2 className="text-primary h-8 w-8 animate-spin" />
        <p className="text-foreground text-sm font-medium">
          Préparation de votre espace…
        </p>
      </div>
    );
  }

  if (phase === "submitting") {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-3 bg-background px-4 text-center">
        <Loader2 className="text-primary h-8 w-8 animate-spin" />
        <p className="text-foreground text-sm font-medium">
          Création de votre organisation…
        </p>
      </div>
    );
  }

  // phase === "needs-org" — inline onboarding form for Google signups
  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4 py-10">
      <div className="w-full max-w-lg space-y-6">
        <div className="flex flex-col items-center gap-2 text-center">
          <div className="rounded-full bg-[#652bb0]/10 p-3">
            <Building2 className="h-6 w-6 text-[#652bb0]" />
          </div>
          <h1 className="text-2xl font-semibold tracking-tight">
            Votre organisation
          </h1>
          <p className="text-muted-foreground text-sm max-w-md">
            Pour personnaliser vos réponses juridiques, dites-nous quelques
            mots sur votre organisation. Ça prend moins d&apos;une minute.
          </p>
        </div>

        {error && (
          <div className="bg-destructive/10 text-destructive rounded-md p-3 text-sm">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmitOrg} className="space-y-5">
          {!profilMetier && (
            <div className="space-y-1.5">
              <Label htmlFor="profilMetier">
                Votre rôle <span className="text-destructive">*</span>
              </Label>
              <Select value={profilMetier} onValueChange={setProfilMetier}>
                <SelectTrigger id="profilMetier">
                  <SelectValue placeholder="Sélectionner votre profil..." />
                </SelectTrigger>
                <SelectContent>
                  {PROFIL_METIER_OPTIONS.map((p) => (
                    <SelectItem key={p.value} value={p.value}>
                      {p.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}

          <OrgFormFields
            values={orgValues}
            onChange={setOrgValues}
            token={session.data?.access_token ?? ""}
          />

          <Button
            type="submit"
            className="w-full bg-[#652bb0] text-white hover:bg-[#5a2599] focus-visible:ring-[#652bb0]/40"
            disabled={!orgValues.name.trim() || !profilMetier}
          >
            Créer mon organisation
          </Button>
        </form>
      </div>
    </div>
  );
}
