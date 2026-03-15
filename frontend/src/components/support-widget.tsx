"use client";

import { useEffect, useRef, useState } from "react";
import { useSession } from "next-auth/react";
import { usePathname } from "next/navigation";
import { Headset, X, Loader2, Send } from "lucide-react";
import { toast } from "sonner";
import { apiFetch } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const TYPES = [
  { value: "bug", label: "Bug", placeholder: "Décrivez le problème rencontré..." },
  { value: "idea", label: "Idée", placeholder: "Partagez votre idée..." },
  { value: "feedback", label: "Feedback", placeholder: "Donnez-nous votre avis..." },
  { value: "question", label: "Question", placeholder: "Posez votre question..." },
] as const;

type SupportType = (typeof TYPES)[number]["value"];

function getBrowserName(): string {
  const ua = navigator.userAgent;
  if (ua.includes("Firefox")) return "Firefox";
  if (ua.includes("Edg")) return "Edge";
  if (ua.includes("Chrome")) return "Chrome";
  if (ua.includes("Safari")) return "Safari";
  return ua.slice(0, 80);
}

export function SupportWidget() {
  const { data: session } = useSession();
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const [type, setType] = useState<SupportType | null>(null);
  const [message, setMessage] = useState("");
  const [sending, setSending] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);

  const token = session?.access_token;
  const isLoggedIn = !!session?.user;

  // Close on click outside
  useEffect(() => {
    if (!open) return;
    function handleClick(e: MouseEvent) {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    // Delay to avoid immediate close on open click
    const timer = setTimeout(() => {
      document.addEventListener("mousedown", handleClick);
    }, 100);
    return () => {
      clearTimeout(timer);
      document.removeEventListener("mousedown", handleClick);
    };
  }, [open]);

  const reset = () => {
    setType(null);
    setMessage("");
  };

  const handleSubmit = async () => {
    if (!type || message.length < 5 || !token) return;
    setSending(true);
    try {
      await apiFetch("/support/", {
        method: "POST",
        token,
        body: JSON.stringify({
          type,
          message,
          page_url: pathname,
          user_agent: getBrowserName(),
        }),
      });
      toast.success("Merci pour votre retour !");
      reset();
      setOpen(false);
    } catch {
      toast.error("Impossible d'envoyer le message. Réessayez plus tard.");
    } finally {
      setSending(false);
    }
  };

  const placeholder =
    TYPES.find((t) => t.value === type)?.placeholder ?? "Votre message...";

  if (!isLoggedIn) return null;

  return (
    <>
      {/* Floating button */}
      {!open && (
        <button
          onClick={() => setOpen(true)}
          className="fixed bottom-6 right-6 z-50 flex h-12 w-12 items-center justify-center rounded-full bg-primary text-primary-foreground shadow-lg transition-transform hover:scale-105 active:scale-95"
          title="Contacter le support"
        >
          <Headset className="h-5 w-5" />
        </button>
      )}

      {/* Panel */}
      {open && (
        <div
          ref={panelRef}
          className="fixed bottom-6 right-6 z-50 w-[340px] rounded-xl border bg-card shadow-xl"
        >
          {/* Header */}
          <div className="flex items-center justify-between border-b px-4 py-3">
            <h3 className="text-sm font-semibold">Comment pouvons-nous vous aider ?</h3>
            <button
              onClick={() => setOpen(false)}
              className="rounded-md p-1 hover:bg-muted"
            >
              <X className="h-4 w-4" />
            </button>
          </div>

          {/* Body */}
          <div className="space-y-4 p-4">
            {/* Type chips */}
            <div className="flex flex-wrap gap-2">
              {TYPES.map((t) => (
                <button
                  key={t.value}
                  onClick={() => setType(t.value)}
                  className={cn(
                    "rounded-full border px-3 py-1 text-xs font-medium transition-colors",
                    type === t.value
                      ? "border-[#9952b8] bg-[#9952b8]/10 text-[#9952b8]"
                      : "border-border hover:bg-muted"
                  )}
                >
                  {t.label}
                </button>
              ))}
            </div>

            {/* Textarea */}
            <div className="space-y-1">
              <textarea
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                placeholder={placeholder}
                rows={4}
                maxLength={2000}
                className="w-full resize-none rounded-lg border bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/30"
              />
              <p className="text-right text-xs text-muted-foreground">
                {message.length}/2000
              </p>
            </div>

            {/* Submit */}
            <Button
              size="sm"
              className="w-full"
              disabled={!type || message.length < 5 || sending}
              onClick={handleSubmit}
            >
              {sending ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Send className="mr-2 h-4 w-4" />
              )}
              {sending ? "Envoi..." : "Envoyer"}
            </Button>
          </div>
        </div>
      )}
    </>
  );
}
