"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowUp,
  ClipboardList,
  FileText,
  MessagesSquare,
  Scale,
  UserRound,
} from "lucide-react";

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

// Ce qu'un compte gratuit débloque — cœur de la conversion.
const PERKS = [
  { icon: MessagesSquare, text: "Poser toutes vos questions, en conversation continue" },
  { icon: Scale, text: "Votre convention collective, appliquée automatiquement" },
  { icon: FileText, text: "Vos documents internes : accords, règlement intérieur…" },
  { icon: UserRound, text: "Des réponses adaptées à votre profil (DRH, dirigeant, élu CSE…) et à votre entreprise" },
  { icon: ClipboardList, text: "Des fiches pratiques PDF prêtes à l’emploi" },
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
  const [draft, setDraft] = useState("");
  const [turnstileToken, setTurnstileToken] = useState<string | null>(null);

  const startedRef = useRef(false);
  const turnstileRef = useRef<TurnstileHandle>(null);

  const runQuery = useCallback(
    async (message: string) => {
      const trimmed = message.slice(0, MAX_LEN).trim();
      if (!trimmed || isStreaming) return;

      const token = turnstileToken;
      if (TURNSTILE_ENABLED) setTurnstileToken(null);

      setTurns([{ role: "user", content: trimmed }]);
      setStreamingContent("");
      setStreamingSources([]);
      setStatus("Analyse de votre question...");
      setError(null);
      setDone(false);
      setIsStreaming(true);

      let acc = "";
      let srcs: MessageSource[] = [];

      await streamPublicAsk(
        { message: trimmed, turnstileToken: token },
        {
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
            setTurns([
              { role: "user", content: trimmed },
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

  // Lance automatiquement la question venue du hero (?q=), une seule fois.
  useEffect(() => {
    if (startedRef.current) return;
    if (!initialQuestion) return;
    if (TURNSTILE_ENABLED && !turnstileToken) return;
    startedRef.current = true;
    void runQuery(initialQuestion);
  }, [initialQuestion, turnstileToken, runQuery]);

  const started = turns.length > 0 || isStreaming;
  const composerDisabled = isStreaming || (TURNSTILE_ENABLED && !turnstileToken);

  const submitInitial = (e: React.FormEvent) => {
    e.preventDefault();
    if (composerDisabled || !draft.trim()) return;
    const q = draft;
    setDraft("");
    void runQuery(q);
  };

  return (
    <div className="rounded-2xl border border-border bg-white p-5 shadow-sm sm:p-8">
      {/* Badge démo — toujours visible */}
      <span className="inline-flex items-center gap-2 rounded-full bg-primary/10 px-3 py-1 text-xs font-semibold text-primary">
        <span className="h-1.5 w-1.5 rounded-full bg-primary" />
        Démonstration — réponse générale
      </span>

      {!started ? (
        /* --- État initial : intro + une seule question --- */
        <div>
          <h1 className="mt-4 text-2xl font-semibold tracking-tight text-foreground sm:text-3xl">
            Posez votre question de droit social
          </h1>
          <p className="mt-2 text-base text-muted-foreground">
            Une réponse claire et sourcée, fondée sur le droit commun (Code du
            travail, jurisprudence). Pour une réponse adaptée à votre convention
            collective et à vos documents, créez un compte gratuit.
          </p>

          {TURNSTILE_ENABLED && (
            <div className="mt-5">
              <Turnstile ref={turnstileRef} onVerify={setTurnstileToken} />
            </div>
          )}

          <form onSubmit={submitInitial} className="mt-6">
            <div className="relative rounded-xl border border-border bg-white transition focus-within:border-primary focus-within:ring-2 focus-within:ring-primary/20">
              <textarea
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    submitInitial(e);
                  }
                }}
                rows={2}
                maxLength={MAX_LEN}
                placeholder="Posez votre question de droit social…"
                className="block w-full resize-none bg-transparent px-4 py-3.5 pr-14 text-base text-foreground placeholder:text-muted-foreground focus:outline-none"
              />
              <button
                type="submit"
                disabled={composerDisabled || !draft.trim()}
                aria-label="Obtenir une réponse"
                className="absolute bottom-2.5 right-2.5 inline-flex h-10 w-10 items-center justify-center rounded-lg bg-primary text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-40"
              >
                <ArrowUp className="h-4 w-4" strokeWidth={2.5} />
              </button>
            </div>
          </form>
        </div>
      ) : (
        /* --- Conversation : une question, une réponse --- */
        <div className="mt-6 flex flex-col gap-6">
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

          {error && (
            <div className="rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm text-foreground">
              {error}
            </div>
          )}

          {/* Bloc de conversion — remplace toute relance (le chat est réservé au compte) */}
          {done && (
            <div className="mt-2 rounded-2xl border border-primary/20 bg-primary/[0.06] p-6 sm:p-7">
              <h2 className="text-xl font-semibold tracking-tight text-foreground">
                Débloquez tout Aoria RH — gratuitement
              </h2>
              <p className="mt-1.5 text-sm text-muted-foreground">
                Cette réponse est <span className="font-medium text-foreground">générale</span>.
                Créez un compte pour continuer et l’adapter à votre entreprise :
              </p>
              <ul className="mt-4 grid gap-3 sm:grid-cols-2">
                {PERKS.map((p) => (
                  <li key={p.text} className="flex items-start gap-2.5 text-sm text-foreground">
                    <span className="mt-0.5 inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                      <p.icon className="h-3.5 w-3.5" strokeWidth={2.2} />
                    </span>
                    {p.text}
                  </li>
                ))}
              </ul>
              <div className="mt-6 flex flex-wrap items-center gap-4">
                <Link
                  href="/register"
                  className="inline-flex items-center justify-center gap-2 rounded-xl bg-primary px-6 py-3 text-base font-semibold text-primary-foreground transition-colors hover:bg-primary/90"
                >
                  Créer mon compte gratuit
                  <span aria-hidden>→</span>
                </Link>
                <Link
                  href="/login"
                  className="text-sm font-medium text-foreground hover:text-primary"
                >
                  J’ai déjà un compte
                </Link>
              </div>
              <p className="mt-3 text-xs text-muted-foreground">
                14 jours gratuits, sans carte bancaire, sans engagement.
              </p>
            </div>
          )}
        </div>
      )}

      <p className="mt-8 border-t border-border pt-4 text-xs text-muted-foreground">
        Information juridique à visée pédagogique, sans valeur de conseil
        juridique personnalisé. Aoria RH est une IA et peut faire des erreurs —
        vérifiez les informations importantes.
      </p>
    </div>
  );
}

// Indicateur de statut repris de la page de chat de l'app (message-list.tsx).
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
