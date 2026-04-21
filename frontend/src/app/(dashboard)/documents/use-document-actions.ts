import { toast } from "sonner";
import { apiFetch, authFetch } from "@/lib/api";

export interface BulkResult {
  requested: number;
  succeeded: number;
  failed: number;
  errors: string[];
}

/**
 * Centralises all document-level actions (single + bulk + metadata) so the
 * page component stays focused on layout and state. Every handler toasts
 * on success/error and calls onChanged() so the caller can refetch its
 * data.
 */
export function useDocumentActions({
  orgId,
  token,
  onChanged,
}: {
  orgId: string | undefined;
  token: string | undefined;
  onChanged: () => void;
}) {
  const handleDelete = async (docId: string, docName?: string): Promise<void> => {
    if (!orgId || !token) return;
    const label = docName ? `« ${docName} »` : "ce document";
    if (
      !confirm(
        `Supprimer ${label} ?\n\nLe fichier et son indexation seront définitivement supprimés. Cette action est irréversible.`,
      )
    ) {
      return;
    }
    try {
      await apiFetch(`/documents/${orgId}/${docId}`, {
        method: "DELETE",
        token,
      });
      toast.success("Document supprimé");
      onChanged();
    } catch (err) {
      const msg = err instanceof Error ? err.message : "";
      toast.error(
        msg.includes("404")
          ? "Ce document a déjà été supprimé."
          : msg.includes("indexation")
            ? "Impossible de supprimer : le document est en cours d'indexation, réessayez dans quelques secondes."
            : msg || "Impossible de supprimer le document. Réessayez dans un instant.",
      );
    }
  };

  const handleDownload = async (docId: string): Promise<void> => {
    if (!orgId || !token) return;
    try {
      const res = await authFetch(`/documents/${orgId}/${docId}/download`, { token });
      if (!res.ok) throw new Error("Erreur");
      const blob = await res.blob();
      const disposition = res.headers.get("Content-Disposition");
      let filename = "document";
      if (disposition) {
        const utf8Match = disposition.match(/filename\*=UTF-8''(.+)/i);
        if (utf8Match) {
          filename = decodeURIComponent(utf8Match[1].replace(/;.*$/, "").trim());
        } else {
          const asciiMatch = disposition.match(/filename="(.+?)"/);
          if (asciiMatch) filename = asciiMatch[1];
        }
      }
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      toast.error(
        err instanceof Error && err.message
          ? err.message
          : "Le téléchargement a échoué. Le fichier original est peut-être indisponible, contactez le support.",
      );
    }
  };

  const handleReindex = async (docId: string): Promise<void> => {
    if (!orgId || !token) return;
    try {
      await apiFetch(`/documents/${orgId}/${docId}/reindex`, {
        method: "POST",
        token,
      });
      toast.success("Réindexation lancée");
      onChanged();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Erreur lors de la réindexation");
    }
  };

  const handleReplace = async (docId: string, file: File): Promise<void> => {
    if (!orgId || !token) return;
    const formData = new FormData();
    formData.append("file", file);
    try {
      const res = await authFetch(`/documents/${orgId}/${docId}`, {
        method: "PUT",
        body: formData,
        token,
      });
      if (!res.ok) {
        const data = await res.json().catch(() => null);
        throw new Error(data?.detail ?? "Erreur lors du remplacement");
      }
      toast.success("Document remplacé — réindexation en cours");
      onChanged();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Erreur lors du remplacement");
    }
  };

  const handleBulkDelete = async (docIds: string[]): Promise<BulkResult | null> => {
    if (!orgId || !token || docIds.length === 0) return null;
    if (
      !confirm(
        `Supprimer ${docIds.length} document${docIds.length > 1 ? "s" : ""} ?\n\nLes fichiers et leur indexation seront définitivement supprimés. Action irréversible.`,
      )
    ) {
      return null;
    }
    try {
      const res = await apiFetch<BulkResult>(`/documents/${orgId}/bulk-delete`, {
        method: "POST",
        token,
        body: JSON.stringify({ document_ids: docIds }),
      });
      if (res.failed === 0) {
        toast.success(`${res.succeeded} document${res.succeeded > 1 ? "s" : ""} supprimé${res.succeeded > 1 ? "s" : ""}`);
      } else {
        toast.warning(
          `${res.succeeded} supprimé${res.succeeded > 1 ? "s" : ""}, ${res.failed} en erreur`,
          { description: res.errors.slice(0, 3).join("\n") },
        );
      }
      onChanged();
      return res;
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "La suppression en lot a échoué");
      return null;
    }
  };

  const handleBulkReindex = async (docIds: string[]): Promise<BulkResult | null> => {
    if (!orgId || !token || docIds.length === 0) return null;
    try {
      const res = await apiFetch<BulkResult>(`/documents/${orgId}/bulk-reindex`, {
        method: "POST",
        token,
        body: JSON.stringify({ document_ids: docIds }),
      });
      if (res.failed === 0) {
        toast.success(`Réindexation lancée sur ${res.succeeded} document${res.succeeded > 1 ? "s" : ""}`);
      } else {
        toast.warning(
          `${res.succeeded} relancé${res.succeeded > 1 ? "s" : ""}, ${res.failed} ignoré${res.failed > 1 ? "s" : ""} (déjà indexé ou en cours)`,
        );
      }
      onChanged();
      return res;
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "La réindexation en lot a échoué");
      return null;
    }
  };

  const handleUpdateMetadata = async (
    docId: string,
    data: Record<string, string | null>,
  ): Promise<boolean> => {
    if (!orgId || !token) return false;
    try {
      await apiFetch(`/documents/${orgId}/${docId}`, {
        method: "PATCH",
        token,
        body: JSON.stringify(data),
      });
      toast.success("Métadonnées mises à jour");
      onChanged();
      return true;
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Impossible d'enregistrer les modifications");
      return false;
    }
  };

  return {
    handleDelete,
    handleDownload,
    handleReindex,
    handleReplace,
    handleBulkDelete,
    handleBulkReindex,
    handleUpdateMetadata,
  };
}
