"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowRight, Lightbulb, Pause, Play, X } from "lucide-react";
import type { DiscoveryTip } from "@/lib/chat-discovery";

const ROTATION_MS = 10_000;
const HIDDEN_KEY = "aoriarh.welcome.rotating-ideas-hidden";
const controlClass =
  "text-muted-foreground hover:bg-muted hover:text-primary focus-visible:outline-ring flex size-9 shrink-0 items-center justify-center rounded-full transition-colors focus-visible:outline-2 focus-visible:outline-offset-2";
const actionClass =
  "text-primary rounded font-medium underline-offset-4 hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 disabled:opacity-50";

export function DiscoveryIdeas({
  tips,
  initialTipId,
  disabled = false,
  suspended = false,
  onAction,
}: {
  tips: readonly DiscoveryTip[];
  initialTipId: string;
  disabled?: boolean;
  suspended?: boolean;
  onAction: (tip: DiscoveryTip) => void;
}) {
  const [tipId, setTipId] = useState<string | null>(null);
  const [hidden, setHidden] = useState(false);
  const [paused, setPaused] = useState(false);
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);
  const [pageHidden, setPageHidden] = useState(false);
  const tip =
    tips.find((item) => item.id === tipId) ??
    tips.find((item) => item.id === initialTipId) ??
    tips[0];

  useEffect(() => {
    try {
      setHidden(localStorage.getItem(HIDDEN_KEY) === "true");
    } catch {
      /* Optional browser preference. */
    }
    const visibilityChanged = () => setPageHidden(document.hidden);
    visibilityChanged();
    document.addEventListener("visibilitychange", visibilityChanged);
    const reducedMotion = window.matchMedia?.(
      "(prefers-reduced-motion: reduce)"
    );
    if (reducedMotion?.matches) setPaused(true);
    return () =>
      document.removeEventListener("visibilitychange", visibilityChanged);
  }, []);

  useEffect(() => {
    if (
      !tip ||
      hidden ||
      paused ||
      hovered ||
      focused ||
      pageHidden ||
      suspended ||
      disabled ||
      tips.length < 2
    )
      return;
    const timer = window.setTimeout(() => {
      setTipId(tips[(tips.indexOf(tip) + 1) % tips.length].id);
    }, ROTATION_MS);
    return () => window.clearTimeout(timer);
  }, [
    tip,
    tips,
    hidden,
    paused,
    hovered,
    focused,
    pageHidden,
    suspended,
    disabled,
  ]);

  function setVisibility(nextHidden: boolean) {
    setHidden(nextHidden);
    try {
      localStorage.setItem(HIDDEN_KEY, String(nextHidden));
    } catch {
      /* Keep the session preference. */
    }
  }

  if (hidden)
    return (
      <div className="mt-5 text-center">
        <button
          type="button"
          onClick={() => setVisibility(false)}
          className="text-muted-foreground hover:text-primary focus-visible:outline-ring min-h-9 rounded px-3 text-xs focus-visible:outline-2"
        >
          Afficher les idées
        </button>
      </div>
    );
  if (!tip) return null;
  const action = tip.action;

  return (
    <aside
      aria-label="Idées et conseils"
      className="mt-5 flex min-h-40 items-start gap-3 py-2 sm:min-h-20 sm:items-center"
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      onFocusCapture={() => setFocused(true)}
      onBlurCapture={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget))
          setFocused(false);
      }}
    >
      <Lightbulb
        aria-hidden="true"
        className="text-primary mt-1 size-4 shrink-0 sm:mt-0"
      />
      <div className="flex min-w-0 flex-1 flex-col gap-2 sm:flex-row sm:items-center sm:gap-4">
        <p
          aria-live={paused || focused ? "polite" : "off"}
          className="min-w-0 flex-1 text-[13px] leading-5"
        >
          <span className="font-medium">{tip.title}</span>
          {" · "}
          <span className="text-muted-foreground">{tip.description}</span>{" "}
          {action &&
            (action.kind === "link" && !disabled ? (
              <Link href={action.href} className={actionClass}>
                {action.label}
              </Link>
            ) : (
              <button
                type="button"
                disabled={disabled}
                onClick={() => onAction(tip)}
                className={actionClass}
              >
                {action.label}
              </button>
            ))}
        </p>
        <div className="flex shrink-0 justify-end gap-1">
          <button
            type="button"
            aria-label="Autre conseil"
            title="Afficher une autre idée"
            className={controlClass}
            onClick={() =>
              setTipId(tips[(tips.indexOf(tip) + 1) % tips.length].id)
            }
          >
            <ArrowRight aria-hidden="true" className="size-4" />
          </button>
          <button
            type="button"
            aria-label={
              paused
                ? "Reprendre le défilement des idées"
                : "Mettre en pause les idées"
            }
            title={paused ? "Reprendre" : "Mettre en pause"}
            className={controlClass}
            onClick={() => setPaused((value) => !value)}
          >
            {paused ? (
              <Play aria-hidden="true" className="size-3.5" />
            ) : (
              <Pause aria-hidden="true" className="size-3.5" />
            )}
          </button>
          <button
            type="button"
            aria-label="Masquer les idées"
            title="Masquer les idées"
            className={controlClass}
            onClick={() => setVisibility(true)}
          >
            <X aria-hidden="true" className="size-3.5" />
          </button>
        </div>
      </div>
    </aside>
  );
}
