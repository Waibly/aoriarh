"use client";

import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useRef,
} from "react";

export const TURNSTILE_SITE_KEY =
  process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY || "";

/** True quand une clé site est configurée : sinon la démo tourne sans captcha
 *  (le backend saute aussi la vérification quand son secret est vide). */
export const TURNSTILE_ENABLED = TURNSTILE_SITE_KEY.length > 0;

const SCRIPT_SRC =
  "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";

interface TurnstileWindow extends Window {
  turnstile?: {
    render: (
      el: HTMLElement,
      opts: {
        sitekey: string;
        callback: (token: string) => void;
        "error-callback"?: () => void;
        "expired-callback"?: () => void;
        theme?: "light" | "dark" | "auto";
        size?: "normal" | "flexible" | "compact";
      },
    ) => string;
    reset: (widgetId?: string) => void;
  };
}

function loadScript(): Promise<void> {
  return new Promise((resolve, reject) => {
    if (typeof window === "undefined") return resolve();
    if ((window as TurnstileWindow).turnstile) return resolve();
    const existing = document.querySelector<HTMLScriptElement>(
      `script[src^="https://challenges.cloudflare.com/turnstile"]`,
    );
    if (existing) {
      existing.addEventListener("load", () => resolve());
      existing.addEventListener("error", () => reject());
      return;
    }
    const script = document.createElement("script");
    script.src = SCRIPT_SRC;
    script.async = true;
    script.defer = true;
    script.onload = () => resolve();
    script.onerror = () => reject();
    document.head.appendChild(script);
  });
}

export interface TurnstileHandle {
  /** Réinitialise le widget pour obtenir un nouveau jeton (jetons à usage unique). */
  reset: () => void;
}

interface TurnstileProps {
  onVerify: (token: string) => void;
  onExpire?: () => void;
}

/**
 * Widget Cloudflare Turnstile (mode explicite). Ne rend rien si aucune clé
 * n'est configurée. Un jeton Turnstile est à usage unique : après chaque envoi,
 * appeler `reset()` via la ref pour en régénérer un.
 */
export const Turnstile = forwardRef<TurnstileHandle, TurnstileProps>(
  function Turnstile({ onVerify, onExpire }, ref) {
    const containerRef = useRef<HTMLDivElement>(null);
    const widgetIdRef = useRef<string | null>(null);

    useImperativeHandle(ref, () => ({
      reset: () => {
        const w = window as TurnstileWindow;
        if (w.turnstile && widgetIdRef.current) {
          w.turnstile.reset(widgetIdRef.current);
        }
      },
    }));

    useEffect(() => {
      if (!TURNSTILE_ENABLED) return;
      let cancelled = false;
      loadScript()
        .then(() => {
          if (cancelled) return;
          const w = window as TurnstileWindow;
          if (!w.turnstile || !containerRef.current) return;
          if (widgetIdRef.current) return; // déjà rendu
          widgetIdRef.current = w.turnstile.render(containerRef.current, {
            sitekey: TURNSTILE_SITE_KEY,
            callback: (token: string) => onVerify(token),
            "expired-callback": () => onExpire?.(),
            theme: "light",
            size: "flexible",
          });
        })
        .catch(() => {
          /* échec de chargement — la page gère l'absence de jeton */
        });
      return () => {
        cancelled = true;
      };
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    if (!TURNSTILE_ENABLED) return null;
    return <div ref={containerRef} className="my-3" />;
  },
);
