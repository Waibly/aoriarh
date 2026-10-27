"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  BookOpen,
  ChevronLeft,
  ChevronRight,
  FileSearch,
  ListChecks,
  PencilLine,
} from "lucide-react";
import { ChatWelcomeLayout, ChatWelcomeHeading } from "./chat-welcome-layout";
import { DiscoveryIdeas } from "./discovery-ideas";
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
const ROTATION_MS = 5_000;
const carouselArrow =
  "text-primary border-border/70 hover:border-primary/35 hover:bg-primary/5 focus-visible:outline-ring flex size-9 shrink-0 items-center justify-center rounded-full border transition-colors focus-visible:outline-2 focus-visible:outline-offset-2";

export function WelcomeScreen(inputProps: ChatInputProps) {
  const { profilMetier } = useOrg();
  const inputRef = useRef<ChatInputHandle>(null);
  const pendingSelection = useRef<ChatSuggestion | null>(null);
  const [examplesOpen, setExamplesOpen] = useState(false);
  const [category, setCategory] = useState<DiscoveryCategory | "all">("all");
  const [step, setStep] = useState(0);
  const [paused, setPaused] = useState(false);
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);
  const [pageHidden, setPageHidden] = useState(false);
  const next = useCallback(() => setStep((value) => value + 1), []);
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
    const updateVisibility = () => setPageHidden(document.hidden);
    updateVisibility();
    document.addEventListener("visibilitychange", updateVisibility);
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches)
      setPaused(true);
    return () =>
      document.removeEventListener("visibilitychange", updateVisibility);
  }, []);

  useEffect(() => {
    setStep(0);
  }, [profilMetier, canUseDocuments]);

  useEffect(() => {
    if (
      paused ||
      hovered ||
      focused ||
      pageHidden ||
      examplesOpen ||
      inputProps.disabled
    )
      return;
    const timer = window.setTimeout(next, ROTATION_MS);
    return () => window.clearTimeout(timer);
  }, [
    step,
    paused,
    hovered,
    focused,
    pageHidden,
    examplesOpen,
    inputProps.disabled,
    next,
    profilMetier,
    canUseDocuments,
  ]);

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
      <div
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
        onFocusCapture={() => setFocused(true)}
        onBlurCapture={(event) => {
          if (!event.currentTarget.contains(event.relatedTarget))
            setFocused(false);
        }}
      >
        <DiscoveryIdeas
          tips={tips}
          initialTipId={hasDocuments ? "comparison" : "documents"}
          disabled={inputProps.disabled}
          step={step}
          paused={paused}
          onNext={next}
          onTogglePause={() => setPaused((value) => !value)}
          onAction={handleTipAction}
        />
        <div className="mt-7">
          <div className="mb-4 flex items-center justify-between gap-4">
            <p id="welcome-suggestions-label" className="text-sm font-medium">
              Des idées pour votre quotidien
            </p>
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
                    Choisissez un exemple, puis adaptez la demande dans la zone
                    de saisie avant de l’envoyer.
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
          <div
            className="mt-3 flex items-center justify-center gap-2"
            role="group"
            aria-label="Pages du carrousel"
          >
            <button
              type="button"
              aria-label="Afficher les idées précédentes"
              title="Idées précédentes"
              onClick={() => setStep((value) => value - 1)}
              className={carouselArrow}
            >
              <ChevronLeft aria-hidden="true" className="size-4" />
            </button>
            {Array.from({ length: pageCount }, (_, page) => (
              <button
                key={page}
                type="button"
                aria-label={`Afficher les tuiles ${page * 2 + 1} à ${Math.min(page * 2 + 2, featured.length)}`}
                aria-current={page === activePage ? "true" : undefined}
                onClick={() =>
                  setStep(
                    (value) =>
                      value + ((page - activePage + pageCount) % pageCount)
                  )
                }
                className="focus-visible:outline-ring flex size-9 items-center justify-center rounded-full focus-visible:outline-2"
              >
                <span
                  aria-hidden="true"
                  className={cn(
                    "h-1.5 rounded-full transition-all motion-reduce:transition-none",
                    page === activePage
                      ? "bg-primary w-5"
                      : "bg-primary/20 w-1.5"
                  )}
                />
              </button>
            ))}
            <button
              type="button"
              aria-label="Afficher les idées suivantes"
              title="Idées suivantes"
              onClick={next}
              className={carouselArrow}
            >
              <ChevronRight aria-hidden="true" className="size-4" />
            </button>
          </div>
        </div>
      </div>
    </ChatWelcomeLayout>
  );
}
