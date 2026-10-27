"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  BookOpen,
  Pause,
  Play,
  FileSearch,
  ListChecks,
  PencilLine,
} from "lucide-react";
import { ChatWelcomeLayout, ChatWelcomeHeading } from "./chat-welcome-layout";
import { DiscoveryIdeas } from "./discovery-ideas";
import { DiscoveryNavigation } from "./discovery-navigation";
import { useDiscoveryRotation } from "./use-discovery-rotation";
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
const quietButton =
  "text-muted-foreground hover:text-primary focus-visible:outline-ring min-h-9 rounded px-2 text-xs transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 disabled:cursor-not-allowed disabled:opacity-50";
export function WelcomeScreen(inputProps: ChatInputProps) {
  const { profilMetier } = useOrg();
  const inputRef = useRef<ChatInputHandle>(null);
  const pendingSelection = useRef<ChatSuggestion | null>(null);
  const [examplesOpen, setExamplesOpen] = useState(false);
  const [category, setCategory] = useState<DiscoveryCategory | "all">("all");
  const rotation = useDiscoveryRotation(
    examplesOpen || Boolean(inputProps.disabled)
  );
  const { step, setStep } = rotation;
  const canUseDocuments = Boolean(inputProps.onAttach || inputProps.onBrowse);
  const canBrowse = Boolean(inputProps.onBrowse);
  const hasDocuments = Boolean(inputProps.attachments?.length);
  const { featured, library } = getChatSuggestions(
    profilMetier,
    canUseDocuments
  );
  const tips = useMemo(
    () =>
      DISCOVERY_TIPS.filter(
        (tip) =>
          (!tip.needsDocuments || canUseDocuments) &&
          (tip.action?.kind !== "browse" || canBrowse)
      ),
    [canUseDocuments, canBrowse]
  );
  const pageCount = Math.ceil(featured.length / 2);
  const activePage = ((step % pageCount) + pageCount) % pageCount;

  useEffect(() => {
    setStep(0);
  }, [profilMetier, canUseDocuments, setStep]);

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

  return (
    <ChatWelcomeLayout compact>
      <ChatWelcomeHeading
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
      <div>
        <DiscoveryIdeas
          tips={tips}
          initialTipId={hasDocuments ? "comparison" : "documents"}
          disabled={inputProps.disabled}
          suspended={examplesOpen}
          onAction={handleTipAction}
        />
        <div className="mt-7" {...rotation.interactionProps}>
          <div className="mb-4 flex items-center justify-between gap-4">
            <p id="welcome-suggestions-label" className="text-sm font-medium">
              Des idées pour votre quotidien
            </p>
            <div className="flex shrink-0 items-center gap-1">
              <button
                type="button"
                aria-label={
                  rotation.paused
                    ? "Reprendre le défilement des idées"
                    : "Mettre en pause les idées"
                }
                title={rotation.paused ? "Reprendre" : "Mettre en pause"}
                onClick={rotation.togglePause}
                className="text-muted-foreground hover:text-primary focus-visible:outline-ring flex size-8 items-center justify-center rounded focus-visible:outline-2 focus-visible:outline-offset-2"
              >
                {rotation.paused ? (
                  <Play aria-hidden="true" className="size-3.5" />
                ) : (
                  <Pause aria-hidden="true" className="size-3.5" />
                )}
              </button>
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
                      Choisissez un exemple, puis adaptez la demande dans la
                      zone de saisie avant de l’envoyer.
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
                          {value === "all"
                            ? "Tous"
                            : DISCOVERY_CATEGORIES[value]}
                        </button>
                      );
                    })}
                  </div>
                  <div className="grid gap-2 sm:grid-cols-2">
                    {library
                      .filter(
                        (item) =>
                          category === "all" || item.category === category
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
                        <div
                          key={item.id}
                          className="bg-muted/40 rounded-lg p-3"
                        >
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
          </div>
          <div className="relative mx-5 sm:mx-0">
            <div
              role="group"
              aria-labelledby="welcome-suggestions-label"
              aria-roledescription="carrousel"
              className="-m-1 overflow-hidden"
            >
              <div
                className="flex transition-transform duration-500 ease-out motion-reduce:transition-none"
                style={{ transform: `translateX(-${activePage * 100}%)` }}
              >
                {Array.from({ length: pageCount }, (_, page) => (
                  <div
                    key={page}
                    data-carousel-page={page}
                    data-active={page === activePage}
                    aria-hidden={page !== activePage}
                    inert={page !== activePage}
                    className="grid w-full shrink-0 grid-cols-2 gap-3 p-1 sm:gap-4"
                  >
                    {featured.slice(page * 2, page * 2 + 2).map((item) => {
                      const Icon = CATEGORY_ICONS[item.category];
                      return (
                        <button
                          key={item.id}
                          type="button"
                          aria-label={item.title}
                          aria-describedby={"welcome-example-" + item.id}
                          disabled={inputProps.disabled}
                          onClick={() => prepareSuggestion(item)}
                          className="border-border/70 hover:border-primary/35 hover:bg-primary/[0.025] focus-visible:outline-ring bg-background/30 flex min-h-28 flex-col gap-3 rounded-2xl border p-4 text-left transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 disabled:cursor-not-allowed disabled:opacity-50 sm:p-5"
                        >
                          <span className="flex flex-col items-start gap-3 sm:flex-row sm:items-center">
                            <span className="bg-primary/8 text-primary flex size-8 shrink-0 items-center justify-center rounded-lg">
                              <Icon aria-hidden="true" className="size-4" />
                            </span>
                            <span className="text-sm leading-5 font-semibold">
                              {item.title}
                            </span>
                          </span>
                          <span
                            id={"welcome-example-" + item.id}
                            className="text-muted-foreground text-sm leading-6"
                          >
                            {item.description}
                          </span>
                        </button>
                      );
                    })}
                  </div>
                ))}
              </div>
            </div>
            <DiscoveryNavigation
              previousLabel="Afficher les idées précédentes"
              nextLabel="Afficher les idées suivantes"
              onPrevious={rotation.previous}
              onNext={rotation.next}
            />
          </div>
        </div>
      </div>
    </ChatWelcomeLayout>
  );
}
