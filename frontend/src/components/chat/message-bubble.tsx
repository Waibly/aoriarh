"use client";

import { useState, useCallback, useRef } from "react";
import { useSession } from "next-auth/react";
import { toast } from "sonner";
import ReactMarkdown from "react-markdown";
import rehypeSanitize from "rehype-sanitize";
import remarkGfm from "remark-gfm";
import { Copy, Check, ThumbsUp, ThumbsDown, Send, ClipboardList, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { MessageSources } from "./message-sources";
import { downloadFiche } from "@/lib/chat-api";
import { cn } from "@/lib/utils";
import type { Message } from "@/types/api";

interface MessageBubbleProps {
  message: Message;
  onFeedback?: (messageId: string, feedback: "up" | "down" | null, comment?: string | null) => void;
}

function formatTime(dateString: string): string {
  return new Date(dateString).toLocaleTimeString("fr-FR", {
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function MessageBubble({ message, onFeedback }: MessageBubbleProps) {
  const isUser = message.role === "user";
  const { data: session } = useSession();
  const [copied, setCopied] = useState(false);
  const [showCommentInput, setShowCommentInput] = useState(false);
  const [comment, setComment] = useState("");
  const [ficheLoading, setFicheLoading] = useState(false);
  const commentRef = useRef<HTMLInputElement>(null);

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(message.content);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Silently fail
    }
  }, [message.content]);

  const handleFeedback = useCallback(
    (value: "up" | "down") => {
      if (!onFeedback) return;
      const current = message.feedback as "up" | "down" | null;
      if (current === value) {
        // Toggle off
        setShowCommentInput(false);
        setComment("");
        onFeedback(message.id, null);
      } else if (value === "down") {
        // Show comment input
        setShowCommentInput(true);
        setComment("");
        onFeedback(message.id, "down");
        setTimeout(() => commentRef.current?.focus(), 50);
      } else {
        setShowCommentInput(false);
        setComment("");
        onFeedback(message.id, "up");
      }
    },
    [message.id, message.feedback, onFeedback],
  );

  const handleSubmitComment = useCallback(() => {
    if (!onFeedback || !comment.trim()) return;
    onFeedback(message.id, "down", comment.trim());
    setShowCommentInput(false);
  }, [message.id, comment, onFeedback]);

  const handleFiche = useCallback(async () => {
    const token = session?.access_token;
    if (!token || ficheLoading) return;
    setFicheLoading(true);
    try {
      await downloadFiche(message.id, token);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "La génération de la fiche a échoué.");
    } finally {
      setFicheLoading(false);
    }
  }, [message.id, session?.access_token, ficheLoading]);

  const isTemp = message.id.startsWith("temp-") || message.id.startsWith("partial-");

  if (isUser) {
    return (
      <div className="group/message flex justify-end">
        <div className="max-w-[80%]">
          <div className="bg-primary text-primary-foreground rounded-2xl rounded-tr-sm px-5 py-3">
            <p className="whitespace-pre-wrap text-base leading-relaxed">{message.content}</p>
          </div>
          <p className="text-muted-foreground mt-1 text-right text-xs opacity-0 transition-opacity group-hover/message:opacity-100">
            {formatTime(message.created_at)}
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="group/message flex w-full min-w-0 flex-col items-start">
      <div className="w-full min-w-0">
        <div className="prose prose-sm dark:prose-invert max-w-none break-words text-[0.9375rem] leading-7 text-foreground [&_h1]:mt-6 [&_h1]:mb-3 [&_h1]:text-lg [&_h1]:font-bold [&_h1]:text-foreground [&_h2]:mt-6 [&_h2]:mb-3 [&_h2]:text-[1.0625rem] [&_h2]:font-bold [&_h2]:text-foreground [&_h3]:mt-5 [&_h3]:mb-2 [&_h3]:text-base [&_h3]:font-bold [&_h3]:text-foreground [&_p]:my-3 [&_p]:leading-7 [&_a]:text-primary [&_a]:underline-offset-2 [&_strong]:font-semibold [&_strong]:text-foreground [&_ul]:my-3 [&_ul]:pl-5 [&_ul]:list-disc [&_ol]:my-3 [&_ol]:pl-5 [&_ol]:list-decimal [&_li]:my-0.5 [&_li]:leading-7 [&_li::marker]:text-foreground/70 [&_pre]:overflow-x-auto [&_table]:block [&_table]:overflow-x-auto [&>*:first-child]:mt-0 [&>*:last-child]:mb-0">
            <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeSanitize]}>
              {message.content}
            </ReactMarkdown>
          </div>
        {!isTemp && (
          <div className="mt-3 flex flex-wrap items-center gap-1.5 rounded-xl border border-border bg-muted/40 px-2.5 py-2">
            {/* Copier la réponse */}
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  className="text-muted-foreground hover:text-foreground"
                  onClick={handleCopy}
                  aria-label={copied ? "Copié" : "Copier la réponse"}
                >
                  {copied ? <Check className="size-4" /> : <Copy className="size-4" />}
                </Button>
              </TooltipTrigger>
              <TooltipContent>{copied ? "Copié" : "Copier la réponse"}</TooltipContent>
            </Tooltip>

            {/* Notation de la réponse */}
            {onFeedback && (
              <>
                <span className="text-muted-foreground ml-1 hidden text-xs sm:inline">
                  Cette réponse est-elle bonne&nbsp;?
                </span>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      className={cn(
                        "text-muted-foreground hover:text-foreground",
                        message.feedback === "up" &&
                          "bg-primary/10 text-primary hover:text-primary",
                      )}
                      onClick={() => handleFeedback("up")}
                      aria-label="Bonne réponse"
                    >
                      <ThumbsUp className="size-4" />
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>Bonne réponse</TooltipContent>
                </Tooltip>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      className={cn(
                        "text-muted-foreground hover:text-foreground",
                        message.feedback === "down" &&
                          "bg-destructive/10 text-destructive hover:text-destructive",
                      )}
                      onClick={() => handleFeedback("down")}
                      aria-label="Réponse à améliorer"
                    >
                      <ThumbsDown className="size-4" />
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>Réponse à améliorer</TooltipContent>
                </Tooltip>
              </>
            )}

            {/* Création de la fiche pratique, à droite */}
            <Button
              variant="outline"
              size="sm"
              onClick={handleFiche}
              disabled={ficheLoading}
              className="ml-auto gap-1.5 border-primary/40 bg-transparent text-primary hover:bg-primary/10 hover:text-primary dark:border-primary/40 dark:bg-transparent dark:text-primary dark:hover:bg-primary/15"
            >
              {ficheLoading ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <ClipboardList className="size-4" />
              )}
              {ficheLoading ? "Génération…" : "Créer une fiche pratique"}
            </Button>
          </div>
        )}
        {showCommentInput && (
          <div className="mt-2 flex items-center gap-2">
            <input
              ref={commentRef}
              type="text"
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") handleSubmitComment();
                if (e.key === "Escape") { setShowCommentInput(false); setComment(""); }
              }}
              placeholder="Qu'est-ce qui n'allait pas ?"
              className="flex-1 rounded-md border border-input bg-background px-3 py-1.5 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
              maxLength={1000}
            />
            <Button
              size="icon-xs"
              variant="ghost"
              onClick={handleSubmitComment}
              disabled={!comment.trim()}
              className="text-muted-foreground hover:text-foreground"
            >
              <Send className="size-3.5" />
            </Button>
          </div>
        )}
        {message.sources && message.sources.length > 0 && (
          <MessageSources sources={message.sources} />
        )}
      </div>
    </div>
  );
}
