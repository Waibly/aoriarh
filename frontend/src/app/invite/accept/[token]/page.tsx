"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useSession } from "next-auth/react";
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

type PageState = "loading" | "valid" | "invalid" | "expired" | "accepting" | "accepted" | "error";

export default function AcceptInvitationPage() {
  const params = useParams();
  const router = useRouter();
  const { data: session, status: sessionStatus } = useSession();
  const token = params.token as string;

  const [pageState, setPageState] = useState<PageState>("loading");
  const [invitation, setInvitation] = useState<InvitationValidateResponse | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

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
          setPageState("valid");
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

  async function handleAccept() {
    if (!session?.access_token) return;

    setPageState("accepting");
    try {
      const res = await authFetch(`/invitations/${token}/accept`, {
        method: "POST",
        token: session.access_token as string,
      });

      if (!res.ok) {
        const data = await res.json().catch(() => null);
        setPageState("error");
        setErrorMessage(data?.detail || "Erreur lors de l'acceptation de l'invitation.");
        return;
      }

      setPageState("accepted");
      setTimeout(() => {
        router.push("/organisation");
      }, 2000);
    } catch {
      setPageState("error");
      setErrorMessage("Erreur réseau. Veuillez réessayer.");
    }
  }

  const isLoggedIn = sessionStatus === "authenticated";
  const isSessionLoading = sessionStatus === "loading";
  const callbackUrl = `/invite/accept/${token}`;

  if (pageState === "loading" || isSessionLoading) {
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

  if (pageState === "accepted") {
    return (
      <Card>
        <CardHeader className="text-center">
          <div className="flex justify-center mb-2">
            <CheckCircle2 className="h-12 w-12 text-green-500" />
          </div>
          <CardTitle>Invitation acceptée !</CardTitle>
          <CardDescription>
            Vous avez rejoint {invitation?.organisation_name}. Redirection en cours...
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

  // pageState === "valid" or "accepting"
  return (
    <Card>
      <CardHeader className="text-center">
        <CardTitle className="text-xl">Invitation à rejoindre</CardTitle>
        <CardDescription className="text-base">
          <span className="font-semibold text-foreground">
            {invitation?.organisation_name}
          </span>
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-center text-sm text-muted-foreground">
          Vous avez été invité(e) à rejoindre cette organisation sur AORIA RH
          avec l&apos;adresse <span className="font-medium text-foreground">{invitation?.email}</span>.
        </p>

        {isLoggedIn ? (
          <Button
            className="w-full"
            onClick={handleAccept}
            disabled={pageState === "accepting"}
          >
            {pageState === "accepting" ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Acceptation en cours...
              </>
            ) : (
              "Accepter l'invitation"
            )}
          </Button>
        ) : (
          <div className="space-y-3">
            <p className="text-center text-sm text-muted-foreground">
              Connectez-vous ou créez un compte pour accepter l&apos;invitation.
            </p>
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
          </div>
        )}
      </CardContent>
    </Card>
  );
}
