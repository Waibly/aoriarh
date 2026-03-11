"use client";

import { useEffect, useRef, useCallback } from "react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { MessageBubble } from "./message-bubble";
import { StreamingBubble } from "./streaming-bubble";
import { ThinkingIndicator } from "./thinking-indicator";
import type { Message, MessageSource } from "@/types/api";

interface MessageListProps {
  messages: Message[];
  isStreaming: boolean;
  streamingContent?: string;
  streamingSources?: MessageSource[] | null;
  onFeedback?: (messageId: string, feedback: "up" | "down" | null) => void;
}

export function MessageList({
  messages,
  isStreaming,
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

  const showThinking = isStreaming && !streamingContent;
  const showStreaming = isStreaming && !!streamingContent;

  return (
    <ScrollArea className="min-h-0 flex-1" viewportRef={viewportRef}>
      <div className="mx-auto max-w-4xl space-y-6 px-2 py-4 sm:px-6">
        {messages.map((message) => (
          <MessageBubble key={message.id} message={message} onFeedback={onFeedback} />
        ))}
        {showThinking && <ThinkingIndicator />}
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
