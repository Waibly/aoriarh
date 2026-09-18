"use client";

import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { WelcomeScreen } from "@/components/chat/welcome-screen";
import { Conversation } from "@/components/chat/conversation";
import { DocumentLibrary } from "@/components/chat/document-library";
import { createConversation, uploadChatDocument, type ChatDocumentReference } from "@/lib/chat-api";
import { prepareLibraryDocument } from "@/lib/chat-document-library";
import type { Conversation as ConversationData } from "@/types/api";

export function NewConversation({ organisationId, token, onSaved }: {
  organisationId?: string;
  token?: string;
  onSaved: (id: string) => void;
}) {
  const [draft, setDraft] = useState<ConversationData | null>(null);
  const creation = useRef<Promise<ConversationData> | null>(null);
  const [attachments, setAttachments] = useState<ChatDocumentReference[]>([]);
  const [busy, setBusy] = useState(false);
  const working = useRef(false);
  const mounted = useRef(true);
  const [libraryOpen, setLibraryOpen] = useState(false);
  const [firstMessage, setFirstMessage] = useState<string | null>(null);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);

  async function ensureConversation() {
    if (!token || !organisationId) throw new Error("Sélectionnez une organisation et connectez-vous");
    if (!creation.current) {
      creation.current = createConversation(organisationId, token).catch((error) => {
        creation.current = null;
        throw error;
      });
    }
    const conversation = await creation.current;
    if (!mounted.current) throw new Error("La conversation a changé");
    setDraft(conversation);
    return conversation;
  }

  async function run(operation: () => Promise<void>, report = true) {
    if (working.current) return false;
    working.current = true;
    setBusy(true);
    try {
      await operation();
      return true;
    } catch (error) {
      if (!report) throw error;
      if (mounted.current) toast.error(error instanceof Error ? error.message : "Opération impossible");
      return false;
    } finally {
      working.current = false;
      if (mounted.current) setBusy(false);
    }
  }

  function checkAttachments(conversation: ConversationData) {
    if (!conversation.document_attachments_enabled) throw new Error("Les pièces jointes ne sont pas activées");
    if (attachments.length >= 3) throw new Error("Trois pièces actives maximum");
  }

  if (firstMessage && draft) return <Conversation key={draft.id} conversationId={draft.id}
    initialQuery={firstMessage} initialAttachments={attachments}
    onConversationSaved={() => onSaved(draft.id)} />;

  const disabled = busy || !organisationId || !token;
  return <><WelcomeScreen disabled={disabled} attachments={attachments}
    onBrowse={draft?.document_attachments_enabled === false ? undefined : () => void run(async () => {
      const conversation = await ensureConversation();
      checkAttachments(conversation);
      setLibraryOpen(true);
    })}
    onRemove={(id) => setAttachments((current) => current.filter((d) => d.document_id !== id))}
    onSend={(content) => run(async () => { await ensureConversation(); setFirstMessage(content); })}
    onAttach={draft?.document_attachments_enabled === false ? undefined : async (file) => {
      await run(async () => {
        if (file.size > 2 * 1024 * 1024) throw new Error("Maximum 2 Mo par pièce jointe");
        const conversation = await ensureConversation();
        checkAttachments(conversation);
        const reference = await uploadChatDocument(conversation.id, file, token!);
        if (mounted.current) setAttachments((current) => [...current, reference]);
      });
    }}
  />
    {draft && token && <DocumentLibrary conversationId={draft.id} token={token}
      open={libraryOpen} onOpenChange={setLibraryOpen}
      selectedIds={attachments.map((d) => d.document_id)} disabled={disabled}
      onSelect={async (document) => {
        await run(async () => {
          checkAttachments(draft);
          const reference = await prepareLibraryDocument(draft.id, token, document);
          if (mounted.current) setAttachments((current) => current.some((d) => d.document_id === reference.document_id)
            ? current : [...current, reference]);
        }, false);
      }} />}
  </>;
}
