import type { ChatDocumentReference } from "@/lib/chat-api";

export const FULL_DOCUMENT_BUDGET_BYTES = 96_000;

export type EffectiveAttachment = ChatDocumentReference & {
  effective_reading_mode: "full" | "targeted";
  effective_processing_status: "ready" | "preparing" | "error";
};

/** Mirrors the server's deterministic allocation: smallest texts stay whole. */
export function effectiveAttachments(items: ChatDocumentReference[]): EffectiveAttachment[] {
  let remaining = FULL_DOCUMENT_BUDGET_BYTES;
  const full = new Set<string>();
  [...items]
    .filter((item) => typeof item.text_bytes === "number")
    .sort((a, b) => (a.text_bytes ?? 0) - (b.text_bytes ?? 0))
    .forEach((item) => {
      if ((item.text_bytes ?? 0) <= remaining) {
        full.add(item.document_id);
        remaining -= item.text_bytes ?? 0;
      }
    });

  return items.map((item) => {
    const mode = full.has(item.document_id) ? "full" :
      (item.text_bytes == null ? item.reading_mode ?? "full" : "targeted");
    const status = item.text_bytes == null ? item.processing_status ?? "preparing" :
      mode === "full" ? "ready" : item.search_status ?? item.processing_status ?? "preparing";
    return { ...item, effective_reading_mode: mode, effective_processing_status: status };
  });
}

export function attachmentBlocker(items: ChatDocumentReference[]): string | null {
  const states = effectiveAttachments(items);
  if (states.some((item) => item.effective_processing_status === "error")) {
    return "La préparation d’un document long a échoué. Retirez-le ou réessayez depuis les documents de l’entreprise.";
  }
  if (states.some((item) => item.effective_processing_status === "preparing")) {
    return "Un document long est encore en préparation. Vous pourrez envoyer votre message dès qu’il sera prêt.";
  }
  return null;
}
