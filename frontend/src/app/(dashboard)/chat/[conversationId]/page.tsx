"use client";

import dynamic from "next/dynamic";
import { useParams, useSearchParams } from "next/navigation";
import { useState, useEffect, useCallback, useRef } from "react";
import { useSession } from "next-auth/react";
import { toast } from "sonner";
import { ChatInput } from "@/components/chat/chat-input";

const MessageList = dynamic(() =>
  import("@/components/chat/message-list").then((mod) => ({ default: mod.MessageList })),
  { ssr: false },
);
import { getConversation, streamMessage, updateMessageFeedback } from "@/lib/chat-api";
import type { Message, MessageSource } from "@/types/api";

export default function ConversationPage() {
  const params = useParams<{ conversationId: string }>();
  const searchParams = useSearchParams();
  const { data: session } = useSession();
  const conversationId = params.conversationId;
  const initialQuery = searchParams.get("q");
  const token = session?.access_token;

  const [messages, setMessages] = useState<Message[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamingContent, setStreamingContent] = useState("");
  const [streamingSources, setStreamingSources] = useState<
    MessageSource[] | null
  >(null);
  const initialQueryProcessed = useRef(false);
  const abortControllerRef = useRef<AbortController | null>(null);

  // Load existing conversation messages (skip when there's an initial query
  // since the conversation was just created and is empty, and skip during streaming)
  const isStreamingRef = useRef(false);
  isStreamingRef.current = isStreaming;

  useEffect(() => {
    if (!token || conversationId === "new" || initialQuery || isStreamingRef.current) return;

    let cancelled = false;
    (async () => {
      try {
        const data = await getConversation(conversationId, token);
        if (!cancelled && !isStreamingRef.current) {
          setMessages(data.messages);
        }
      } catch {
        // conversation not found or access denied
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [conversationId, token, initialQuery]);

  const handleSend = useCallback(
    async (content: string) => {
      if (!token || conversationId === "new") return;

      const tempUserMessage: Message = {
        id: `temp-${Date.now()}`,
        conversation_id: conversationId,
        role: "user",
        content,
        sources: null,
        feedback: null,
        feedback_comment: null,
        created_at: new Date().toISOString(),
      };

      setMessages((prev) => [...prev, tempUserMessage]);
      setIsStreaming(true);
      setStreamingContent("");
      setStreamingSources(null);

      // Abort any previous in-progress stream
      abortControllerRef.current?.abort();
      const abortController = new AbortController();
      abortControllerRef.current = abortController;

      // Local accumulators (synchronous — not subject to React batching)
      let accumulatedContent = "";
      let accumulatedSources: MessageSource[] | null = null;

      try {
        await streamMessage(
          conversationId,
          content,
          token,
          {
            onSources: (sources) => {
              accumulatedSources = sources;
              setStreamingSources(sources);
            },
            onDelta: (delta) => {
              accumulatedContent += delta;
              setStreamingContent((prev) => prev + delta);
            },
            onDone: (ids) => {
              setMessages((prev) => {
                const filtered = prev.filter(
                  (m) => m.id !== tempUserMessage.id,
                );
                return [
                  ...filtered,
                  { ...tempUserMessage, id: ids.message_id },
                  {
                    id: ids.answer_id,
                    conversation_id: conversationId,
                    role: "assistant" as const,
                    content: accumulatedContent,
                    sources: accumulatedSources,
                    feedback: null,
                    feedback_comment: null,
                    created_at: new Date().toISOString(),
                  },
                ];
              });

              setStreamingContent("");
              setStreamingSources(null);
              setIsStreaming(false);

              // Notify sidebar to refresh conversation list (title updated)
              window.dispatchEvent(new Event("conversation-updated"));
            },
            onError: (errorMsg) => {
              // If we already have partial content, keep it as a message
              if (accumulatedContent) {
                setMessages((prev) => {
                  const filtered = prev.filter(
                    (m) => m.id !== tempUserMessage.id,
                  );
                  return [
                    ...filtered,
                    tempUserMessage,
                    {
                      id: `partial-${Date.now()}`,
                      conversation_id: conversationId,
                      role: "assistant" as const,
                      content: accumulatedContent,
                      sources: accumulatedSources,
                      feedback: null,
                      feedback_comment: null,
                      created_at: new Date().toISOString(),
                    },
                  ];
                });
              } else {
                // No content at all — remove everything
                setMessages((prev) =>
                  prev.filter((m) => m.id !== tempUserMessage.id),
                );
              }
              setStreamingContent("");
              setStreamingSources(null);
              setIsStreaming(false);
              toast.error(errorMsg);
            },
          },
          abortController.signal,
        );
      } catch {
        if (!abortController.signal.aborted) {
          setMessages((prev) =>
            prev.filter((m) => m.id !== tempUserMessage.id),
          );
          setStreamingContent("");
          setStreamingSources(null);
          setIsStreaming(false);
          toast.error("Une erreur est survenue. Veuillez réessayer.");
        }
      }
    },
    [conversationId, token],
  );

  const handleFeedback = useCallback(
    async (messageId: string, feedback: "up" | "down" | null, comment?: string | null) => {
      if (!token) return;
      setMessages((prev) =>
        prev.map((m) => (m.id === messageId ? { ...m, feedback, feedback_comment: comment ?? null } : m)),
      );
      try {
        await updateMessageFeedback(messageId, feedback, token, comment);
      } catch {
        setMessages((prev) =>
          prev.map((m) =>
            m.id === messageId ? { ...m, feedback: null, feedback_comment: null } : m,
          ),
        );
        toast.error("Impossible d'enregistrer votre retour.");
      }
    },
    [token],
  );

  // Auto-send initial query from welcome screen
  useEffect(() => {
    if (initialQuery && token && !initialQueryProcessed.current) {
      initialQueryProcessed.current = true;
      handleSend(initialQuery);
      // Clean URL immediately
      window.history.replaceState({}, "", `/chat/${conversationId}`);
    }
  }, [initialQuery, token, handleSend, conversationId]);

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl bg-white p-4 dark:bg-card">
      <MessageList
        messages={messages}
        isStreaming={isStreaming}
        streamingContent={streamingContent}
        streamingSources={streamingSources}
        onFeedback={handleFeedback}
      />
      <ChatInput
        onSend={handleSend}
        disabled={isStreaming}
        onStop={
          isStreaming
            ? () => {
                abortControllerRef.current?.abort();
                setIsStreaming(false);
                setStreamingContent("");
                setStreamingSources(null);
              }
            : undefined
        }
      />
    </div>
  );
}
