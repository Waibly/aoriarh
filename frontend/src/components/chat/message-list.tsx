"use client";

import { useEffect, useRef, useCallback, useState } from "react";
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

  const scrollToBottom = useCallback((behavior: ScrollBehavior = "smooth") => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    viewport.scrollTo({ top: viewport.scrollHeight, behavior });
  }, []);

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

  // Scroll to the freshly sent message (only if user is near bottom).
  // Deliberately NOT following the streaming output: once the answer starts
  // generating, the view stays put so the user can read at their own pace.
  useEffect(() => {
    if (isNearBottomRef.current) {
      scrollToBottom();
    }
  }, [messages, scrollToBottom]);

  const showStatus = isStreaming && !streamingContent && !!streamingStatus;
  const showThinking = isStreaming && !streamingContent && !streamingStatus;
  const showStreaming = isStreaming && !!streamingContent;

  return (
    <ScrollArea className="min-h-0 min-w-0 flex-1" viewportRef={viewportRef}>
      <div className="mx-auto w-full max-w-4xl min-w-0 space-y-6 px-2 py-4 sm:px-6">
        {messages.map((message) => (
          <div
            key={message.id}
            id={`message-${message.id}`}
            className="scroll-mt-4"
          >
            <MessageBubble message={message} onFeedback={onFeedback} />
          </div>
        ))}
        {(showThinking || showStatus) && (
          <StatusIndicator step={streamingStatus ?? undefined} />
        )}
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
  const [elapsed, setElapsed] = useState(0);
  const [stepElapsed, setStepElapsed] = useState(0);
  useEffect(() => {
    const started = Date.now();
    const timer = window.setInterval(
      () => setElapsed(Math.floor((Date.now() - started) / 1000)),
      1000
    );
    return () => window.clearInterval(timer);
  }, []);
  useEffect(() => {
    setStepElapsed(0);
    const started = Date.now();
    const timer = window.setInterval(
      () => setStepElapsed(Math.floor((Date.now() - started) / 1000)),
      1000
    );
    return () => window.clearInterval(timer);
  }, [step]);
  return (
    <div className="flex items-start gap-3">
      <div className="bg-primary/10 flex h-8 w-8 shrink-0 items-center justify-center rounded-full">
        <svg
          className="text-primary h-4 w-4"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
        >
          <path
            d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2z"
            strokeOpacity="0.3"
          />
          <path d="M12 2a10 10 0 0 1 10 10" strokeLinecap="round">
            <animateTransform
              attributeName="transform"
              type="rotate"
              from="0 12 12"
              to="360 12 12"
              dur="1s"
              repeatCount="indefinite"
            />
          </path>
        </svg>
      </div>
      <div className="text-muted-foreground min-w-0 pt-1.5 text-sm">
        <div className="flex flex-wrap items-center gap-x-2">
          <span role="status">
            {step || "Prise en compte de votre question…"}
          </span>
          <span className="text-xs tabular-nums" aria-label="Temps écoulé">
            {elapsed} s
          </span>
        </div>
        {stepElapsed >= 20 && (
          <p className="mt-1 text-xs">
            Cette étape est toujours en cours. Vous pouvez patienter sans
            renvoyer votre question.
          </p>
        )}
      </div>
    </div>
  );
}
