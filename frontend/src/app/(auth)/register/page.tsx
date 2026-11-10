"use client";

import { useErrorState } from "@/hooks/use-error-state";

import { useState, useEffect, useRef, Suspense } from "react";
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
import { DEFAULT_TERRITOIRE, PROFIL_METIER_OPTIONS } from "@/types/api";
import { apiFetch } from "@/lib/api";
import {
  setupOrganisation,
  type OrganisationSetupProgress,
} from "@/lib/organisation-setup";
import {
  readSignupCookie as readCookie,
  clearSignupCookie as clearCookie,
  safeAppCallback,
  redeemPendingPlan,
  withSetupWarnings,
} from "@/lib/signup-flow";
import {
  OrgFormFields,
  emptyOrgFormFields,
  isOrgFormFieldsValid,
  type OrgFormFieldsValues,
} from "@/components/org/org-form-fields";
import { getAttribution, sendAttribution } from "@/lib/attribution";
import { trackEssaiDemarre } from "@/lib/gtag";
import { storePendingQuestion } from "@/lib/pending-question";

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

// Mêmes règles que le backend (schemas/auth.py) : affichées en direct sous le
// champ pour que l'utilisateur voie ce qui manque pendant la saisie.
const PASSWORD_RULES: { label: string; test: (v: string) => boolean }[] = [
  { label: "12 caractères", test: (v) => v.length >= 12 },
  { label: "1 majuscule", test: (v) => /[A-Z]/.test(v) },
  { label: "1 chiffre", test: (v) => /\d/.test(v) },
  { label: "1 symbole", test: (v) => /[^A-Za-z0-9]/.test(v) },
];

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
  const callbackUrl = safeAppCallback(rawCallback);
  const inviteToken =
    callbackUrl?.match(/\/invite\/accept\/([^/?]+)/)?.[1] ?? null;
  const [isInvitation, setIsInvitation] = useState(false);

  // Onboarding mode: user already authenticated (typically via Google) but has
  // no organisation yet. We only show the org step — no account creation, no
  // Google button. Triggered by /post-signup after the OAuth round-trip.
  const isOnboardingOnly =
    searchParams.get("onboard") === "1" && session.status === "authenticated";

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

  // Question préparée sur un outil du site : conservée jusqu'au premier écran du chat.
  useEffect(() => {
    storePendingQuestion(searchParams.get("q"));
  }, [searchParams]);

  useEffect(() => {
    if (!inviteToken) return;
    fetch(`${API_BASE_URL}/invitations/${inviteToken}/validate`)
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (data?.valid) {
          setIsInvitation(true);
          setEmail(data.email);
        }
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
  const [profilMetier, setProfilMetier] = useState("");

  // --- Step 2 : Organisation ---
  const [orgValues, setOrgValues] =
    useState<OrgFormFieldsValues>(emptyOrgFormFields());

  const [error, setError] = useErrorState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [accountCreated, setAccountCreated] = useState(false);
  const [organisationReady, setOrganisationReady] = useState(false);
  const setupProgress = useRef<OrganisationSetupProgress>({});
  const registration = useRef<{
    access_token: string;
    checkout_url?: string | null;
  } | null>(null);
  const signedIn = useRef(false);
  const tracked = useRef(false);

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
    const missing = PASSWORD_RULES.filter((r) => !r.test(password));
    if (missing.length > 0) {
      setError(
        `Mot de passe incomplet : il manque ${missing.map((r) => r.label).join(", ")}`
      );
      return false;
    }
    if (!profilMetier) {
      setError("Sélectionnez votre rôle pour continuer");
      return false;
    }
    return true;
  }

  // --- Submit handlers ---

  function organisationData() {
    return {
      name: orgValues.name.trim(),
      forme_juridique: orgValues.formeJuridique || null,
      taille: orgValues.taille || null,
      secteur_activite: orgValues.secteurActivite.trim() || null,
      convention_collective: orgValues.notSubjectToCcn
        ? null
        : orgValues.selectedCcn
            .map((c) => `${c.titre_court || c.titre} (IDCC ${c.idcc})`)
            .join(", ") || null,
      not_subject_to_ccn: orgValues.notSubjectToCcn,
      territoire: orgValues.territoire || DEFAULT_TERRITOIRE,
      profil_metier: profilMetier || null,
      selectedCcn: orgValues.selectedCcn,
    };
  }

  async function handleOnboardingSubmit() {
    const token = session.data?.access_token;
    if (!token) {
      router.replace("/login");
      return;
    }
    setIsLoading(true);
    setError(null);
    void sendAttribution(token);
    if (!tracked.current) {
      trackEssaiDemarre();
      tracked.current = true;
    }
    try {
      const { warnings } = await setupOrganisation(
        organisationData(),
        token,
        setupProgress.current
      );
      setOrganisationReady(true);
      await redeemPendingPlan(token);
      const plan = readCookie("aoria_signup_plan");
      const cycle = readCookie("aoria_signup_cycle");
      const callback = safeAppCallback(
        readCookie("aoria_post_signup_callback")
      );
      if (
        plan &&
        cycle &&
        (PAID_PLANS as readonly string[]).includes(plan) &&
        (BILLING_CYCLES as readonly string[]).includes(cycle)
      ) {
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
        window.location.href = checkout.checkout_url;
        return;
      }
      clearCookie("aoria_post_signup_callback");
      router.replace(withSetupWarnings(callback ?? "/chat", warnings));
      router.refresh();
    } catch (error) {
      setError(
        error instanceof Error
          ? error.message
          : "Impossible de terminer votre inscription. Réessayez."
      );
    } finally {
      setIsLoading(false);
    }
  }

  async function handleSubmit() {
    setIsLoading(true);
    setError(null);
    try {
      if (!registration.current) {
        const res = await fetch(`${API_BASE_URL}/auth/register`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            email,
            password,
            full_name: fullName,
            workspace_name: null,
            invited: isInvitation,
            invitation_token: isInvitation ? inviteToken : null,
            requested_plan:
              !isInvitation && hasPaidPlanRequested ? requestedPlan : null,
            requested_cycle:
              !isInvitation && hasPaidPlanRequested ? requestedCycle : null,
            attribution: getAttribution(),
          }),
        });
        if (!res.ok) {
          const data = await res.json().catch(() => null);
          if (res.status === 409) {
            setError("Un compte avec cet email existe déjà");
            setStep(1);
          } else {
            const detail = data?.detail;
            setError(
              typeof detail === "string"
                ? detail
                : Array.isArray(detail)
                  ? detail.map((d: { msg: string }) => d.msg).join(". ")
                  : "Erreur lors de l'inscription. Veuillez réessayer."
            );
            if (res.status === 422) setStep(1);
          }
          return;
        }
        registration.current = await res.json();
        setAccountCreated(true);
        trackEssaiDemarre();
      }
      const token = registration.current?.access_token;
      if (!token)
        throw new Error("La création du compte n'a pas été confirmée.");
      if (!signedIn.current) {
        const result = await signIn("credentials", {
          email,
          password,
          redirect: false,
        });
        if (!result?.ok)
          throw new Error(
            "Votre compte est créé. Connectez-vous pour terminer votre inscription."
          );
        signedIn.current = true;
      }
      let warnings: string[] = [];
      if (isInvitation) {
        if (profilMetier)
          await apiFetch("/users/me", {
            method: "PATCH",
            token,
            body: JSON.stringify({ profil_metier: profilMetier }),
          });
      } else {
        ({ warnings } = await setupOrganisation(
          organisationData(),
          token,
          setupProgress.current
        ));
        setOrganisationReady(true);
      }
      await redeemPendingPlan(token);
      if (registration.current?.checkout_url) {
        window.location.href = registration.current.checkout_url;
        return;
      }
      if (!isInvitation && hasPaidPlanRequested) {
        router.push(withSetupWarnings("/billing", warnings));
      } else {
        router.push(withSetupWarnings(callbackUrl ?? "/chat", warnings));
      }
      router.refresh();
    } catch (error) {
      setError(
        error instanceof Error
          ? error.message
          : "Impossible de terminer votre inscription. Réessayez."
      );
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
          <div className="bg-primary/10 rounded-full p-2.5">
            <Building2 className="text-primary h-5 w-5" />
          </div>
          <h1 className="text-2xl font-semibold tracking-tight">
            Votre organisation
          </h1>
          <p className="text-muted-foreground text-sm">
            Pour personnaliser vos réponses juridiques, dites-nous quelques mots
            sur votre organisation.
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
          <fieldset disabled={organisationReady} className="contents">
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

            <OrgFormFields
              values={orgValues}
              onChange={setOrgValues}
              token={session.data?.access_token ?? ""}
            />
          </fieldset>

          <Button
            type="submit"
            disabled={
              !isOrgFormFieldsValid(orgValues) || !profilMetier || isLoading
            }
          >
            {isLoading
              ? "En cours..."
              : organisationReady
                ? "Terminer l'activation de mon accès"
                : "Continuer"}
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

      {!isInvitation &&
        hasPaidPlanRequested &&
        requestedPlan &&
        requestedCycle && (
          <div className="bg-primary/5 border-primary/20 text-primary rounded-md border px-4 py-3 text-sm">
            <p className="font-medium">
              Vous souscrivez à l&apos;offre {PLAN_LABEL[requestedPlan]} (
              {CYCLE_LABEL[requestedCycle]})
            </p>
            <p className="text-primary/80 mt-1 text-xs">
              Le paiement par carte sera demandé après la création de votre
              compte.
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
          <div className="bg-border h-px w-6 shrink-0" />
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
                  disabled={accountCreated}
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
                  readOnly={isInvitation || accountCreated}
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
                  autoComplete="new-password"
                  disabled={accountCreated}
                  aria-describedby="password-rules"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  minLength={12}
                />
                <ul
                  id="password-rules"
                  className="flex flex-wrap gap-x-3 gap-y-1 text-xs"
                >
                  {PASSWORD_RULES.map((r) => {
                    const ok = r.test(password);
                    return (
                      <li
                        key={r.label}
                        className={`flex items-center gap-1 ${
                          ok ? "text-primary" : "text-muted-foreground"
                        }`}
                      >
                        <Check
                          className={`h-3 w-3 ${ok ? "opacity-100" : "opacity-30"}`}
                          aria-hidden
                        />
                        {r.label}
                      </li>
                    );
                  })}
                </ul>
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
                <p className="text-muted-foreground text-xs">
                  Permet d&apos;adapter les réponses à votre perspective métier.
                </p>
              </div>
              {isInvitation ? (
                <Button type="submit" disabled={isLoading}>
                  {isLoading
                    ? "En cours..."
                    : accountCreated
                      ? "Terminer mon inscription"
                      : "Créer mon compte"}
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
              <fieldset disabled={organisationReady} className="contents">
                <OrgFormFields
                  values={orgValues}
                  onChange={setOrgValues}
                  token=""
                />
              </fieldset>
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
                  disabled={!isOrgFormFieldsValid(orgValues) || isLoading}
                >
                  {isLoading
                    ? "En cours..."
                    : accountCreated
                      ? "Terminer mon inscription"
                      : "Créer mon compte"}
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
                if (callbackUrl)
                  document.cookie = `aoria_post_signup_callback=${encodeURIComponent(callbackUrl)}; max-age=600; path=/; samesite=lax`;
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
      className={`flex items-center gap-1.5 rounded-full px-2 py-1.5 text-xs font-semibold transition-all sm:px-3 ${
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
