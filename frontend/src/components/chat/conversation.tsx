"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useOrg } from "@/lib/org-context";
import { getDossier, type DossierDetail } from "@/lib/dossiers-api";
import { DossierPanel } from "@/components/dossiers/dossier-panel";
import { CreateDossierDialog } from "@/components/dossiers/create-dossier-dialog";
import dynamic from "next/dynamic";
import { useState, useEffect, useCallback, useRef } from "react";
import { useSession } from "next-auth/react";
import { toast } from "sonner";
import { FolderOpen } from "lucide-react";
import { ChatInput } from "@/components/chat/chat-input";
import { CaseFilePanel } from "@/components/chat/case-file-panel";
import { SearchDetailsPanel } from "@/components/chat/search-details";
import { DocumentLibrary } from "@/components/chat/document-library";
import { Button } from "@/components/ui/button";
import { prepareLibraryDocument } from "@/lib/chat-document-library";
import { attachmentBlocker } from "@/lib/chat-attachments";
import { useAttachmentReadiness } from "@/hooks/use-attachment-readiness";

const MessageList = dynamic(
  () =>
    import("@/components/chat/message-list").then((mod) => ({
      default: mod.MessageList,
    })),
  { ssr: false }
);
import {
  getConversation,
  streamMessage,
  updateMessageFeedback,
  uploadChatDocument,
  type ChatDocumentReference,
} from "@/lib/chat-api";
import type { Message, MessageSource, SearchDetails } from "@/types/api";

export function Conversation({
  conversationId,
  initialQuery = null,
  initialAttachments,
  onInitialQueryStarted,
  onConversationSaved,
}: {
  conversationId: string;
  initialQuery?: string | null;
  initialAttachments?: ChatDocumentReference[];
  onInitialQueryStarted?: () => void;
  onConversationSaved?: () => void;
}) {
  const { data: session } = useSession();
  const token = session?.access_token;
  const router = useRouter();
  const { currentOrg } = useOrg();
  const [dossier, setDossier] = useState<DossierDetail | null>(null);
  const [conversationTitle, setConversationTitle] = useState("");
  const [conversationOrg, setConversationOrg] = useState<string | null>(null);
  const [createDossier, setCreateDossier] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [sendError, setSendError] = useState("");
  const [attachmentScope, setAttachmentScope] = useState<
    "dossier" | "conversation"
  >("dossier");
  useEffect(() => {
    if (conversationOrg && currentOrg && conversationOrg !== currentOrg.id) {
      abortControllerRef.current?.abort();
      setMessages([]);
      setAttachments([]);
      setDossier(null);
      router.replace("/chat");
    }
  }, [conversationOrg, currentOrg?.id, router]);

  const [messages, setMessages] = useState<Message[]>([]);
  const [attachments, setAttachments] = useState<ChatDocumentReference[]>(
    initialAttachments ?? []
  );
  const [isUploading, setIsUploading] = useState(false);
  const [attachmentsEnabled, setAttachmentsEnabled] = useState(false);
  const [libraryOpen, setLibraryOpen] = useState(false);
  const [caseFileOpen, setCaseFileOpen] = useState(false);
  const [caseFileRefreshVersion, setCaseFileRefreshVersion] = useState(0);
  const [searchDetails, setSearchDetails] = useState<SearchDetails | null>(
    null
  );
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamingStatus, setStreamingStatus] = useState<string | null>(null);
  const [streamingContent, setStreamingContent] = useState("");
  const [streamingSources, setStreamingSources] = useState<
    MessageSource[] | null
  >(null);
  const initialQueryProcessed = useRef(false);
  const sentInConversation = useRef<string | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const activeConversationRef = useRef(conversationId);
  activeConversationRef.current = conversationId;
  useAttachmentReadiness(conversationId, token, attachments, setAttachments);

  // Load existing conversation messages (skip when there's an initial query
  // since the conversation was just created and is empty, and skip during streaming)
  const isStreamingRef = useRef(false);
  isStreamingRef.current = isStreaming;

  useEffect(() => {
    if (!token || conversationId === "new") return;

    let cancelled = false;
    if (!initialQuery) setAttachments([]);
    setAttachmentsEnabled(false);
    setIsUploading(false);
    (async () => {
      try {
        const data = await getConversation(conversationId, token);
        let loadedDossier: DossierDetail | null = null;
        if (!cancelled) {
          setConversationTitle(data.title || "Nouvelle conversation");
          setConversationOrg(data.organisation_id);
          if (data.dossier_id) {
            loadedDossier = await getDossier(data.dossier_id, token);
            if (!cancelled) setDossier(loadedDossier);
          } else setDossier(null);
        }
        if (!cancelled)
          setAttachmentsEnabled(data.document_attachments_enabled === true);
        if (
          !cancelled &&
          !isStreamingRef.current &&
          !initialQuery &&
          sentInConversation.current !== conversationId
        ) {
          setMessages(data.messages);
          const latest = [...data.messages]
            .reverse()
            .find((m) => m.role === "user" && m.document_references != null);
          const commonIds = new Set(
            loadedDossier?.documents.map((d) => d.document_id) ?? []
          );
          if (!cancelled)
            setAttachments(
              (latest?.document_references ?? []).filter(
                (r) => r.scope !== "dossier" && !commonIds.has(r.document_id)
              )
            );
        }
      } catch (error) {
        if (!cancelled)
          setLoadError(
            error instanceof Error
              ? error.message
              : "Conversation non accessible"
          );
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [conversationId, token, initialQuery]);

  useEffect(() => {
    if (messages.length && window.location.hash.startsWith("#message-")) {
      document
        .getElementById(window.location.hash.slice(1))
        ?.scrollIntoView({ block: "center" });
    }
  }, [messages]);

  const handleSend = useCallback(
    async (content: string) => {
      if (!token || conversationId === "new") return;
      const blocked = attachmentBlocker(attachments ?? []);
      if (blocked) {
        toast.error(blocked);
        return false;
      }

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

      sentInConversation.current = conversationId;
      setMessages((prev) => [...prev, tempUserMessage]);
      setIsStreaming(true);
      setStreamingContent("");
      setStreamingSources(null);
      setSearchDetails(null);
      setSendError("");

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
            onCaseFileUpdated: () => {
              setCaseFileRefreshVersion((version) => version + 1);
            },
            onDone: (ids) => {
              setMessages((prev) => {
                const filtered = prev.filter(
                  (m) => m.id !== tempUserMessage.id
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
            onWarning: (message) => toast.warning(message),
            onError: (errorMsg) => {
              // If we already have partial content, keep it as a message
              if (
                accumulatedContent ||
                accumulatedDetails?.raw_response ||
                accumulatedDetails?.router_raw_response
              ) {
                setSearchDetails(null);
                setMessages((prev) => {
                  const filtered = prev.filter(
                    (m) => m.id !== tempUserMessage.id
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
              }
              // The user's question remains visible even when the provider fails.
              setStreamingContent("");
              setStreamingSources(null);
              setIsStreaming(false);
              setSendError(errorMsg);
            },
          },
          abortController.signal,
          attachments
        );
      } catch {
        if (!abortController.signal.aborted) {
          if (accumulatedContent) {
            setMessages((prev) => [
              ...prev,
              {
                id: `partial-${Date.now()}`,
                conversation_id: conversationId,
                role: "assistant",
                content: accumulatedContent,
                sources: accumulatedSources,
                search_details: accumulatedDetails,
                feedback: null,
                feedback_comment: null,
                created_at: new Date().toISOString(),
              },
            ]);
          }
          setStreamingContent("");
          setStreamingSources(null);
          setIsStreaming(false);
          setSendError(
            "La réponse a été interrompue. Votre question et le texte reçu restent affichés."
          );
        }
      }
    },
    [conversationId, token, attachments, onConversationSaved]
  );

  const handleFeedback = useCallback(
    async (
      messageId: string,
      feedback: "up" | "down" | null,
      comment?: string | null
    ) => {
      if (!token) return;
      setMessages((prev) =>
        prev.map((m) =>
          m.id === messageId
            ? { ...m, feedback, feedback_comment: comment ?? null }
            : m
        )
      );
      try {
        await updateMessageFeedback(messageId, feedback, token, comment);
      } catch {
        setMessages((prev) =>
          prev.map((m) =>
            m.id === messageId
              ? { ...m, feedback: null, feedback_comment: null }
              : m
          )
        );
        toast.error("Impossible d'enregistrer votre retour.");
      }
    },
    [token]
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
    <div className="dark:bg-card flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl bg-white p-4">
      {token && conversationId !== "new" && (
        <div className="flex flex-wrap items-center justify-between gap-2 border-b pb-3">
          {dossier ? (
            <Link
              href={`/dossiers/${dossier.id}`}
              className="text-primary min-w-0 text-sm font-medium"
            >
              {dossier.name} / {conversationTitle}
            </Link>
          ) : (
            <Button
              variant="ghost"
              size="sm"
              disabled={isStreaming}
              onClick={() => setCreateDossier(true)}
            >
              Créer un dossier à partir de cet échange
            </Button>
          )}
          {dossier && (
            <Button size="sm" variant="ghost" asChild>
              <Link href={`/dossiers/${dossier.id}`}>
                Nouvelle conversation
              </Link>
            </Button>
          )}
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => setCaseFileOpen(true)}
          >
            <FolderOpen />
            {dossier ? "Voir le dossier" : "Contexte de la conversation"}
          </Button>
        </div>
      )}
      {loadError && (
        <p role="alert" className="text-destructive p-3">
          {loadError}
        </p>
      )}
      {dossier?.archived_at && (
        <p className="text-muted-foreground p-3 text-sm">
          Dossier archivé : réactivez-le pour poursuivre cet échange.
        </p>
      )}
      <MessageList
        messages={messages}
        isStreaming={isStreaming}
        streamingStatus={streamingStatus}
        streamingContent={streamingContent}
        streamingSources={streamingSources}
        onFeedback={handleFeedback}
      />
      {sendError && (
        <p
          role="alert"
          className="border-destructive/20 bg-destructive/5 text-destructive mx-auto mb-3 w-full max-w-3xl rounded-lg border px-4 py-3 text-sm"
        >
          {sendError}
        </p>
      )}
      <div className="max-h-64 overflow-auto">
        <SearchDetailsPanel details={searchDetails} />
      </div>
      {attachmentsEnabled && token && (
        <DocumentLibrary
          key={conversationId}
          open={libraryOpen}
          onOpenChange={setLibraryOpen}
          conversationId={conversationId}
          token={token}
          selectedIds={(attachments ?? []).map((doc) => doc.document_id)}
          disabled={
            isStreaming || isUploading || !!dossier?.archived_at || !!loadError
          }
          onSelect={async (document) => {
            if (isStreaming || isUploading || (attachments?.length ?? 0) >= 3)
              return;
            setIsUploading(true);
            try {
              const ref = await prepareLibraryDocument(
                conversationId,
                token,
                document
              );
              if (activeConversationRef.current === conversationId) {
                setAttachments((current) =>
                  current.some((d) => d.document_id === ref.document_id)
                    ? current
                    : [...current, ref]
                );
              }
            } finally {
              if (activeConversationRef.current === conversationId)
                setIsUploading(false);
            }
          }}
        />
      )}
      <ChatInput
        draftKey={conversationId}
        attachmentScope={dossier ? attachmentScope : "entreprise"}
        onAttachmentScopeChange={
          dossier && !dossier.archived_at ? setAttachmentScope : undefined
        }
        onBrowse={attachmentsEnabled ? () => setLibraryOpen(true) : undefined}
        onSend={handleSend}
        disabled={
          isStreaming || isUploading || !!dossier?.archived_at || !!loadError
        }
        attachments={attachments}
        onRemove={(id) =>
          setAttachments((current) =>
            (current ?? []).filter((doc) => doc.document_id !== id)
          )
        }
        onAttach={
          attachmentsEnabled
            ? async (file) => {
                if (!token || isUploading || (attachments?.length ?? 0) >= 3)
                  return;
                if (file.size > 2 * 1024 * 1024) {
                  toast.error("Maximum 2 Mo par pièce jointe");
                  return;
                }
                setIsUploading(true);
                try {
                  const doc = await uploadChatDocument(
                    conversationId,
                    file,
                    token,
                    dossier ? attachmentScope : undefined
                  );
                  setAttachments((current) => [...(current ?? []), doc]);
                } catch (error) {
                  toast.error(
                    error instanceof Error ? error.message : "Échec du dépôt"
                  );
                } finally {
                  setIsUploading(false);
                }
              }
            : undefined
        }
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
      {token && conversationOrg && !dossier && (
        <CreateDossierDialog
          open={createDossier}
          onOpenChange={setCreateDossier}
          organisationId={conversationOrg}
          organisationName={currentOrg?.name}
          token={token}
          conversationId={conversationId}
          onCreated={(d) => {
            setDossier(d);
            setCaseFileOpen(false);
          }}
        />
      )}
      {token && dossier && (
        <DossierPanel
          id={dossier.id}
          token={token}
          open={caseFileOpen}
          onOpenChange={setCaseFileOpen}
          refreshVersion={caseFileRefreshVersion}
        />
      )}
      {token && !dossier && conversationId !== "new" && (
        <CaseFilePanel
          key={`case-file-${conversationId}`}
          conversationId={conversationId}
          token={token}
          open={caseFileOpen}
          onOpenChange={setCaseFileOpen}
          refreshVersion={caseFileRefreshVersion}
          onOpenMessage={(messageId) => {
            setCaseFileOpen(false);
            window.setTimeout(() => {
              document
                .getElementById(`message-${messageId}`)
                ?.scrollIntoView({ behavior: "smooth", block: "center" });
            }, 250);
          }}
        />
      )}
    </div>
  );
}
