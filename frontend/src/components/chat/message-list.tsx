"use client";

import { useEffect, useRef, useCallback } from "react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { MessageBubble } from "./message-bubble";
import { StreamingBubble } from "./streaming-bubble";
import type { Message, MessageSource } from "@/types/api";

interface MessageListProps {
  messages: Message[];
  isStreaming: boolean;
  streamingStatus?: string | null;
  streamingContent?: string;
  streamingSources?: MessageSource[] | null;
  onFeedback?: (messageId: string, feedback: "up" | "down" | null) => void;
}

export function MessageList({
  messages,
  isStreaming,
  streamingStatus,
  streamingContent,
  streamingSources,
  onFeedback,
}: MessageListProps) {
  const viewportRef = useRef<HTMLDivElement>(null);
  const isNearBottomRef = useRef(true);

  const scrollToBottom = useCallback(
    (behavior: ScrollBehavior = "smooth") => {
      const viewport = viewportRef.current;
      if (!viewport) return;
      viewport.scrollTo({ top: viewport.scrollHeight, behavior });
    },
    [],
  );

  // Track whether the user is near the bottom of the scroll area
  useEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport) return;

    const handleScroll = () => {
      const threshold = 100;
      const { scrollTop, scrollHeight, clientHeight } = viewport;
      isNearBottomRef.current =
        scrollHeight - scrollTop - clientHeight < threshold;
    };

    viewport.addEventListener("scroll", handleScroll, { passive: true });
    return () => viewport.removeEventListener("scroll", handleScroll);
  }, []);

  // Auto-scroll when new messages are added (only if user is near bottom)
  useEffect(() => {
    if (isNearBottomRef.current) {
      scrollToBottom();
    }
  }, [messages, scrollToBottom]);

  // Follow streaming output (only if user is near bottom)
  useEffect(() => {
    if (isStreaming && isNearBottomRef.current) {
      scrollToBottom("instant");
    }
  }, [streamingContent, isStreaming, scrollToBottom]);

  const showStatus = isStreaming && !streamingContent && !!streamingStatus;
  const showThinking = isStreaming && !streamingContent && !streamingStatus;
  const showStreaming = isStreaming && !!streamingContent;

  return (
    <ScrollArea className="min-h-0 flex-1" viewportRef={viewportRef}>
      <div className="mx-auto max-w-4xl space-y-6 px-2 py-4 sm:px-6">
        {messages.map((message) => (
          <MessageBubble key={message.id} message={message} onFeedback={onFeedback} />
        ))}
        {showThinking && <StatusIndicator />}
        {showStatus && <StatusIndicator step={streamingStatus} />}
        {showStreaming && (
          <StreamingBubble
            content={streamingContent || ""}
            sources={streamingSources}
          />
        )}
      </div>
    </ScrollArea>
  );
}

function StatusIndicator({ step }: { step?: string }) {
  return (
    <div className="flex items-start gap-3">
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary/10">
        <svg className="h-4 w-4 text-primary" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2z" strokeOpacity="0.3" />
          <path d="M12 2a10 10 0 0 1 10 10" strokeLinecap="round">
            <animateTransform attributeName="transform" type="rotate" from="0 12 12" to="360 12 12" dur="1s" repeatCount="indefinite" />
          </path>
        </svg>
      </div>
      <div className="flex items-center pt-1.5">
        <span className="text-sm text-muted-foreground animate-pulse">
          {step || "Réflexion en cours..."}
        </span>
      </div>
    </div>
  );
}
