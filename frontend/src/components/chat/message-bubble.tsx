"use client";

import { useState, useCallback, useRef } from "react";
import ReactMarkdown from "react-markdown";
import rehypeSanitize from "rehype-sanitize";
import remarkGfm from "remark-gfm";
import { Copy, Check, ThumbsUp, ThumbsDown, Send } from "lucide-react";
import { Button } from "@/components/ui/button";
import { MessageSources } from "./message-sources";
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
  const [copied, setCopied] = useState(false);
  const [showCommentInput, setShowCommentInput] = useState(false);
  const [comment, setComment] = useState("");
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
    <div className="group/message flex flex-col items-start">
      <div className="w-full">
        <div className="prose prose-sm dark:prose-invert max-w-none text-[0.9375rem] leading-7 text-foreground [&_h1]:mt-6 [&_h1]:mb-3 [&_h1]:text-lg [&_h1]:font-bold [&_h1]:text-foreground [&_h2]:mt-6 [&_h2]:mb-3 [&_h2]:text-[1.0625rem] [&_h2]:font-bold [&_h2]:text-foreground [&_h3]:mt-5 [&_h3]:mb-2 [&_h3]:text-base [&_h3]:font-bold [&_h3]:text-foreground [&_p]:my-3 [&_p]:leading-7 [&_a]:text-primary [&_a]:underline-offset-2 [&_strong]:font-semibold [&_strong]:text-foreground [&_ul]:my-3 [&_ul]:pl-5 [&_ul]:list-disc [&_ol]:my-3 [&_ol]:pl-5 [&_ol]:list-decimal [&_li]:my-0.5 [&_li]:leading-7 [&_li::marker]:text-foreground/70 [&>*:first-child]:mt-0 [&>*:last-child]:mb-0">
            <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeSanitize]}>
              {message.content}
            </ReactMarkdown>
          </div>
        <div className="mt-2 flex items-center gap-2 opacity-0 transition-opacity group-hover/message:opacity-100">
          {!isTemp && (
            <>
              <Button
                variant="ghost"
                size="icon-xs"
                className="text-muted-foreground hover:text-foreground"
                onClick={handleCopy}
                aria-label={copied ? "Copié" : "Copier la réponse"}
              >
                {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
              </Button>
              {onFeedback && (
                <>
                  <Button
                    variant="ghost"
                    size="icon-xs"
                    className={cn(
                      "text-muted-foreground hover:text-foreground",
                      message.feedback === "up" && "text-primary hover:text-primary",
                    )}
                    onClick={() => handleFeedback("up")}
                    aria-label="Bonne réponse"
                  >
                    <ThumbsUp className="size-3.5" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon-xs"
                    className={cn(
                      "text-muted-foreground hover:text-foreground",
                      message.feedback === "down" && "text-destructive hover:text-destructive",
                    )}
                    onClick={() => handleFeedback("down")}
                    aria-label="Mauvaise réponse"
                  >
                    <ThumbsDown className="size-3.5" />
                  </Button>
                </>
              )}
            </>
          )}
          <span className="text-muted-foreground text-xs">
            {formatTime(message.created_at)}
          </span>
        </div>
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
