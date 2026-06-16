"use client";

import { useState, useCallback, useRef } from "react";
import { useSession } from "next-auth/react";
import { toast } from "sonner";
import ReactMarkdown from "react-markdown";
import rehypeSanitize from "rehype-sanitize";
import remarkGfm from "remark-gfm";
import {
  Copy,
  Check,
  ThumbsUp,
  ThumbsDown,
  Send,
  ClipboardList,
  Loader2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { MessageSources } from "./message-sources";
import { downloadFiche } from "@/lib/chat-api";
import { cn } from "@/lib/utils";
import type { Message } from "@/types/api";

interface MessageBubbleProps {
  message: Message;
  onFeedback?: (
    messageId: string,
    feedback: "up" | "down" | null,
    comment?: string | null
  ) => void;
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
  const proseRef = useRef<HTMLDivElement>(null);

  const handleCopy = useCallback(
    async (format: "text" | "markdown") => {
      // "text" copies what the user sees (rendered, no formatting symbols);
      // "markdown" copies the raw source so formatting survives in a
      // Markdown-aware editor.
      const value =
        format === "markdown"
          ? message.content
          : (proseRef.current?.innerText ?? message.content);
      try {
        await navigator.clipboard.writeText(value);
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      } catch {
        // Silently fail
      }
    },
    [message.content]
  );

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
    [message.id, message.feedback, onFeedback]
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
      toast.error(
        err instanceof Error
          ? err.message
          : "La génération de la fiche a échoué."
      );
    } finally {
      setFicheLoading(false);
    }
  }, [message.id, session?.access_token, ficheLoading]);

  const isTemp =
    message.id.startsWith("temp-") || message.id.startsWith("partial-");

  if (isUser) {
    return (
      <div className="group/message flex justify-end">
        <div className="max-w-[80%]">
          <div className="bg-primary text-primary-foreground rounded-2xl rounded-tr-sm px-5 py-3">
            <p className="text-base leading-relaxed whitespace-pre-wrap">
              {message.content}
            </p>
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
        <div
          ref={proseRef}
          className="prose prose-sm dark:prose-invert text-foreground [&_h1]:text-foreground [&_h2]:text-foreground [&_h3]:text-foreground [&_a]:text-primary [&_strong]:text-foreground [&_li::marker]:text-foreground/70 max-w-none text-[0.9375rem] leading-7 break-words [&_a]:underline-offset-2 [&_h1]:mt-6 [&_h1]:mb-3 [&_h1]:text-lg [&_h1]:font-bold [&_h2]:mt-6 [&_h2]:mb-3 [&_h2]:text-[1.0625rem] [&_h2]:font-bold [&_h3]:mt-5 [&_h3]:mb-2 [&_h3]:text-base [&_h3]:font-bold [&_li]:my-0.5 [&_li]:leading-7 [&_ol]:my-3 [&_ol]:list-decimal [&_ol]:pl-5 [&_p]:my-3 [&_p]:leading-7 [&_pre]:overflow-x-auto [&_strong]:font-semibold [&_table]:block [&_table]:overflow-x-auto [&_ul]:my-3 [&_ul]:list-disc [&_ul]:pl-5 [&>*:first-child]:mt-0 [&>*:last-child]:mb-0"
        >
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            rehypePlugins={[rehypeSanitize]}
          >
            {message.content}
          </ReactMarkdown>
        </div>
        {!isTemp && (
          <div className="border-primary/15 bg-primary/5 my-8 flex flex-wrap items-center gap-1.5 rounded-xl border px-2.5 py-2">
            {/* Copier la réponse — choix du format */}
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  className="text-primary/70 hover:text-primary"
                  aria-label={copied ? "Copié" : "Copier la réponse"}
                >
                  {copied ? (
                    <Check className="size-4" />
                  ) : (
                    <Copy className="size-4" />
                  )}
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start" className="w-72">
                <DropdownMenuItem
                  onSelect={() => handleCopy("text")}
                  className="flex-col items-start gap-0.5"
                >
                  <span className="font-medium">Texte simple</span>
                  <span className="text-muted-foreground text-xs">
                    Sans symboles de mise en forme — idéal pour un e-mail ou
                    Word
                  </span>
                </DropdownMenuItem>
                <DropdownMenuItem
                  onSelect={() => handleCopy("markdown")}
                  className="flex-col items-start gap-0.5"
                >
                  <span className="font-medium">Texte mis en forme</span>
                  <span className="text-muted-foreground text-xs">
                    Conserve titres, listes et gras — pour Notion, Obsidian…
                    (Markdown)
                  </span>
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>

            {/* Notation de la réponse */}
            {onFeedback && (
              <>
                <span className="text-foreground ml-1 hidden text-xs sm:inline">
                  Cette réponse est-elle bonne&nbsp;?
                </span>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      className={cn(
                        "text-primary/70 hover:text-primary",
                        message.feedback === "up" &&
                          "bg-primary/10 text-primary hover:text-primary"
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
                        "text-primary/70 hover:text-destructive",
                        message.feedback === "down" &&
                          "bg-destructive/10 text-destructive hover:text-destructive"
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
              className="border-primary/40 text-primary hover:bg-primary/10 hover:text-primary dark:border-primary/40 dark:bg-card dark:text-primary dark:hover:bg-primary/15 ml-auto gap-1.5 bg-white"
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
                if (e.key === "Escape") {
                  setShowCommentInput(false);
                  setComment("");
                }
              }}
              placeholder="Qu'est-ce qui n'allait pas ?"
              className="border-input bg-background placeholder:text-muted-foreground focus:ring-ring flex-1 rounded-md border px-3 py-1.5 text-sm focus:ring-1 focus:outline-none"
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
