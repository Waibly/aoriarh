"use client";

import { useEffect } from "react";
import { effectiveAttachments } from "@/lib/chat-attachments";
import { getChatDocumentReadiness, type ChatDocumentReference } from "@/lib/chat-api";

export function useAttachmentReadiness(
  conversationId: string | undefined,
  token: string | undefined,
  attachments: ChatDocumentReference[],
  setAttachments: React.Dispatch<React.SetStateAction<ChatDocumentReference[]>>,
) {
  useEffect(() => {
    if (!conversationId || !token || !attachments.length) return;
    const pendingIds = new Set(effectiveAttachments(attachments).filter((item) =>
      item.text_bytes == null ||
      (item.effective_reading_mode === "targeted" && item.effective_processing_status === "preparing")
    ).map((item) => item.document_id));
    const pending = attachments.filter((item) => pendingIds.has(item.document_id));
    if (!pending.length) return;
    let cancelled = false;

    const refresh = async () => {
      const settled = await Promise.allSettled(
        pending.map((item) => getChatDocumentReadiness(conversationId, item, token)),
      );
      if (cancelled) return;
      const updates = new Map<string, ChatDocumentReference>();
      settled.forEach((result) => {
        if (result.status === "fulfilled" && result.value) {
          updates.set(result.value.document_id, result.value);
        }
      });
      if (updates.size) setAttachments((current) => {
        let changed = false;
        const next = current.map((item) => {
          const update = updates.get(item.document_id);
          if (!update || (
            update.name === item.name && update.text_bytes === item.text_bytes &&
            update.reading_mode === item.reading_mode &&
            update.processing_status === item.processing_status &&
            update.search_status === item.search_status
          )) return item;
          changed = true;
          return update;
        });
        return changed ? next : current;
      });
    };

    void refresh();
    const timer = window.setInterval(() => void refresh(), 2_000);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [conversationId, token, attachments, setAttachments]);
}
