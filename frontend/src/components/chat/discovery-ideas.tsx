"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Lightbulb, Pause, Play, X } from "lucide-react";
import { DiscoveryNavigation } from "./discovery-navigation";
import { useDiscoveryRotation } from "./use-discovery-rotation";
import type { DiscoveryTip } from "@/lib/chat-discovery";

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
  const [hidden, setHidden] = useState(false);
  const rotation = useDiscoveryRotation(disabled || suspended || hidden);
  const { step, paused } = rotation;
  const firstIndex = Math.max(
    0,
    tips.findIndex((item) => item.id === initialTipId)
  );
  const tip =
    tips[(((firstIndex + step) % tips.length) + tips.length) % tips.length];

  useEffect(() => {
    try {
      setHidden(localStorage.getItem(HIDDEN_KEY) === "true");
    } catch {
      /* Optional browser preference. */
    }
  }, []);

  function setVisibility(nextHidden: boolean) {
    setHidden(nextHidden);
    try {
      localStorage.setItem(HIDDEN_KEY, String(nextHidden));
    } catch {
      /* Keep the session preference. */
    }
  }

  function playbackControls() {
    return (
      <>
        <button
          type="button"
          aria-label={
            paused
              ? "Reprendre le défilement des conseils"
              : "Mettre en pause les conseils"
          }
          title={paused ? "Reprendre" : "Mettre en pause"}
          className={controlClass}
          onClick={rotation.togglePause}
        >
          {paused ? (
            <Play aria-hidden="true" className="size-3.5" />
          ) : (
            <Pause aria-hidden="true" className="size-3.5" />
          )}
        </button>
      </>
    );
  }

  if (hidden)
    return (
      <div className="mt-5 flex items-center justify-between gap-3">
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
      className="group/discovery relative mx-5 mt-5 flex items-start gap-3 py-2 sm:mx-0 sm:min-h-20 sm:items-center"
      {...rotation.interactionProps}
    >
      <DiscoveryNavigation
        previousLabel="Afficher le conseil précédent"
        nextLabel="Afficher le conseil suivant"
        onPrevious={rotation.previous}
        onNext={rotation.next}
      />
      <Lightbulb
        aria-hidden="true"
        className="text-primary mt-1 size-4 shrink-0 sm:mt-0"
      />
      <div className="flex min-w-0 flex-1 flex-col gap-2 sm:flex-row sm:items-center sm:gap-4">
        <p
          aria-live={paused ? "polite" : "off"}
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
          {playbackControls()}
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
