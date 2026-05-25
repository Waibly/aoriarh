"use client";

import { useEffect, useState, useRef } from "react";
import { useParams, useRouter } from "next/navigation";
import { signIn, useSession } from "next-auth/react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Loader2, CheckCircle2, XCircle, Gift } from "lucide-react";
import { apiFetch, API_BASE_URL } from "@/lib/api";

interface ValidateResponse {
  valid: boolean;
  reason?: string;
  plan?: string;
  duration_months?: number;
  label?: string;
  email?: string;
  features?: string[];
}

interface RedeemResponse {
  status: string;
  message?: string;
  plan?: string;
  plan_expires_at?: string;
}

type PageState =
  | "loading"
  | "valid"
  | "redeeming"
  | "redeemed"
  | "already_paid"
  | "already_redeemed"
  | "invalid"
  | "error";

function setCookie(name: string, value: string, maxAge: number) {
  document.cookie = `${name}=${encodeURIComponent(value)}; max-age=${maxAge}; path=/; samesite=lax`;
}

export default function PromoPage() {
  const params = useParams();
  const router = useRouter();
  const { data: session, status: sessionStatus } = useSession();
  const token = params.token as string;

  const [pageState, setPageState] = useState<PageState>("loading");
  const [promoData, setPromoData] = useState<ValidateResponse | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const redeemAttempted = useRef(false);

  useEffect(() => {
    async function validate() {
      try {
        const res = await fetch(
          `${API_BASE_URL}/plan-invitations/${token}/validate`,
        );
        if (!res.ok) {
          setPageState("invalid");
          return;
        }
        const data: ValidateResponse = await res.json();
        setPromoData(data);
        setPageState(data.valid ? "valid" : "invalid");
      } catch {
        setPageState("error");
        setErrorMessage("Impossible de vérifier ce lien.");
      }
    }
    validate();
  }, [token]);

  useEffect(() => {
    if (pageState !== "valid") return;
    if (sessionStatus === "loading") return;
    if (sessionStatus !== "authenticated" || !session?.access_token) return;
    if (redeemAttempted.current) return;

    redeemAttempted.current = true;
    setPageState("redeeming");

    apiFetch<RedeemResponse>(`/plan-invitations/${token}/redeem`, {
      method: "POST",
      token: session.access_token as string,
    })
      .then((data) => {
        if (data.status === "redeemed") {
          setPageState("redeemed");
          setTimeout(() => {
            window.location.href = "/chat";
          }, 2000);
        } else if (data.status === "already_paid") {
          setPageState("already_paid");
        } else if (data.status === "already_redeemed") {
          setPageState("already_redeemed");
        } else {
          setPageState("error");
          setErrorMessage(data.message || "Erreur inattendue");
        }
      })
      .catch((err) => {
        setPageState("error");
        setErrorMessage(
          err instanceof Error ? err.message : "Erreur réseau",
        );
      });
  }, [pageState, sessionStatus, session, token]);

  function handleSignup() {
    setCookie("aoria_plan_invite_token", token, 600);
    router.push("/register");
  }

  function handleLogin() {
    setCookie("aoria_plan_invite_token", token, 600);
    router.push(`/login?callbackUrl=${encodeURIComponent(`/promo/${token}`)}`);
  }

  function handleGoogleSignIn() {
    setCookie("aoria_plan_invite_token", token, 600);
    signIn("google", { callbackUrl: `/promo/${token}` });
  }

  if (pageState === "loading" || sessionStatus === "loading") {
    return (
      <Card>
        <CardContent className="flex flex-col items-center gap-4 py-12">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
          <p className="text-muted-foreground">Vérification...</p>
        </CardContent>
      </Card>
    );
  }

  if (pageState === "invalid") {
    return (
      <Card>
        <CardHeader className="text-center">
          <div className="flex justify-center mb-2">
            <XCircle className="h-12 w-12 text-destructive" />
          </div>
          <CardTitle>Lien expiré ou invalide</CardTitle>
          <CardDescription>
            Ce lien n&apos;est plus actif. Vous pouvez toujours créer un
            compte avec l&apos;essai gratuit de 14 jours.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex justify-center">
          <Button onClick={() => router.push("/register")}>
            Créer un compte
          </Button>
        </CardContent>
      </Card>
    );
  }

  if (pageState === "redeeming") {
    return (
      <Card>
        <CardContent className="flex flex-col items-center gap-4 py-12">
          <Loader2 className="h-8 w-8 animate-spin text-primary" />
          <p className="text-muted-foreground">
            Activation de votre plan...
          </p>
        </CardContent>
      </Card>
    );
  }

  if (pageState === "redeemed") {
    return (
      <Card>
        <CardHeader className="text-center">
          <div className="flex justify-center mb-2">
            <CheckCircle2 className="h-12 w-12 text-green-500" />
          </div>
          <CardTitle>Plan Invité activé</CardTitle>
          <CardDescription>
            Votre accès est prêt. Redirection en cours...
          </CardDescription>
        </CardHeader>
        <CardContent className="flex justify-center">
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
        </CardContent>
      </Card>
    );
  }

  if (pageState === "already_paid") {
    return (
      <Card>
        <CardHeader className="text-center">
          <CardTitle>Abonnement déjà actif</CardTitle>
          <CardDescription>
            Votre compte dispose déjà d&apos;un abonnement payant. Ce lien
            n&apos;est pas applicable.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex justify-center">
          <Button onClick={() => router.push("/chat")}>
            Accéder au chat
          </Button>
        </CardContent>
      </Card>
    );
  }

  if (pageState === "already_redeemed") {
    return (
      <Card>
        <CardHeader className="text-center">
          <CardTitle>Déjà activé</CardTitle>
          <CardDescription>
            Vous avez déjà utilisé ce lien. Votre plan Invité est actif.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex justify-center">
          <Button onClick={() => router.push("/chat")}>
            Accéder au chat
          </Button>
        </CardContent>
      </Card>
    );
  }

  if (pageState === "error") {
    return (
      <Card>
        <CardHeader className="text-center">
          <div className="flex justify-center mb-2">
            <XCircle className="h-12 w-12 text-destructive" />
          </div>
          <CardTitle>Erreur</CardTitle>
          <CardDescription>{errorMessage}</CardDescription>
        </CardHeader>
        <CardContent className="flex justify-center">
          <Button variant="outline" onClick={() => router.push("/register")}>
            Créer un compte
          </Button>
        </CardContent>
      </Card>
    );
  }

  // pageState === "valid", user not authenticated
  const durationLabel =
    promoData?.duration_months === 1
      ? "1 mois"
      : `${promoData?.duration_months} mois`;

  return (
    <Card>
      <CardHeader className="text-center">
        <div className="flex justify-center mb-2">
          <Gift className="h-12 w-12 text-primary" />
        </div>
        <CardTitle className="text-xl">
          Accès Invité AORIA RH
        </CardTitle>
        <CardDescription>
          Vous avez été sélectionné(e) pour un accès gratuit de{" "}
          <strong>{durationLabel}</strong> à l&apos;assistant juridique RH.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {promoData?.features && promoData.features.length > 0 && (
          <ul className="space-y-1.5 text-sm text-muted-foreground">
            {promoData.features.map((f) => (
              <li key={f} className="flex items-start gap-2">
                <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-green-500" />
                <span>{f}</span>
              </li>
            ))}
          </ul>
        )}

        <Button className="w-full" variant="outline" onClick={handleGoogleSignIn}>
          <svg className="mr-2 h-4 w-4" viewBox="0 0 24 24">
            <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z" fill="#4285F4" />
            <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853" />
            <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" fill="#FBBC05" />
            <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335" />
          </svg>
          Continuer avec Google
        </Button>

        <div className="relative">
          <div className="absolute inset-0 flex items-center">
            <span className="w-full border-t" />
          </div>
          <div className="relative flex justify-center text-xs uppercase">
            <span className="bg-card text-muted-foreground px-2">Ou</span>
          </div>
        </div>

        <div className="flex gap-3">
          <Button className="flex-1" onClick={handleSignup}>
            Créer un compte
          </Button>
          <Button variant="outline" className="flex-1" onClick={handleLogin}>
            Se connecter
          </Button>
        </div>

        <p className="text-center text-xs text-muted-foreground">
          Pas de carte bancaire requise. Sans engagement.
        </p>
      </CardContent>
    </Card>
  );
}
