"use client";

import { useState, useEffect, Suspense } from "react";
import { signIn, useSession } from "next-auth/react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { User, Building2, ArrowRight, ArrowLeft, Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { PasswordInput } from "@/components/password-input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { PROFIL_METIER_OPTIONS } from "@/types/api";
import {
  OrgFormFields,
  emptyOrgFormFields,
  isOrgFormFieldsValid,
  type OrgFormFieldsValues,
} from "@/components/org/org-form-fields";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

const PAID_PLANS = ["solo", "equipe", "groupe"] as const;
const BILLING_CYCLES = ["monthly", "yearly"] as const;
type PaidPlan = (typeof PAID_PLANS)[number];
type BillingCycle = (typeof BILLING_CYCLES)[number];

const PLAN_LABEL: Record<PaidPlan, string> = {
  solo: "Solo",
  equipe: "Équipe",
  groupe: "Groupe",
};
const CYCLE_LABEL: Record<BillingCycle, string> = {
  monthly: "mensuel",
  yearly: "annuel",
};

function readCookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie.match(
    new RegExp("(?:^|; )" + name.replace(/[.$?*|{}()[\]\\/+^]/g, "\\$&") + "=([^;]*)"),
  );
  return match ? decodeURIComponent(match[1]) : null;
}

function clearCookie(name: string) {
  if (typeof document === "undefined") return;
  document.cookie = `${name}=; max-age=0; path=/; samesite=lax`;
}

export default function RegisterPage() {
  return (
    <Suspense>
      <RegisterForm />
    </Suspense>
  );
}

function RegisterForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const session = useSession();
  const rawCallback = searchParams.get("callbackUrl");
  const callbackUrl = rawCallback?.startsWith("/") ? rawCallback : null;
  const inviteToken =
    callbackUrl?.match(/\/invite\/accept\/([^/?]+)/)?.[1] ?? null;
  const [isInvitation, setIsInvitation] = useState(false);

  // Onboarding mode: user already authenticated (typically via Google) but has
  // no organisation yet. We only show the org step — no account creation, no
  // Google button. Triggered by /post-signup after the OAuth round-trip.
  const isOnboardingOnly =
    searchParams.get("onboard") === "1" &&
    session.status === "authenticated";

  const rawPlan = searchParams.get("plan");
  const rawCycle = searchParams.get("cycle");
  const requestedPlan: PaidPlan | null =
    rawPlan && (PAID_PLANS as readonly string[]).includes(rawPlan)
      ? (rawPlan as PaidPlan)
      : null;
  const requestedCycle: BillingCycle | null =
    rawCycle && (BILLING_CYCLES as readonly string[]).includes(rawCycle)
      ? (rawCycle as BillingCycle)
      : null;
  const hasPaidPlanRequested =
    requestedPlan !== null && requestedCycle !== null;

  useEffect(() => {
    if (!inviteToken) return;
    fetch(`${API_BASE_URL}/invitations/${inviteToken}/validate`)
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (data?.valid) setIsInvitation(true);
      })
      .catch(() => {});
  }, [inviteToken]);

  // Guard the onboarding mode: if /register?onboard=1 is hit by someone who
  // is NOT authenticated, send them to login. Avoids the form being shown to
  // anonymous users (they would never be able to submit it).
  useEffect(() => {
    if (
      searchParams.get("onboard") === "1" &&
      session.status === "unauthenticated"
    ) {
      router.replace("/login");
    }
  }, [searchParams, session.status, router]);

  const [step, setStep] = useState(1);

  // --- Step 1 : Compte + profil métier ---
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [profilMetier, setProfilMetier] = useState("");

  // --- Step 2 : Organisation ---
  const [orgValues, setOrgValues] = useState<OrgFormFieldsValues>(
    emptyOrgFormFields(),
  );

  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  // Onboarding mode: pre-fill the profil from the cookie set by /register
  // before the Google round-trip, so the user doesn't have to re-pick it.
  useEffect(() => {
    if (!isOnboardingOnly) return;
    const profilFromCookie = readCookie("aoria_signup_profil");
    if (profilFromCookie) {
      setProfilMetier(profilFromCookie);
      clearCookie("aoria_signup_profil");
    }
  }, [isOnboardingOnly]);

  function validateStep1(): boolean {
    setError(null);
    if (password.length < 8) {
      setError("Le mot de passe doit contenir au moins 8 caractères");
      return false;
    }
    if (password !== confirmPassword) {
      setError("Les mots de passe ne correspondent pas");
      return false;
    }
    if (!profilMetier) {
      setError("Sélectionnez votre rôle pour continuer");
      return false;
    }
    return true;
  }

  // --- Submit handlers ---

  // Onboarding (Google, already authenticated): patch profil, create org,
  // install CCN, then run Stripe checkout if a paid plan was requested.
  async function handleOnboardingSubmit() {
    setIsLoading(true);
    setError(null);
    const token = session.data?.access_token;
    if (!token) {
      setIsLoading(false);
      router.replace("/login");
      return;
    }

    try {
      if (profilMetier) {
        await fetch(`${API_BASE_URL}/users/me`, {
          method: "PATCH",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${token}`,
          },
          body: JSON.stringify({ profil_metier: profilMetier }),
        }).catch(() => {});
      }

      const ccnLabel = orgValues.notSubjectToCcn
        ? null
        : orgValues.selectedCcn.length > 0
          ? orgValues.selectedCcn
              .map((c) => `${c.titre_court || c.titre} (IDCC ${c.idcc})`)
              .join(", ")
          : null;

      const orgRes = await fetch(`${API_BASE_URL}/organisations/`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          name: orgValues.name.trim(),
          forme_juridique: orgValues.formeJuridique || null,
          taille: orgValues.taille || null,
          secteur_activite: orgValues.secteurActivite.trim() || null,
          convention_collective: ccnLabel,
          not_subject_to_ccn: orgValues.notSubjectToCcn,
        }),
      });

      if (!orgRes.ok) {
        setError(
          "Impossible de créer votre organisation. Vérifiez vos informations puis réessayez.",
        );
        return;
      }

      const org = await orgRes.json();
      if (!orgValues.notSubjectToCcn && orgValues.selectedCcn.length > 0) {
        for (const c of orgValues.selectedCcn) {
          fetch(`${API_BASE_URL}/conventions/organisations/${org.id}`, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              Authorization: `Bearer ${token}`,
            },
            body: JSON.stringify({ idcc: c.idcc }),
          }).catch(() => {});
        }
      }

      // Redeem plan invitation if a promo token cookie exists
      const planInviteToken = readCookie("aoria_plan_invite_token");
      if (planInviteToken) {
        clearCookie("aoria_plan_invite_token");
        try {
          await fetch(`${API_BASE_URL}/plan-invitations/${planInviteToken}/redeem`, {
            method: "POST",
            headers: {
              Authorization: `Bearer ${token}`,
            },
          });
        } catch {
          // Non-blocking
        }
      }

      // Stripe checkout if a paid plan was stashed in cookies before the OAuth
      const plan = readCookie("aoria_signup_plan");
      const cycle = readCookie("aoria_signup_cycle");
      const callback = readCookie("aoria_post_signup_callback");
      clearCookie("aoria_signup_plan");
      clearCookie("aoria_signup_cycle");
      clearCookie("aoria_post_signup_callback");

      const planValid =
        plan && (PAID_PLANS as readonly string[]).includes(plan);
      const cycleValid =
        cycle && (BILLING_CYCLES as readonly string[]).includes(cycle);
      const safeCallback =
        callback && callback.startsWith("/") ? callback : null;

      if (planValid && cycleValid) {
        try {
          const checkout = await fetch(`${API_BASE_URL}/billing/checkout`, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              Authorization: `Bearer ${token}`,
            },
            body: JSON.stringify({ plan, cycle }),
          });
          if (checkout.ok) {
            const data = await checkout.json();
            if (data?.checkout_url) {
              window.location.href = data.checkout_url;
              return;
            }
          }
        } catch {
          router.replace("/billing");
          return;
        }
      }

      router.replace(safeCallback ?? "/chat");
      router.refresh();
    } catch {
      setError("Une erreur est survenue. Veuillez réessayer.");
    } finally {
      setIsLoading(false);
    }
  }

  // Standard registration (email/password) + optional first org.
  async function handleSubmit() {
    setIsLoading(true);
    setError(null);

    try {
      const res = await fetch(`${API_BASE_URL}/auth/register`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email,
          password,
          full_name: fullName,
          workspace_name: null,
          invited: isInvitation,
          requested_plan:
            !isInvitation && hasPaidPlanRequested ? requestedPlan : null,
          requested_cycle:
            !isInvitation && hasPaidPlanRequested ? requestedCycle : null,
        }),
      });

      if (!res.ok) {
        const data = await res.json().catch(() => null);
        if (res.status === 409) {
          setError("Un compte avec cet email existe déjà");
          setStep(1);
        } else if (res.status === 422 && data?.detail) {
          const messages = Array.isArray(data.detail)
            ? data.detail.map((d: { msg: string }) => d.msg).join(". ")
            : data.detail;
          setError(messages);
          setStep(1);
        } else {
          setError("Erreur lors de l'inscription. Veuillez réessayer.");
        }
        return;
      }

      const registerData = await res.json().catch(() => null);
      const accessToken = registerData?.access_token as string | undefined;

      if (profilMetier && accessToken) {
        try {
          await fetch(`${API_BASE_URL}/users/me`, {
            method: "PATCH",
            headers: {
              "Content-Type": "application/json",
              Authorization: `Bearer ${accessToken}`,
            },
            body: JSON.stringify({ profil_metier: profilMetier }),
          });
        } catch {
          // Non-blocking
        }
      }

      const ccnInstallErrors: string[] = [];
      if (!isInvitation && orgValues.name.trim() && accessToken) {
        try {
          const ccnLabel = orgValues.notSubjectToCcn
            ? null
            : orgValues.selectedCcn.length > 0
              ? orgValues.selectedCcn
                  .map((c) => `${c.titre_court || c.titre} (IDCC ${c.idcc})`)
                  .join(", ")
              : null;

          const orgRes = await fetch(`${API_BASE_URL}/organisations/`, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              Authorization: `Bearer ${accessToken}`,
            },
            body: JSON.stringify({
              name: orgValues.name.trim(),
              forme_juridique: orgValues.formeJuridique || null,
              taille: orgValues.taille || null,
              secteur_activite: orgValues.secteurActivite.trim() || null,
              convention_collective: ccnLabel,
              not_subject_to_ccn: orgValues.notSubjectToCcn,
            }),
          });

          if (
            orgRes.ok &&
            !orgValues.notSubjectToCcn &&
            orgValues.selectedCcn.length > 0
          ) {
            const orgData = await orgRes.json();
            for (const c of orgValues.selectedCcn) {
              try {
                const r = await fetch(
                  `${API_BASE_URL}/conventions/organisations/${orgData.id}`,
                  {
                    method: "POST",
                    headers: {
                      "Content-Type": "application/json",
                      Authorization: `Bearer ${accessToken}`,
                    },
                    body: JSON.stringify({ idcc: c.idcc }),
                  },
                );
                if (!r.ok) {
                  const data = await r.json().catch(() => null);
                  const detail =
                    typeof data?.detail === "string"
                      ? data.detail
                      : `Erreur ${r.status}`;
                  ccnInstallErrors.push(`IDCC ${c.idcc} : ${detail}`);
                }
              } catch (err) {
                ccnInstallErrors.push(
                  `IDCC ${c.idcc} : ${err instanceof Error ? err.message : "erreur réseau"}`,
                );
              }
            }
          }
        } catch {
          // Non-blocking — org can be re-created later
        }
      }

      const result = await signIn("credentials", {
        email,
        password,
        redirect: false,
      });

      if (result?.error) {
        router.push(
          callbackUrl
            ? `/login?callbackUrl=${encodeURIComponent(callbackUrl)}`
            : "/login",
        );
        return;
      }

      if (registerData?.checkout_url) {
        window.location.href = registerData.checkout_url;
        return;
      }

      // Redeem plan invitation if a promo token cookie exists
      const planInviteToken = readCookie("aoria_plan_invite_token");
      if (planInviteToken && accessToken) {
        clearCookie("aoria_plan_invite_token");
        try {
          await fetch(`${API_BASE_URL}/plan-invitations/${planInviteToken}/redeem`, {
            method: "POST",
            headers: { Authorization: `Bearer ${accessToken}` },
          });
        } catch {
          // Non-blocking — user can redeem later via the link
        }
      }

      const landing = callbackUrl || "/chat";
      if (ccnInstallErrors.length > 0) {
        const params = new URLSearchParams({
          ccn_install_error: ccnInstallErrors.join(" • "),
        });
        router.push(`${landing}?${params.toString()}`);
      } else {
        router.push(landing);
      }
      router.refresh();
    } catch {
      setError("Une erreur est survenue. Veuillez réessayer.");
    } finally {
      setIsLoading(false);
    }
  }

  // --- Render ---

  // Onboarding mode (Google user without org yet) : single org-only screen
  if (isOnboardingOnly) {
    return (
      <>
        <div className="flex flex-col items-center gap-2 text-center">
          <div className="rounded-full bg-primary/10 p-2.5">
            <Building2 className="h-5 w-5 text-primary" />
          </div>
          <h1 className="text-2xl font-semibold tracking-tight">
            Votre organisation
          </h1>
          <p className="text-muted-foreground text-sm">
            Pour personnaliser vos réponses juridiques, dites-nous quelques
            mots sur votre organisation.
          </p>
        </div>

        {error && (
          <div className="bg-destructive/10 text-destructive rounded-md p-3 text-sm">
            {error}
          </div>
        )}

        <form
          onSubmit={(e) => {
            e.preventDefault();
            handleOnboardingSubmit();
          }}
          className="grid gap-5"
        >
          {!profilMetier && (
            <div className="grid gap-2">
              <Label htmlFor="profilMetierOnboarding">
                Votre rôle <span className="text-destructive">*</span>
              </Label>
              <Select value={profilMetier} onValueChange={setProfilMetier}>
                <SelectTrigger id="profilMetierOnboarding">
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
            requireTaille
          />

          <Button
            type="submit"
            disabled={
              !isOrgFormFieldsValid(orgValues, { requireTaille: true }) ||
              !profilMetier ||
              isLoading
            }
          >
            {isLoading ? "Création en cours..." : "Continuer"}
          </Button>
        </form>
      </>
    );
  }

  const totalSteps = isInvitation ? 1 : 2;

  return (
    <>
      <div className="flex flex-col space-y-2 text-center">
        <h1 className="text-2xl font-semibold tracking-tight">
          {isInvitation ? "Rejoindre l'équipe" : "Créer un compte"}
        </h1>
        <p className="text-muted-foreground text-sm">
          {isInvitation
            ? "Créez votre compte pour accepter l'invitation"
            : step === 1
              ? "Quelques informations pour démarrer"
              : "Une dernière étape : votre organisation"}
        </p>
      </div>

      {!isInvitation && hasPaidPlanRequested && requestedPlan && requestedCycle && (
        <div className="bg-primary/5 border border-primary/20 text-primary rounded-md px-4 py-3 text-sm">
          <p className="font-medium">
            Vous souscrivez à l&apos;offre {PLAN_LABEL[requestedPlan]} ({CYCLE_LABEL[requestedCycle]})
          </p>
          <p className="text-primary/80 text-xs mt-1">
            Le paiement par carte sera demandé après la création de votre compte.
          </p>
        </div>
      )}

      {totalSteps > 1 && (
        <div className="flex items-center justify-center gap-2 py-2">
          <StepBadge
            step={1}
            current={step}
            icon={<User className="h-3.5 w-3.5" />}
            label="Vous"
          />
          <div className="h-px w-6 bg-border shrink-0" />
          <StepBadge
            step={2}
            current={step}
            icon={<Building2 className="h-3.5 w-3.5" />}
            label="Organisation"
          />
        </div>
      )}

      <div className="grid gap-6">
        {error && (
          <div className="bg-destructive/10 text-destructive rounded-md p-3 text-sm">
            {error}
          </div>
        )}

        {step === 1 && (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (!validateStep1()) return;
              if (isInvitation) {
                handleSubmit();
              } else {
                setStep(2);
              }
            }}
          >
            <div className="grid gap-4">
              <div className="grid gap-2">
                <Label htmlFor="fullName">
                  Nom complet <span className="text-destructive">*</span>
                </Label>
                <Input
                  id="fullName"
                  type="text"
                  placeholder="Jean Dupont"
                  value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                  required
                  autoFocus
                />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="email">
                  Email <span className="text-destructive">*</span>
                </Label>
                <Input
                  id="email"
                  type="email"
                  placeholder="vous@exemple.fr"
                  autoCapitalize="none"
                  autoComplete="email"
                  autoCorrect="off"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="password">
                  Mot de passe <span className="text-destructive">*</span>
                </Label>
                <PasswordInput
                  id="password"
                  placeholder="8 caractères minimum"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  minLength={8}
                />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="confirmPassword">
                  Confirmer le mot de passe{" "}
                  <span className="text-destructive">*</span>
                </Label>
                <PasswordInput
                  id="confirmPassword"
                  placeholder="Retapez votre mot de passe"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  required
                  minLength={8}
                />
              </div>
              <div className="grid gap-2">
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
                <p className="text-xs text-muted-foreground">
                  Permet d&apos;adapter les réponses à votre perspective métier.
                </p>
              </div>
              {isInvitation ? (
                <Button type="submit" disabled={isLoading}>
                  {isLoading ? "Création en cours..." : "Créer mon compte"}
                </Button>
              ) : (
                <Button type="submit">
                  Suivant
                  <ArrowRight className="ml-2 h-4 w-4" />
                </Button>
              )}
            </div>
          </form>
        )}

        {step === 2 && !isInvitation && (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              handleSubmit();
            }}
          >
            <div className="grid gap-5">
              <OrgFormFields
                values={orgValues}
                onChange={setOrgValues}
                token=""
                requireTaille
              />
              <div className="flex gap-3">
                <Button
                  type="button"
                  variant="outline"
                  className="flex-1"
                  onClick={() => setStep(1)}
                >
                  <ArrowLeft className="mr-2 h-4 w-4" />
                  Retour
                </Button>
                <Button
                  type="submit"
                  className="flex-1"
                  disabled={
                    !isOrgFormFieldsValid(orgValues, { requireTaille: true }) ||
                    isLoading
                  }
                >
                  {isLoading ? "Création en cours..." : "Créer mon compte"}
                </Button>
              </div>
            </div>
          </form>
        )}

        {step === 1 && !isInvitation && (
          <>
            <div className="relative">
              <div className="absolute inset-0 flex items-center">
                <span className="w-full border-t" />
              </div>
              <div className="relative flex justify-center text-xs uppercase">
                <span className="bg-background text-muted-foreground px-2">
                  Ou
                </span>
              </div>
            </div>
            <Button
              variant="outline"
              type="button"
              disabled={isLoading}
              onClick={() => {
                if (hasPaidPlanRequested && requestedPlan && requestedCycle) {
                  document.cookie = `aoria_signup_plan=${requestedPlan}; max-age=600; path=/; samesite=lax`;
                  document.cookie = `aoria_signup_cycle=${requestedCycle}; max-age=600; path=/; samesite=lax`;
                }
                if (profilMetier) {
                  document.cookie = `aoria_signup_profil=${profilMetier}; max-age=600; path=/; samesite=lax`;
                }
                signIn("google", { callbackUrl: "/post-signup" });
              }}
            >
              <svg className="mr-2 h-4 w-4" viewBox="0 0 24 24">
                <path
                  d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z"
                  fill="#4285F4"
                />
                <path
                  d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
                  fill="#34A853"
                />
                <path
                  d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"
                  fill="#FBBC05"
                />
                <path
                  d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"
                  fill="#EA4335"
                />
              </svg>
              S&apos;inscrire avec Google
            </Button>
          </>
        )}
      </div>
      {step === 1 && !isInvitation && (
        <p className="text-muted-foreground px-8 text-center text-sm">
          Déjà un compte ?{" "}
          <Link
            href={
              callbackUrl
                ? `/login?callbackUrl=${encodeURIComponent(callbackUrl)}`
                : "/login"
            }
            className="hover:text-primary underline underline-offset-4"
          >
            Se connecter
          </Link>
        </p>
      )}
    </>
  );
}

function StepBadge({
  step,
  current,
  icon,
  label,
}: {
  step: number;
  current: number;
  icon: React.ReactNode;
  label: string;
}) {
  const isActive = step === current;
  const isDone = step < current;

  return (
    <div
      className={`flex items-center gap-1.5 rounded-full px-2 sm:px-3 py-1.5 text-xs font-semibold transition-all ${
        isActive || isDone
          ? "bg-primary/10 text-primary"
          : "bg-muted text-muted-foreground"
      }`}
      aria-label={label}
    >
      {isDone ? <Check className="h-3.5 w-3.5" /> : icon}
      <span className="hidden sm:inline">{label}</span>
    </div>
  );
}
