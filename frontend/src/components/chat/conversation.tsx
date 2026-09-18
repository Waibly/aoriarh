"use client";

import dynamic from "next/dynamic";
import { useState, useEffect, useCallback, useRef } from "react";
import { useSession } from "next-auth/react";
import { toast } from "sonner";
import { ChatInput } from "@/components/chat/chat-input";
import { SearchDetailsPanel } from "@/components/chat/search-details";
import { DocumentLibrary } from "@/components/chat/document-library";
import { prepareLibraryDocument } from "@/lib/chat-document-library";

const MessageList = dynamic(() =>
  import("@/components/chat/message-list").then((mod) => ({ default: mod.MessageList })),
  { ssr: false },
);
import { getConversation, streamMessage, updateMessageFeedback, uploadChatDocument, type ChatDocumentReference } from "@/lib/chat-api";
import type { Message, MessageSource, SearchDetails } from "@/types/api";

export function Conversation({ conversationId, initialQuery = null, initialAttachments,
  onInitialQueryStarted, onConversationSaved }: {
  conversationId: string;
  initialQuery?: string | null;
  initialAttachments?: ChatDocumentReference[];
  onInitialQueryStarted?: () => void;
  onConversationSaved?: () => void;
}) {
  const { data: session } = useSession();
  const token = session?.access_token;

  const [messages, setMessages] = useState<Message[]>([]);
  const [attachments, setAttachments] = useState<ChatDocumentReference[] | undefined>(initialAttachments);
  const [isUploading, setIsUploading] = useState(false);
  const [attachmentsEnabled, setAttachmentsEnabled] = useState(false);
  const [searchDetails, setSearchDetails] = useState<SearchDetails | null>(null);
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamingStatus, setStreamingStatus] = useState<string | null>(null);
  const [streamingContent, setStreamingContent] = useState("");
  const [streamingSources, setStreamingSources] = useState<
    MessageSource[] | null
  >(null);
  const initialQueryProcessed = useRef(false);
  const abortControllerRef = useRef<AbortController | null>(null);
  const activeConversationRef = useRef(conversationId);
  activeConversationRef.current = conversationId;

  // Load existing conversation messages (skip when there's an initial query
  // since the conversation was just created and is empty, and skip during streaming)
  const isStreamingRef = useRef(false);
  isStreamingRef.current = isStreaming;

  useEffect(() => {
    if (!token || conversationId === "new") return;

    let cancelled = false;
    if (!initialQuery) setAttachments(undefined);
    setAttachmentsEnabled(false);
    setIsUploading(false);
    (async () => {
      try {
        const data = await getConversation(conversationId, token);
        if (!cancelled) setAttachmentsEnabled(data.document_attachments_enabled === true);
        if (!cancelled && !isStreamingRef.current && !initialQuery) {
          setMessages(data.messages);
          const latest = [...data.messages].reverse().find((m) => m.role === "user" && m.document_references != null);
          setAttachments(latest?.document_references ?? []);
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
        document_references: attachments,
        sources: null,
        feedback: null,
        feedback_comment: null,
        created_at: new Date().toISOString(),
      };

      setMessages((prev) => [...prev, tempUserMessage]);
      setIsStreaming(true);
      setStreamingContent("");
      setStreamingSources(null);
      setSearchDetails(null);

      // Abort any previous in-progress stream
      abortControllerRef.current?.abort();
      const abortController = new AbortController();
      abortControllerRef.current = abortController;

      // Local accumulators (synchronous — not subject to React batching)
      let accumulatedContent = "";
      let accumulatedSources: MessageSource[] | null = null;
      let accumulatedDetails: SearchDetails | undefined;

      try {
        await streamMessage(
          conversationId,
          content,
          token,
          {
            onStatus: (step) => {
              setStreamingStatus(step);
            },
            onSearchDetails: (details) => {
              accumulatedDetails = details;
              setSearchDetails(details);
            },
            onSources: (sources) => {
              accumulatedSources = sources;
              setStreamingSources(sources);
            },
            onDelta: (delta) => {
              setStreamingStatus(null); // Clear status when content starts
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
                    search_details: accumulatedDetails,
                    feedback: null,
                    feedback_comment: null,
                    fiche_eligible: ids.fiche_eligible,
                    created_at: new Date().toISOString(),
                  },
                ];
              });

              setStreamingContent("");
              setSearchDetails(null);
              setStreamingSources(null);
              setIsStreaming(false);

              // Notify sidebar to refresh conversation list (title updated)
              window.dispatchEvent(new Event("conversation-updated"));
              onConversationSaved?.();
            },
            onError: (errorMsg) => {
              // If we already have partial content, keep it as a message
              if (accumulatedContent || accumulatedDetails?.raw_response || accumulatedDetails?.router_raw_response) {
                setSearchDetails(null);
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
                      search_details: accumulatedDetails,
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
          attachments,
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
    [conversationId, token, attachments, onConversationSaved],
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
      onInitialQueryStarted?.();
    }
  }, [initialQuery, token, handleSend, conversationId, onInitialQueryStarted]);

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl bg-white p-4 dark:bg-card">
      <MessageList
        messages={messages}
        isStreaming={isStreaming}
        streamingStatus={streamingStatus}
        streamingContent={streamingContent}
        streamingSources={streamingSources}
        onFeedback={handleFeedback}
      />
      <div className="max-h-64 overflow-auto"><SearchDetailsPanel details={searchDetails} /></div>
      {attachmentsEnabled && token && <DocumentLibrary key={conversationId}
        conversationId={conversationId} token={token}
        selectedIds={(attachments ?? []).map((doc) => doc.document_id)}
        disabled={isStreaming || isUploading}
        onSelect={async (document) => {
          if (isStreaming || isUploading || (attachments?.length ?? 0) >= 3) return;
          setIsUploading(true);
          try {
            const ref = await prepareLibraryDocument(conversationId, token, document);
            if (activeConversationRef.current === conversationId) {
              setAttachments((current) => current?.some((d) => d.document_id === ref.document_id)
                ? current : [...(current ?? []), ref]);
            }
          } finally {
            if (activeConversationRef.current === conversationId) setIsUploading(false);
          }
        }} />}
      <ChatInput
        onSend={handleSend}
        disabled={isStreaming || isUploading}
        attachments={attachments}
        onRemove={(id) => setAttachments((current) => (current ?? []).filter((doc) => doc.document_id !== id))}
        onAttach={attachmentsEnabled ? async (file) => {
          if (!token || isUploading || (attachments?.length ?? 0) >= 3) return;
          if (file.size > 2 * 1024 * 1024) { toast.error("Maximum 2 Mo par pièce jointe"); return; }
          setIsUploading(true);
          try {
            const doc = await uploadChatDocument(conversationId, file, token);
            setAttachments((current) => [...(current ?? []), doc]);
          } catch (error) {
            toast.error(error instanceof Error ? error.message : "Échec du dépôt");
          } finally { setIsUploading(false); }
        } : undefined}
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
