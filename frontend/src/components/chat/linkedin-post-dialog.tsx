"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AlertTriangle, Check, Copy, Loader2, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { generateLinkedInPost, type LinkedInPostResult } from "@/lib/chat-api";
import { cn } from "@/lib/utils";

interface LinkedInPostDialogProps {
  messageId: string;
  token: string | undefined;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function LinkedInPostDialog({
  messageId,
  token,
  open,
  onOpenChange,
}: LinkedInPostDialogProps) {
  const [post, setPost] = useState<LinkedInPostResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const inFlightRef = useRef(false);

  const requestPost = useCallback(async () => {
    if (inFlightRef.current) return;
    if (!token) {
      setError("Session indisponible. Veuillez actualiser la page.");
      return;
    }

    inFlightRef.current = true;
    setLoading(true);
    setError(null);
    try {
      const generated = await generateLinkedInPost(messageId, token);
      setPost(generated);
      setCopied(false);
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : "La génération du post LinkedIn a échoué."
      );
    } finally {
      inFlightRef.current = false;
      setLoading(false);
    }
  }, [messageId, token]);

  useEffect(() => {
    if (open && !post && !error && !inFlightRef.current) {
      void requestPost();
    }
  }, [error, open, post, requestPost]);

  const handleRetry = useCallback(() => {
    setError(null);
    void requestPost();
  }, [requestPost]);

  const handleCopy = useCallback(async () => {
    if (!post) return;
    try {
      await navigator.clipboard.writeText(post.content);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.error(
        "Impossible de copier le post. Sélectionnez le texte manuellement."
      );
    }
  }, [post]);

  const overLimit = (post?.character_count ?? 0) > 3000;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex h-[92dvh] max-h-[92dvh] flex-col sm:h-[88vh] sm:max-h-[88vh] sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>Brouillon de post LinkedIn</DialogTitle>
          <DialogDescription>
            Vérifiez le contenu et les sources avant publication sur LinkedIn.
          </DialogDescription>
        </DialogHeader>

        {loading && !post && (
          <div
            className="text-muted-foreground flex min-h-0 flex-1 flex-col items-center justify-center gap-3"
            role="status"
          >
            <Loader2 className="text-primary size-7 animate-spin" />
            <p className="text-sm">Génération du post…</p>
          </div>
        )}

        {error && !post && (
          <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-4 text-center">
            <AlertTriangle className="text-destructive size-7" />
            <p className="text-muted-foreground max-w-md text-sm">{error}</p>
            <Button variant="outline" onClick={handleRetry} disabled={loading}>
              {loading ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <RefreshCw className="size-4" />
              )}
              Réessayer
            </Button>
          </div>
        )}

        {post && (
          <div className="flex min-h-0 flex-1 flex-col gap-3">
            {post.warnings.length > 0 && (
              <div
                className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-2.5 text-amber-900 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-200"
                role="alert"
              >
                <div className="flex gap-2">
                  <AlertTriangle className="mt-0.5 size-4 shrink-0" />
                  <ul className="space-y-1 text-xs">
                    {post.warnings.map((warning, index) => (
                      <li key={`${index}-${warning}`}>{warning}</li>
                    ))}
                  </ul>
                </div>
              </div>
            )}

            <textarea
              aria-label="Post LinkedIn généré"
              value={post.content}
              readOnly
              spellCheck={false}
              className="border-input bg-background text-foreground focus-visible:ring-ring min-h-80 w-full flex-1 resize-none rounded-lg border p-4 text-sm leading-6 focus-visible:ring-2 focus-visible:outline-none"
            />

            <p
              className={cn(
                "text-muted-foreground text-right text-xs tabular-nums",
                overLimit && "text-destructive font-medium"
              )}
            >
              {post.character_count.toLocaleString("fr-FR")} / 3 000 caractères
            </p>
          </div>
        )}

        <DialogFooter className="mt-auto shrink-0">
          <Button onClick={handleCopy} disabled={!post || loading}>
            {copied ? (
              <Check className="size-4" />
            ) : (
              <Copy className="size-4" />
            )}
            {copied ? "Post copié" : "Copier le post"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
