"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  BookOpen,
  FileSearch,
  Lightbulb,
  ListChecks,
  MoveRight,
  PencilLine,
  X,
} from "lucide-react";
import { ChatWelcomeLayout, ChatWelcomeHeading } from "./chat-welcome-layout";
import {
  ChatInput,
  type ChatInputHandle,
  type ChatInputProps,
} from "@/components/chat/chat-input";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  DISCOVERY_CATEGORIES,
  DISCOVERY_TIPS,
  getChatSuggestions,
  type ChatSuggestion,
  type DiscoveryCategory,
  type DiscoveryTip,
} from "@/lib/chat-discovery";
import { useOrg } from "@/lib/org-context";
import { cn } from "@/lib/utils";

const CATEGORY_ICONS = {
  understand: BookOpen,
  analyze: FileSearch,
  write: PencilLine,
  prepare: ListChecks,
};
const TIPS_HIDDEN_KEY = "aoriarh.welcome.tips-hidden";
const quietButton =
  "text-muted-foreground hover:text-primary focus-visible:outline-ring rounded-md text-xs transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 disabled:cursor-not-allowed disabled:opacity-50";

export function WelcomeScreen(inputProps: ChatInputProps) {
  const { profilMetier } = useOrg();
  const inputRef = useRef<ChatInputHandle>(null);
  const pendingSelection = useRef<ChatSuggestion | null>(null);
  const [examplesOpen, setExamplesOpen] = useState(false);
  const [category, setCategory] = useState<DiscoveryCategory | "all">("all");
  const [tipsHidden, setTipsHidden] = useState(false);
  const [tipId, setTipId] = useState<string | null>(null);
  const canUseDocuments = Boolean(inputProps.onAttach || inputProps.onBrowse);
  const hasDocuments = Boolean(inputProps.attachments?.length);
  const { featured, library } = getChatSuggestions(
    profilMetier,
    canUseDocuments
  );
  const tips = DISCOVERY_TIPS.filter(
    (tip) =>
      (!tip.needsDocuments || canUseDocuments) &&
      (tip.action?.kind !== "browse" || Boolean(inputProps.onBrowse))
  );
  const tip =
    tips.find((item) => item.id === tipId) ??
    tips.find(
      (item) => item.id === (hasDocuments ? "comparison" : "documents")
    ) ??
    tips[0];

  useEffect(() => {
    try {
      setTipsHidden(localStorage.getItem(TIPS_HIDDEN_KEY) === "true");
    } catch {
      /* Storage is optional. */
    }
  }, []);

  function hideTips(hidden: boolean) {
    setTipsHidden(hidden);
    try {
      localStorage.setItem(TIPS_HIDDEN_KEY, String(hidden));
    } catch {
      /* Keep the session preference. */
    }
  }

  function prepareSuggestion(suggestion: ChatSuggestion) {
    if (inputProps.disabled) return;
    inputRef.current?.prefill(suggestion.prompt);
    if (suggestion.needsDocuments && !hasDocuments)
      inputRef.current?.openAttachments();
  }

  function handleTipAction(selected: DiscoveryTip) {
    if (inputProps.disabled || !selected.action) return;
    const action = selected.action;
    if (action.kind === "prompt") inputRef.current?.prefill(action.prompt);
    if (action.kind === "attach") {
      if (action.prompt) inputRef.current?.prefill(action.prompt);
      inputRef.current?.openAttachments();
    }
    if (action.kind === "browse") inputProps.onBrowse?.();
  }

  function tipAction(selected: DiscoveryTip) {
    const action = selected.action;
    if (!action) return null;
    if (action.kind === "link" && !inputProps.disabled) {
      return (
        <Link
          href={action.href}
          className={cn(
            quietButton,
            "text-primary inline-flex min-h-8 items-center gap-1.5 font-medium"
          )}
        >
          {action.label}
          <MoveRight aria-hidden="true" className="size-3" />
        </Link>
      );
    }
    return (
      <button
        type="button"
        disabled={inputProps.disabled}
        onClick={() => handleTipAction(selected)}
        className={cn(
          quietButton,
          "text-primary min-h-8 text-left font-medium"
        )}
      >
        {action.label}
      </button>
    );
  }

  return (
    <ChatWelcomeLayout compact>
      <ChatWelcomeHeading
        compact
        badge="Aoria RH · Votre assistant juridique"
        title="Une question en droit social ?"
        description={
          <>
            Une situation à comprendre, un écrit à préparer ?{" "}
            <br className="hidden sm:block" />
            Explorez le droit social à partir de vos documents et des textes
            applicables.
          </>
        }
      />
      <ChatInput {...inputProps} ref={inputRef} variant="welcome" />
      <div className="mt-3">
        <p id="welcome-suggestions-label" className="sr-only">
          Des idées pour votre quotidien
        </p>
        <div
          role="group"
          aria-labelledby="welcome-suggestions-label"
          className="grid grid-cols-2 gap-2"
        >
          {featured.map((item) => {
            const Icon = CATEGORY_ICONS[item.category];
            return (
              <button
                key={item.id}
                type="button"
                disabled={inputProps.disabled}
                onClick={() => prepareSuggestion(item)}
                className="bg-primary/5 hover:border-primary/20 hover:bg-primary/10 focus-visible:outline-ring flex min-h-12 items-start gap-2 rounded-xl border border-transparent px-3 py-2.5 text-left transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 disabled:cursor-not-allowed disabled:opacity-50 sm:items-center sm:gap-2.5"
              >
                <Icon
                  aria-hidden="true"
                  className="text-primary mt-0.5 size-4 shrink-0 sm:mt-0"
                />
                <span className="min-w-0 text-xs leading-5 sm:text-sm">
                  {item.title}
                </span>
              </button>
            );
          })}
        </div>
        <div className="mt-1 flex items-center justify-end">
          <Dialog open={examplesOpen} onOpenChange={setExamplesOpen}>
            <DialogTrigger asChild>
              <button
                type="button"
                className={cn(quietButton, "min-h-8 shrink-0")}
                disabled={inputProps.disabled}
              >
                Voir les exemples
              </button>
            </DialogTrigger>
            <DialogContent
              className="sm:max-w-2xl"
              onCloseAutoFocus={(event) => {
                if (pendingSelection.current) {
                  event.preventDefault();
                  prepareSuggestion(pendingSelection.current);
                  pendingSelection.current = null;
                }
              }}
            >
              <DialogHeader>
                <DialogTitle>Choisissez un exemple</DialogTitle>
                <DialogDescription>
                  Choisissez un exemple, puis adaptez la demande dans la zone de
                  saisie avant de l’envoyer.
                </DialogDescription>
              </DialogHeader>
              <div
                role="group"
                aria-label="Filtrer les exemples"
                className="flex flex-wrap gap-1.5"
              >
                {[
                  "all",
                  ...Object.keys(DISCOVERY_CATEGORIES).filter((key) =>
                    library.some((item) => item.category === key)
                  ),
                ].map((key) => {
                  const value = key as DiscoveryCategory | "all";
                  return (
                    <button
                      key={key}
                      type="button"
                      aria-pressed={category === value}
                      onClick={() => setCategory(value)}
                      className={cn(
                        "focus-visible:outline-ring min-h-9 rounded-full px-3 text-xs focus-visible:outline-2",
                        category === value
                          ? "bg-primary/10 text-primary"
                          : "text-muted-foreground hover:bg-muted"
                      )}
                    >
                      {value === "all" ? "Tous" : DISCOVERY_CATEGORIES[value]}
                    </button>
                  );
                })}
              </div>
              <div className="grid gap-2 sm:grid-cols-2">
                {library
                  .filter(
                    (item) => category === "all" || item.category === category
                  )
                  .map((item) => {
                    const Icon = CATEGORY_ICONS[item.category];
                    return (
                      <button
                        key={item.id}
                        type="button"
                        disabled={inputProps.disabled}
                        onClick={() => {
                          pendingSelection.current = item;
                          setExamplesOpen(false);
                        }}
                        className="hover:border-primary/30 hover:bg-primary/5 focus-visible:outline-ring rounded-xl border p-3 text-left transition-colors focus-visible:outline-2 disabled:opacity-50"
                      >
                        <span className="text-primary mb-2 flex items-center gap-2 text-xs">
                          <Icon aria-hidden="true" className="size-3.5" />
                          {DISCOVERY_CATEGORIES[item.category]}
                        </span>
                        <span className="block text-sm font-medium">
                          {item.title}
                        </span>
                        <span className="text-muted-foreground mt-1.5 block text-xs leading-relaxed">
                          {item.prompt}
                        </span>
                      </button>
                    );
                  })}
              </div>
              <details className="border-t pt-3">
                <summary className="text-muted-foreground focus-visible:outline-ring cursor-pointer rounded text-sm focus-visible:outline-2">
                  Découvrir les capacités d’Aoria RH
                </summary>
                <div className="mt-3 space-y-3">
                  {tips.map((item) => (
                    <div key={item.id} className="bg-muted/40 rounded-lg p-3">
                      <p className="text-sm font-medium">{item.title}</p>
                      <p className="text-muted-foreground mt-1 text-xs leading-relaxed">
                        {item.description}
                      </p>
                    </div>
                  ))}
                </div>
              </details>
            </DialogContent>
          </Dialog>
        </div>
        {tipsHidden ? (
          <div className="mt-2 text-right">
            <button
              type="button"
              onClick={() => hideTips(false)}
              className={cn(quietButton, "min-h-8")}
            >
              Afficher un conseil
            </button>
          </div>
        ) : (
          tip && (
            <aside
              aria-label="Conseil d’utilisation"
              className="border-border/60 mt-4 flex items-start gap-2.5 border-t pt-3"
            >
              <Lightbulb
                aria-hidden="true"
                className="text-primary/70 mt-0.5 size-4 shrink-0"
              />
              <div className="min-w-0 flex-1">
                <div
                  aria-live="polite"
                  className="space-y-1 sm:flex sm:flex-wrap sm:items-baseline sm:space-y-0 sm:gap-x-2"
                >
                  <p className="text-xs leading-relaxed font-medium">
                    {tip.title}
                  </p>
                  <p className="text-muted-foreground text-xs leading-relaxed">
                    {tip.description}
                  </p>
                </div>
                <div className="mt-0.5 flex flex-wrap items-center gap-x-4">
                  {tipAction(tip)}
                  <button
                    type="button"
                    className={cn(quietButton, "min-h-8")}
                    onClick={() =>
                      setTipId(tips[(tips.indexOf(tip) + 1) % tips.length].id)
                    }
                  >
                    Autre conseil
                  </button>
                </div>
              </div>
              <button
                type="button"
                aria-label="Masquer les conseils"
                onClick={() => hideTips(true)}
                className={cn(
                  quietButton,
                  "-mt-1 flex size-8 shrink-0 items-center justify-center"
                )}
              >
                <X aria-hidden="true" className="size-3.5" />
              </button>
            </aside>
          )
        )}
      </div>
    </ChatWelcomeLayout>
  );
}
