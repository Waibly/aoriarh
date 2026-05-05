"use client";

import { useState, useEffect, Suspense } from "react";
import { signIn } from "next-auth/react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import {
  User,
  Briefcase,
  Building2,
  ArrowRight,
  ArrowLeft,
  Check,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { PROFIL_METIER_OPTIONS } from "@/types/api";
import type { CcnReference } from "@/types/api";
import { CcnSelector } from "@/components/ccn-selector";
import { UserCog } from "lucide-react";

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
  const rawCallback = searchParams.get("callbackUrl");
  const callbackUrl = rawCallback?.startsWith("/") ? rawCallback : null;
  // Extract invitation token and validate it exists
  const inviteToken = callbackUrl?.match(/\/invite\/accept\/([^/?]+)/)?.[1] ?? null;
  const [isInvitation, setIsInvitation] = useState(false);

  // Paid plan pre-selection from the marketing site (?plan=solo&cycle=monthly).
  // Validated against the closed list — anything else is ignored so a tampered
  // URL can never push an unsupported value to the backend.
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
  const hasPaidPlanRequested = requestedPlan !== null && requestedCycle !== null;

  useEffect(() => {
    if (!inviteToken) return;
    // Validate token is real and pending before enabling invitation mode
    fetch(`${API_BASE_URL}/invitations/${inviteToken}/validate`)
      .then((res) => res.ok ? res.json() : null)
      .then((data) => {
        if (data?.valid) setIsInvitation(true);
      })
      .catch(() => {});
  }, [inviteToken]);

  // Step management — skip workspace/org steps for invitations
  const [step, setStep] = useState(1);

  // Step 1 — Compte
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");

  // Step 2 — Espace de travail
  const [workspaceName, setWorkspaceName] = useState("");

  // Step 3 — Organisation (nom + CCN(s) installées)
  const [orgName, setOrgName] = useState("");
  const [selectedCcns, setSelectedCcns] = useState<CcnReference[]>([]);
  // "Ma CCN n'est pas dans la liste" : permet de saisir un libellé manuel
  // sans déclencher l'installation KALI.
  const [ccnNotListed, setCcnNotListed] = useState(false);
  const [manualCcnLabel, setManualCcnLabel] = useState("");

  // Step 4 — Profil métier (also used in invitation step 2)
  const [profilMetier, setProfilMetier] = useState("");

  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

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
    return true;
  }

  async function handleSubmit() {
    setIsLoading(true);
    setError(null);

    try {
      // 1. Register
      const res = await fetch(`${API_BASE_URL}/auth/register`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email,
          password,
          full_name: fullName,
          workspace_name: isInvitation ? null : (workspaceName.trim() || null),
          invited: isInvitation,
          // Only send plan/cycle for self-registrations: invited users have no
          // Account so the backend would ignore them anyway.
          requested_plan: !isInvitation && hasPaidPlanRequested ? requestedPlan : null,
          requested_cycle: !isInvitation && hasPaidPlanRequested ? requestedCycle : null,
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

      // 2. Save profil_metier if provided (invitation flow)
      if (profilMetier && registerData?.access_token) {
        try {
          await fetch(`${API_BASE_URL}/users/me`, {
            method: "PATCH",
            headers: {
              "Content-Type": "application/json",
              Authorization: `Bearer ${registerData.access_token}`,
            },
            body: JSON.stringify({ profil_metier: profilMetier }),
          });
        } catch {
          // Non-blocking
        }
      }

      // 3. Create first org with CCN label, then install CCNs
      // Errors here are non-fatal (the user account is created), but we
      // surface them via the page error so the user can react.
      const ccnInstallErrors: string[] = [];
      if (orgName.trim() && registerData?.access_token) {
        try {
          const ccnLabel = ccnNotListed
            ? manualCcnLabel.trim() || null
            : selectedCcns.length > 0
              ? selectedCcns
                  .map((c) => `${c.titre_court || c.titre} (IDCC ${c.idcc})`)
                  .join(", ")
              : null;

          const orgRes = await fetch(`${API_BASE_URL}/organisations/`, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              Authorization: `Bearer ${registerData.access_token}`,
            },
            body: JSON.stringify({
              name: orgName.trim(),
              convention_collective: ccnLabel,
            }),
          });

          if (orgRes.ok && !ccnNotListed && selectedCcns.length > 0) {
            const orgData = await orgRes.json();
            // Install each selected CCN sequentially so we keep error
            // visibility per IDCC. The KALI sync itself runs async via the
            // worker — we just enqueue here.
            for (const c of selectedCcns) {
              try {
                const r = await fetch(
                  `${API_BASE_URL}/conventions/organisations/${orgData.id}`,
                  {
                    method: "POST",
                    headers: {
                      "Content-Type": "application/json",
                      Authorization: `Bearer ${registerData.access_token}`,
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

      // 3. Sign in via NextAuth
      const result = await signIn("credentials", {
        email,
        password,
        redirect: false,
      });

      if (result?.error) {
        router.push(
          callbackUrl
            ? `/login?callbackUrl=${encodeURIComponent(callbackUrl)}`
            : "/login"
        );
        return;
      }

      // If the backend started a Stripe Checkout session for the requested
      // paid plan, send the user straight to the hosted payment page. The
      // trial account stays as a safety net if they abandon — when they
      // come back to /chat the trial banner will prompt them to upgrade.
      if (registerData?.checkout_url) {
        window.location.href = registerData.checkout_url;
        return;
      }

      // Land on /chat — the product's core value. The CcnInstallBanner
      // (mounted in the dashboard layout) keeps the user informed of the
      // CCN install status wherever they go, so we don't need to force
      // them through the documents page.
      const landing = callbackUrl || "/chat";

      // Surface CCN install errors as a query param. A global toast handler
      // in the dashboard layout fires the message wherever the user lands.
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

  return (
    <>
      <div className="flex flex-col space-y-2 text-center">
        <h1 className="text-2xl font-semibold tracking-tight">
          {isInvitation ? "Rejoindre l'équipe" : "Créer un compte"}
        </h1>
        <p className="text-muted-foreground text-sm">
          {isInvitation
            ? step === 1
              ? "Créez votre compte pour accepter l'invitation"
              : "Une dernière étape pour personnaliser vos réponses"
            : step === 1
              ? "Entrez vos informations pour commencer"
              : step === 2
                ? "Nommez votre espace de travail"
                : step === 3
                  ? "Créez votre première organisation"
                  : "Une dernière étape pour personnaliser vos réponses"}
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

      {/* Stepper */}
      {isInvitation ? (
        <div className="flex items-center justify-center gap-2 py-2">
          <StepBadge
            step={1}
            current={step}
            icon={<User className="h-3.5 w-3.5" />}
            label="Compte"
          />
          <div className="h-px w-3 sm:w-6 bg-border shrink-0" />
          <StepBadge
            step={2}
            current={step}
            icon={<UserCog className="h-3.5 w-3.5" />}
            label="Profil"
          />
        </div>
      ) : (
        <div className="flex items-center justify-center gap-2 py-2">
          <StepBadge
            step={1}
            current={step}
            icon={<User className="h-3.5 w-3.5" />}
            label="Compte"
          />
          <div className="h-px w-3 sm:w-6 bg-border shrink-0" />
          <StepBadge
            step={2}
            current={step}
            icon={<Briefcase className="h-3.5 w-3.5" />}
            label="Espace"
          />
          <div className="h-px w-3 sm:w-6 bg-border shrink-0" />
          <StepBadge
            step={3}
            current={step}
            icon={<Building2 className="h-3.5 w-3.5" />}
            label="Organisation"
          />
          <div className="h-px w-3 sm:w-6 bg-border shrink-0" />
          <StepBadge
            step={4}
            current={step}
            icon={<UserCog className="h-3.5 w-3.5" />}
            label="Profil"
          />
        </div>
      )}

      <div className="grid gap-6">
        {error && (
          <div className="bg-destructive/10 text-destructive rounded-md p-3 text-sm">
            {error}
          </div>
        )}

        {/* Step 1 — Compte */}
        {step === 1 && (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (!validateStep1()) return;
              setStep(2);
            }}
          >
            <div className="grid gap-4">
              <div className="grid gap-2">
                <Label htmlFor="fullName">Nom complet</Label>
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
                <Label htmlFor="email">Email</Label>
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
                <Label htmlFor="password">Mot de passe</Label>
                <Input
                  id="password"
                  type="password"
                  placeholder="8 caractères minimum"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  minLength={8}
                />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="confirmPassword">
                  Confirmer le mot de passe
                </Label>
                <Input
                  id="confirmPassword"
                  type="password"
                  placeholder="Retapez votre mot de passe"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  required
                  minLength={8}
                />
              </div>
              <Button type="submit">
                Suivant
                <ArrowRight className="ml-2 h-4 w-4" />
              </Button>
            </div>
          </form>
        )}

        {/* Step 2 — Profil métier (invitation) or Espace de travail (normal) */}
        {step === 2 && isInvitation && (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              handleSubmit();
            }}
          >
            <div className="grid gap-4">
              <div className="grid gap-2">
                <Label htmlFor="profilMetier">
                  Quel est votre rôle ?{" "}
                  <span className="text-destructive">*</span>
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
                  Votre fonction permet d&apos;adapter les réponses juridiques à
                  votre perspective métier.
                </p>
              </div>
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
                  disabled={!profilMetier || isLoading}
                >
                  {isLoading ? "Création en cours..." : "Créer mon compte"}
                </Button>
              </div>
            </div>
          </form>
        )}

        {step === 2 && !isInvitation && (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              setStep(3);
            }}
          >
            <div className="grid gap-4">
              <div className="grid gap-2">
                <Label htmlFor="workspaceName">
                  Nom de l&apos;espace de travail{" "}
                  <span className="text-destructive">*</span>
                </Label>
                <Input
                  id="workspaceName"
                  type="text"
                  placeholder="Ex : Waibly, Mon cabinet RH"
                  value={workspaceName}
                  onChange={(e) => setWorkspaceName(e.target.value)}
                  required
                  autoFocus
                />
                <p className="text-xs text-muted-foreground">
                  Votre espace de travail regroupe toutes vos organisations et
                  votre équipe. C&apos;est le nom de votre entreprise, cabinet
                  ou structure.
                </p>
              </div>
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
                  disabled={!workspaceName.trim()}
                >
                  Suivant
                  <ArrowRight className="ml-2 h-4 w-4" />
                </Button>
              </div>
            </div>
          </form>
        )}

        {/* Step 3 — Organisation + CCN */}
        {step === 3 && !isInvitation && (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              setStep(4);
            }}
          >
            <div className="grid gap-4">
              <div className="grid gap-2">
                <Label htmlFor="orgName">
                  Nom de l&apos;organisation
                </Label>
                <Input
                  id="orgName"
                  type="text"
                  placeholder="Ex : Waibly Paris"
                  value={orgName}
                  onChange={(e) => setOrgName(e.target.value)}
                  autoFocus
                />
                <p className="text-xs text-muted-foreground">
                  Une organisation correspond à une entité juridique, un client
                  ou un dossier distinct. Chacune a ses propres documents et
                  conversations. Vous pourrez en créer d&apos;autres plus tard.
                </p>
              </div>

              <div className="grid gap-2">
                <Label>
                  Convention collective{" "}
                  <span className="text-destructive">*</span>
                </Label>
                {!ccnNotListed && (
                  <CcnSelector
                    selected={selectedCcns}
                    onChange={setSelectedCcns}
                    maxSelected={1}
                  />
                )}
                {ccnNotListed && (
                  <Input
                    type="text"
                    placeholder="Ex : Convention de la coiffure (à défaut)"
                    value={manualCcnLabel}
                    onChange={(e) => setManualCcnLabel(e.target.value)}
                  />
                )}
                <label className="flex items-start gap-2 text-xs text-muted-foreground select-none cursor-pointer">
                  <input
                    type="checkbox"
                    checked={ccnNotListed}
                    onChange={(e) => {
                      setCcnNotListed(e.target.checked);
                      if (e.target.checked) {
                        setSelectedCcns([]);
                      } else {
                        setManualCcnLabel("");
                      }
                    }}
                    className="mt-0.5"
                  />
                  <span>
                    Ma convention n&apos;est pas dans la liste (saisie libre,
                    sans installation automatique).
                  </span>
                </label>
                <p className="text-xs text-muted-foreground">
                  {ccnNotListed
                    ? "Votre convention sera enregistrée comme libellé. AORIA RH ne pourra pas la consulter dans ses réponses tant qu'elle n'est pas ajoutée à notre référentiel."
                    : "Plan d'essai : 1 convention. AORIA RH la récupère automatiquement depuis le service public KALI (1-2 minutes)."}
                </p>
              </div>

              <div className="flex gap-3">
                <Button
                  type="button"
                  variant="outline"
                  className="flex-1"
                  onClick={() => setStep(2)}
                >
                  <ArrowLeft className="mr-2 h-4 w-4" />
                  Retour
                </Button>
                <Button
                  type="submit"
                  className="flex-1"
                  disabled={
                    !orgName.trim() ||
                    (ccnNotListed
                      ? !manualCcnLabel.trim()
                      : selectedCcns.length === 0)
                  }
                >
                  Suivant
                  <ArrowRight className="ml-2 h-4 w-4" />
                </Button>
              </div>
            </div>
          </form>
        )}

        {/* Step 4 — Profil métier (normal flow) */}
        {step === 4 && !isInvitation && (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              handleSubmit();
            }}
          >
            <div className="grid gap-4">
              <div className="grid gap-2">
                <Label htmlFor="profilMetierNormal">
                  Quel est votre rôle ?{" "}
                  <span className="text-destructive">*</span>
                </Label>
                <Select value={profilMetier} onValueChange={setProfilMetier}>
                  <SelectTrigger id="profilMetierNormal">
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
                  Votre fonction permet d&apos;adapter les réponses juridiques à
                  votre perspective métier.
                </p>
              </div>
              <div className="flex gap-3">
                <Button
                  type="button"
                  variant="outline"
                  className="flex-1"
                  onClick={() => setStep(3)}
                >
                  <ArrowLeft className="mr-2 h-4 w-4" />
                  Retour
                </Button>
                <Button
                  type="submit"
                  className="flex-1"
                  disabled={!profilMetier || isLoading}
                >
                  {isLoading ? "Création en cours..." : "Créer mon compte"}
                </Button>
              </div>
            </div>
          </form>
        )}

        {step === 1 && (
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
                // For paid-plan signups via Google we need to start a Stripe
                // Checkout session AFTER the OAuth round-trip — params can't be
                // sent inline like with the email/password POST. We stash them
                // in short-lived cookies (sameSite=Lax so they survive the
                // Google round-trip) and route through /post-signup which
                // reads them and creates the Checkout session.
                if (!isInvitation && hasPaidPlanRequested && requestedPlan && requestedCycle) {
                  document.cookie = `aoria_signup_plan=${requestedPlan}; max-age=600; path=/; samesite=lax`;
                  document.cookie = `aoria_signup_cycle=${requestedCycle}; max-age=600; path=/; samesite=lax`;
                  signIn("google", { callbackUrl: "/post-signup" });
                  return;
                }
                signIn("google", { callbackUrl: callbackUrl || "/chat" });
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
      {step === 1 && (
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
