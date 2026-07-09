"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useRef, useState } from "react";

import { StreamingBubble } from "@/components/chat/streaming-bubble";
import {
  Turnstile,
  TURNSTILE_ENABLED,
  type TurnstileHandle,
} from "@/components/demo/turnstile";
import { streamPublicAsk } from "@/lib/demo-api";
import type { MessageSource } from "@/types/api";

interface Turn {
  role: "user" | "assistant";
  content: string;
  sources?: MessageSource[];
}

const MAX_LEN = 500;

function DemoClient() {
  const searchParams = useSearchParams();
  const initialQuestion = (searchParams.get("q") || "").slice(0, MAX_LEN).trim();

  const [turns, setTurns] = useState<Turn[]>([]);
  const [streamingContent, setStreamingContent] = useState("");
  const [streamingSources, setStreamingSources] = useState<MessageSource[]>([]);
  const [status, setStatus] = useState<string | null>(null);
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [followUp, setFollowUp] = useState("");
  const [turnstileToken, setTurnstileToken] = useState<string | null>(null);

  const conversationIdRef = useRef<string | null>(null);
  const startedRef = useRef(false);
  const turnstileRef = useRef<TurnstileHandle>(null);

  const runQuery = useCallback(
    async (message: string) => {
      const trimmed = message.slice(0, MAX_LEN).trim();
      if (!trimmed || isStreaming) return;

      // Jeton Turnstile à usage unique : on le consomme puis on le régénère.
      const token = turnstileToken;
      if (TURNSTILE_ENABLED) setTurnstileToken(null);

      setTurns((prev) => [...prev, { role: "user", content: trimmed }]);
      setStreamingContent("");
      setStreamingSources([]);
      setStatus("Analyse de votre question...");
      setError(null);
      setDone(false);
      setIsStreaming(true);

      let acc = "";
      let srcs: MessageSource[] = [];

      await streamPublicAsk(
        {
          message: trimmed,
          turnstileToken: token,
          conversationId: conversationIdRef.current,
        },
        {
          onMeta: (cid) => {
            conversationIdRef.current = cid;
          },
          onStatus: (step) => setStatus(step),
          onSources: (s) => {
            srcs = s;
            setStreamingSources(s);
          },
          onDelta: (chunk) => {
            acc += chunk;
            setStreamingContent(acc);
          },
          onDone: () => {
            setTurns((prev) => [
              ...prev,
              { role: "assistant", content: acc, sources: srcs },
            ]);
            setStreamingContent("");
            setStreamingSources([]);
            setStatus(null);
            setIsStreaming(false);
            setDone(true);
            if (TURNSTILE_ENABLED) turnstileRef.current?.reset();
          },
          onError: (msg) => {
            setError(msg);
            setStatus(null);
            setIsStreaming(false);
            if (TURNSTILE_ENABLED) turnstileRef.current?.reset();
          },
        },
      );
    },
    [isStreaming, turnstileToken],
  );

  // Lancement automatique de la question du hero, dès que (le cas échéant) le
  // jeton Turnstile est disponible.
  useEffect(() => {
    if (startedRef.current) return;
    if (!initialQuestion) return;
    if (TURNSTILE_ENABLED && !turnstileToken) return;
    startedRef.current = true;
    void runQuery(initialQuestion);
  }, [initialQuestion, turnstileToken, runQuery]);

  const canSend =
    !isStreaming &&
    followUp.trim().length > 0 &&
    (!TURNSTILE_ENABLED || !!turnstileToken);

  const handleFollowUp = (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSend) return;
    const q = followUp;
    setFollowUp("");
    void runQuery(q);
  };

  const showWelcomeInput = !initialQuestion && turns.length === 0 && !isStreaming;

  return (
    <div className="flex flex-col gap-6">
      <div>
        <p className="inline-flex items-center gap-2 rounded-full bg-primary/10 px-3 py-1 text-xs font-medium text-primary">
          Démonstration — réponse générale
        </p>
        <h1 className="mt-3 text-2xl font-semibold tracking-tight text-foreground sm:text-3xl">
          Posez votre question de droit social
        </h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Une réponse claire et sourcée, fondée sur le droit commun (Code du
          travail, jurisprudence).
        </p>
      </div>

      {/* Distinction bien visible : démo = générique / compte = personnalisé */}
      <div className="rounded-xl border border-border bg-muted/30 p-4 text-sm leading-relaxed">
        <p className="text-foreground">
          <span className="font-semibold">Ici, en démo :</span> réponse{" "}
          <span className="font-semibold">générale</span>, fondée uniquement sur
          le droit commun (Code du travail, jurisprudence).
        </p>
        <p className="mt-1.5 text-muted-foreground">
          <span className="font-medium text-foreground">Avec un compte :</span>{" "}
          votre convention collective appliquée, vos documents internes (accords,
          règlement intérieur…) et une réponse adaptée à votre profil (DRH,
          dirigeant, élu CSE…).
        </p>
      </div>

      {/* Widget Turnstile unique et partagé : fournit le jeton pour la question
          initiale (venue du hero via ?q=) comme pour les relances. Ne rend rien
          si aucune clé n'est configurée. */}
      {TURNSTILE_ENABLED && (
        <Turnstile ref={turnstileRef} onVerify={setTurnstileToken} />
      )}

      {/* Champ initial si on arrive sans question */}
      {showWelcomeInput && (
        <form onSubmit={handleFollowUp} className="flex flex-col gap-3">
          <input
            type="text"
            value={followUp}
            onChange={(e) => setFollowUp(e.target.value)}
            maxLength={MAX_LEN}
            placeholder="Posez votre question de droit social…"
            className="w-full rounded-xl border border-border bg-white px-5 py-4 text-base text-foreground outline-none focus:ring-2 focus:ring-primary"
          />
          <button
            type="submit"
            disabled={!canSend}
            className="inline-flex items-center justify-center gap-2 self-start rounded-xl bg-primary px-6 py-3 font-semibold text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-50"
          >
            Obtenir une réponse
          </button>
        </form>
      )}

      {/* Conversation */}
      <div className="flex flex-col gap-6">
        {turns.map((turn, i) =>
          turn.role === "user" ? (
            <div key={i} className="flex justify-end">
              <div className="max-w-[85%] rounded-2xl bg-primary px-4 py-3 text-primary-foreground">
                {turn.content}
              </div>
            </div>
          ) : (
            <StreamingBubble
              key={i}
              content={turn.content}
              sources={turn.sources}
              streaming={false}
            />
          ),
        )}

        {/* Réponse en cours de streaming */}
        {isStreaming && (
          <div className="flex flex-col gap-2">
            {status && !streamingContent && (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <span className="h-2 w-2 animate-pulse rounded-full bg-primary" />
                {status}
              </div>
            )}
            {streamingContent && (
              <StreamingBubble
                content={streamingContent}
                sources={streamingSources}
              />
            )}
          </div>
        )}
      </div>

      {/* Erreur */}
      {error && (
        <div className="rounded-xl border border-border bg-muted/40 p-4 text-sm text-foreground">
          {error}
        </div>
      )}

      {/* Relance (quand une première réponse est arrivée) */}
      {turns.length > 0 && !showWelcomeInput && (
        <form
          onSubmit={handleFollowUp}
          className="flex flex-col gap-3 border-t border-border pt-6"
        >
          <input
            type="text"
            value={followUp}
            onChange={(e) => setFollowUp(e.target.value)}
            maxLength={MAX_LEN}
            disabled={isStreaming}
            placeholder="Poser une autre question…"
            className="w-full rounded-xl border border-border bg-white px-5 py-4 text-base text-foreground outline-none focus:ring-2 focus:ring-primary disabled:opacity-60"
          />
          <button
            type="submit"
            disabled={!canSend}
            className="inline-flex items-center justify-center gap-2 self-start rounded-xl border border-border px-5 py-2.5 text-sm font-semibold text-foreground transition-colors hover:bg-muted disabled:opacity-50"
          >
            Envoyer
          </button>
        </form>
      )}

      {/* Bandeau conversion (dès qu'une réponse est arrivée) */}
      {done && (
        <div className="rounded-2xl border border-primary/20 bg-primary/5 p-6">
          <h2 className="text-lg font-semibold text-foreground">
            Passez de la réponse générale à la réponse adaptée à votre entreprise
          </h2>
          <p className="mt-2 text-sm text-muted-foreground">
            Cette réponse est générale. Avec un compte, chaque réponse tient
            compte de :
          </p>
          <ul className="mt-3 space-y-1.5 text-sm text-foreground">
            {[
              "Votre convention collective (appliquée automatiquement)",
              "Vos documents internes : accords d’entreprise, règlement intérieur…",
              "Votre profil : DRH, dirigeant, élu CSE, expert-comptable…",
            ].map((item) => (
              <li key={item} className="flex items-start gap-2">
                <span className="mt-0.5 inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-primary text-[10px] font-bold text-primary-foreground">
                  ✓
                </span>
                {item}
              </li>
            ))}
          </ul>
          <p className="mt-3 text-sm text-muted-foreground">
            14 jours gratuits, sans carte bancaire.
          </p>
          <div className="mt-4 flex flex-wrap gap-3">
            <Link
              href="/register"
              className="inline-flex items-center justify-center gap-2 rounded-xl bg-primary px-6 py-3 font-semibold text-primary-foreground hover:bg-primary/90"
            >
              Créer mon compte
              <span aria-hidden>→</span>
            </Link>
            <Link
              href="/login"
              className="inline-flex items-center justify-center rounded-xl border border-border px-6 py-3 font-semibold text-foreground hover:bg-muted"
            >
              Se connecter
            </Link>
          </div>
        </div>
      )}

      <p className="text-xs text-muted-foreground">
        Information juridique à visée pédagogique, sans valeur de conseil
        juridique personnalisé.
      </p>
    </div>
  );
}

export default function DemoPage() {
  return (
    <Suspense fallback={null}>
      <DemoClient />
    </Suspense>
  );
}
