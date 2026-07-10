"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { Check } from "lucide-react";

import { ChatInput } from "@/components/chat/chat-input";
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

const ACCOUNT_PERKS = [
  "Votre convention collective, appliquée automatiquement",
  "Vos documents internes : accords d’entreprise, règlement intérieur…",
  "Une réponse adaptée à votre profil (DRH, dirigeant, élu CSE…)",
];

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

  const hasConversation = turns.length > 0 || isStreaming;
  const composerDisabled = isStreaming || (TURNSTILE_ENABLED && !turnstileToken);

  return (
    <div className="flex flex-col gap-8 py-2">
      {/* En-tête */}
      <div>
        <span className="inline-flex items-center gap-2 rounded-full bg-primary/10 px-3 py-1 text-xs font-semibold text-primary">
          <span className="h-1.5 w-1.5 rounded-full bg-primary" />
          Démonstration — réponse générale
        </span>
        <h1 className="mt-4 text-3xl font-semibold tracking-tight text-foreground sm:text-4xl">
          Posez votre question de droit social
        </h1>
        <p className="mt-3 max-w-2xl text-base text-muted-foreground">
          Une réponse claire et sourcée, fondée sur le droit commun (Code du
          travail, jurisprudence).
        </p>
      </div>

      {/* Distinction démo (générique) / compte (personnalisé) */}
      <div className="overflow-hidden rounded-2xl border border-border">
        <div className="border-l-2 border-primary bg-primary/5 px-5 py-4">
          <p className="text-sm text-foreground">
            <span className="font-semibold">En démo :</span> réponse{" "}
            <span className="font-semibold">générale</span>, fondée uniquement
            sur le droit commun (Code du travail, jurisprudence).
          </p>
        </div>
        <div className="bg-card px-5 py-4">
          <p className="text-sm text-muted-foreground">
            <span className="font-medium text-foreground">Avec un compte :</span>{" "}
            votre convention collective, vos documents internes et une réponse
            adaptée à votre profil.
          </p>
        </div>
      </div>

      {/* Widget Turnstile partagé (rien si aucune clé configurée) */}
      {TURNSTILE_ENABLED && (
        <Turnstile ref={turnstileRef} onVerify={setTurnstileToken} />
      )}

      {/* Conversation */}
      {hasConversation && (
        <div className="flex flex-col gap-6">
          {turns.map((turn, i) =>
            turn.role === "user" ? (
              <div key={i} className="flex justify-end">
                <div className="max-w-[85%] rounded-2xl rounded-tr-sm bg-primary px-5 py-3 text-primary-foreground">
                  <p className="whitespace-pre-wrap text-base leading-relaxed">
                    {turn.content}
                  </p>
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

          {isStreaming && !streamingContent && <StatusIndicator step={status} />}
          {isStreaming && streamingContent && (
            <StreamingBubble
              content={streamingContent}
              sources={streamingSources}
            />
          )}
        </div>
      )}

      {/* Erreur */}
      {error && (
        <div className="rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm text-foreground">
          {error}
        </div>
      )}

      {/* Bandeau de conversion (après la première réponse) */}
      {done && (
        <div className="rounded-2xl border border-primary/20 bg-primary/5 p-6">
          <h2 className="text-lg font-semibold text-foreground">
            Passez à la réponse adaptée à votre entreprise
          </h2>
          <ul className="mt-4 space-y-2.5">
            {ACCOUNT_PERKS.map((perk) => (
              <li key={perk} className="flex items-start gap-2.5 text-sm text-foreground">
                <span className="mt-0.5 inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground">
                  <Check className="h-3 w-3" strokeWidth={3} />
                </span>
                {perk}
              </li>
            ))}
          </ul>
          <div className="mt-5 flex flex-wrap items-center gap-3">
            <Link
              href="/register"
              className="inline-flex items-center justify-center gap-2 rounded-xl bg-primary px-6 py-3 font-semibold text-primary-foreground transition-colors hover:bg-primary/90"
            >
              Créer mon compte
              <span aria-hidden>→</span>
            </Link>
            <span className="text-sm text-muted-foreground">
              14 jours gratuits, sans carte bancaire
            </span>
          </div>
        </div>
      )}

      {/* Composer (le vrai champ de saisie de l'app) */}
      <div className="-mx-4 sm:-mx-6">
        <ChatInput onSend={runQuery} disabled={composerDisabled} />
      </div>
    </div>
  );
}

// Indicateur de statut repris à l'identique de la page de chat de l'app
// (message-list.tsx) pour un rendu cohérent.
function StatusIndicator({ step }: { step?: string | null }) {
  return (
    <div className="flex items-start gap-3">
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary/10">
        <svg
          className="h-4 w-4 text-primary"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
        >
          <path
            d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2z"
            strokeOpacity="0.3"
          />
          <path d="M12 2a10 10 0 0 1 10 10" strokeLinecap="round">
            <animateTransform
              attributeName="transform"
              type="rotate"
              from="0 12 12"
              to="360 12 12"
              dur="1s"
              repeatCount="indefinite"
            />
          </path>
        </svg>
      </div>
      <div className="flex items-center pt-1.5">
        <span className="animate-pulse text-sm text-muted-foreground">
          {step || "Réflexion en cours..."}
        </span>
      </div>
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
