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
import { Loader2, CheckCircle2, XCircle, AlertTriangle } from "lucide-react";
import type { InvitationValidateResponse } from "@/types/api";
import { authFetch, API_BASE_URL } from "@/lib/api";

type PageState = "loading" | "needsAuth" | "accepting" | "accepted" | "invalid" | "expired" | "error";

export default function AcceptInvitationPage() {
  const params = useParams();
  const router = useRouter();
  const { data: session, status: sessionStatus } = useSession();
  const token = params.token as string;

  const [pageState, setPageState] = useState<PageState>("loading");
  const [invitation, setInvitation] = useState<InvitationValidateResponse | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const acceptAttempted = useRef(false);

  // Step 1: Validate the invitation token
  useEffect(() => {
    async function validateToken() {
      try {
        const res = await fetch(`${API_BASE_URL}/invitations/${token}/validate`);
        if (!res.ok) {
          setPageState("invalid");
          return;
        }
        const data: InvitationValidateResponse = await res.json();
        setInvitation(data);

        if (data.valid) {
          // Token is valid — check auth status to decide next step
          setPageState("needsAuth");
        } else if (data.status === "expired") {
          setPageState("expired");
        } else {
          setPageState("invalid");
        }
      } catch {
        setPageState("error");
        setErrorMessage("Impossible de vérifier l'invitation. Veuillez réessayer.");
      }
    }

    validateToken();
  }, [token]);

  // Step 2: Auto-accept as soon as user is authenticated
  useEffect(() => {
    if (pageState !== "needsAuth" || sessionStatus === "loading") return;
    if (sessionStatus !== "authenticated" || !session?.access_token) return;
    if (acceptAttempted.current) return;

    acceptAttempted.current = true;
    setPageState("accepting");

    async function autoAccept() {
      try {
        const res = await authFetch(`/invitations/${token}/accept`, {
          method: "POST",
          token: session!.access_token as string,
        });

        if (!res.ok) {
          const data = await res.json().catch(() => null);
          setPageState("error");
          setErrorMessage(data?.detail || "Erreur lors de l'acceptation de l'invitation.");
          return;
        }

        setPageState("accepted");
        setTimeout(() => {
          // Full page reload to reset OrgProvider with new memberships
          window.location.href = "/chat";
        }, 1500);
      } catch {
        setPageState("error");
        setErrorMessage("Erreur réseau. Veuillez réessayer.");
      }
    }

    autoAccept();
  }, [pageState, sessionStatus, session, token, router]);

  const callbackUrl = `/invite/accept/${token}`;
  const isLoggedIn = sessionStatus === "authenticated";

  if (pageState === "loading" || sessionStatus === "loading") {
    return (
      <Card>
        <CardContent className="flex flex-col items-center gap-4 py-12">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
          <p className="text-muted-foreground">Vérification de l&apos;invitation...</p>
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
          <CardTitle>Invitation invalide</CardTitle>
          <CardDescription>
            Cette invitation n&apos;existe pas ou a déjà été utilisée.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex justify-center">
          <Button variant="outline" onClick={() => router.push("/login")}>
            Retour à la connexion
          </Button>
        </CardContent>
      </Card>
    );
  }

  if (pageState === "expired") {
    return (
      <Card>
        <CardHeader className="text-center">
          <div className="flex justify-center mb-2">
            <AlertTriangle className="h-12 w-12 text-amber-500" />
          </div>
          <CardTitle>Invitation expirée</CardTitle>
          <CardDescription>
            Cette invitation a expiré. Demandez à l&apos;administrateur de votre
            organisation de vous en envoyer une nouvelle.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex justify-center">
          <Button variant="outline" onClick={() => router.push("/login")}>
            Retour à la connexion
          </Button>
        </CardContent>
      </Card>
    );
  }

  if (pageState === "accepting") {
    return (
      <Card>
        <CardContent className="flex flex-col items-center gap-4 py-12">
          <Loader2 className="h-8 w-8 animate-spin text-primary" />
          <p className="text-muted-foreground">Acceptation de l&apos;invitation...</p>
        </CardContent>
      </Card>
    );
  }

  if (pageState === "accepted") {
    const displayName = invitation?.account_name
      ? `l'espace de travail ${invitation.account_name}`
      : invitation?.organisation_name;
    return (
      <Card>
        <CardHeader className="text-center">
          <div className="flex justify-center mb-2">
            <CheckCircle2 className="h-12 w-12 text-green-500" />
          </div>
          <CardTitle>Bienvenue !</CardTitle>
          <CardDescription>
            Vous avez rejoint <strong>{displayName}</strong>. Redirection en cours...
          </CardDescription>
        </CardHeader>
        <CardContent className="flex justify-center">
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
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
          <Button variant="outline" onClick={() => router.push("/login")}>
            Retour à la connexion
          </Button>
        </CardContent>
      </Card>
    );
  }

  // pageState === "needsAuth" and user is NOT logged in
  if (!isLoggedIn) {
    const joinLabel = invitation?.account_name
      ? `Rejoindre l'espace de travail ${invitation.account_name}`
      : `Rejoindre ${invitation?.organisation_name}`;
    const joinDescription = invitation?.account_name
      ? "Vous avez été invité(e) à rejoindre cet espace de travail sur AORIA RH."
      : "Vous avez été invité(e) à rejoindre cette organisation sur AORIA RH.";
    return (
      <Card>
        <CardHeader className="text-center">
          <CardTitle className="text-xl">{joinLabel}</CardTitle>
          <CardDescription>
            {joinDescription}
            <br />
            Connectez-vous avec l&apos;adresse <strong>{invitation?.email}</strong> pour accepter l&apos;invitation.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <Button
            className="w-full"
            variant="outline"
            onClick={() => signIn("google", { callbackUrl })}
          >
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
            <Button
              className="flex-1"
              onClick={() => router.push(`/login?callbackUrl=${encodeURIComponent(callbackUrl)}`)}
            >
              Se connecter
            </Button>
            <Button
              variant="outline"
              className="flex-1"
              onClick={() => router.push(`/register?callbackUrl=${encodeURIComponent(callbackUrl)}`)}
            >
              Créer un compte
            </Button>
          </div>
        </CardContent>
      </Card>
    );
  }

  // Fallback — should not reach here (auto-accept handles authenticated users)
  return null;
}
