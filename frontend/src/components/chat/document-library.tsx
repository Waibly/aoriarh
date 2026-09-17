"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { searchChatLibrary, type LibraryDocument, type LibrarySearch } from "@/lib/chat-document-library";

const emptySearch: LibrarySearch = { name: "", uploaded_from: "", uploaded_to: "" };

export function DocumentLibrary({ conversationId, token, selectedIds, disabled, onSelect }: {
  conversationId: string;
  token: string;
  selectedIds: string[];
  disabled: boolean;
  onSelect: (document: LibraryDocument) => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState(emptySearch);
  const [submitted, setSubmitted] = useState(emptySearch);
  const [items, setItems] = useState<LibraryDocument[]>([]);
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(false);
  const [preparing, setPreparing] = useState(false);
  const [error, setError] = useState("");
  const sequence = useRef(0);
  const selecting = useRef(false);
  useEffect(() => () => { sequence.current += 1; }, []);

  async function load(criteria: LibrarySearch, nextOffset = 0) {
    const request = ++sequence.current;
    setLoading(true);
    setError("");
    setItems([]);
    setHasMore(false);
    try {
      const result = await searchChatLibrary(conversationId, token, criteria, nextOffset);
      if (request !== sequence.current) return;
      setItems(result.items);
      setHasMore(result.has_more);
      setOffset(nextOffset);
      setSubmitted(criteria);
    } catch (e) {
      if (request === sequence.current) setError(e instanceof Error ? e.message : "Recherche impossible");
    } finally {
      if (request === sequence.current) setLoading(false);
    }
  }

  function changeOpen(value: boolean) {
    if (selecting.current) return;
    sequence.current += 1;
    setOpen(value);
    if (value) void load(search);
  }

  async function select(document: LibraryDocument) {
    if (selecting.current || disabled || selectedIds.length >= 3) return;
    selecting.current = true;
    const request = sequence.current;
    setPreparing(true);
    setError("");
    try {
      await onSelect(document);
      if (request === sequence.current) setOpen(false);
    } catch (e) {
      if (request === sequence.current) setError(e instanceof Error ? e.message : "Préparation impossible");
    } finally {
      selecting.current = false;
      if (request === sequence.current) setPreparing(false);
    }
  }

  return <>
    <div className="px-2 pt-2 sm:px-6">
      <Button variant="outline" size="sm" disabled={disabled || selectedIds.length >= 3}
        onClick={() => changeOpen(true)}>Documents de l’entreprise</Button>
    </div>
    <Dialog open={open} onOpenChange={changeOpen}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Choisir un document de l’entreprise</DialogTitle>
          <DialogDescription>Recherchez par nom ou date de dépôt (UTC), puis choisissez la pièce à lire. Aucun fichier n’est dupliqué.</DialogDescription>
        </DialogHeader>
        <form className="space-y-3" onSubmit={(event) => { event.preventDefault(); if (!preparing) void load(search); }}>
          <label className="block text-sm">Nom du document
            <input className="mt-1 w-full rounded border p-2" value={search.name} maxLength={200}
              disabled={preparing} onChange={(e) => setSearch({ ...search, name: e.target.value })} />
          </label>
          <div className="flex gap-2">
            <label className="text-sm">Déposé à partir du
              <input type="date" className="mt-1 w-full rounded border p-2" value={search.uploaded_from}
                disabled={preparing} onChange={(e) => setSearch({ ...search, uploaded_from: e.target.value })} />
            </label>
            <label className="text-sm">Déposé jusqu’au
              <input type="date" className="mt-1 w-full rounded border p-2" value={search.uploaded_to}
                disabled={preparing} onChange={(e) => setSearch({ ...search, uploaded_to: e.target.value })} />
            </label>
          </div>
          <Button type="submit" disabled={loading || preparing}>Rechercher</Button>
        </form>
        {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
        {loading ? <p role="status">Recherche…</p> : <div className="max-h-64 overflow-auto space-y-2">
          {!error && items.length === 0 && <p>Aucun document trouvé. Essayez un autre nom ou une autre période.</p>}
          {items.map((doc) => <div key={doc.document_id} className="flex items-center justify-between gap-3 rounded border p-2">
            <div className="min-w-0 text-sm">
              <p className="break-words">{doc.name}</p>
              <p className="text-xs text-muted-foreground">Déposé le {new Date(doc.uploaded_at).toLocaleDateString("fr-FR", { timeZone: "UTC" })} · {doc.file_format?.toUpperCase()}</p>
              {!doc.source_sha256 && <p className="text-xs">Version du fichier indisponible</p>}
            </div>
            <Button size="sm" variant="outline" aria-label={`Choisir ${doc.name}`}
              disabled={disabled || preparing || selectedIds.length >= 3 || selectedIds.includes(doc.document_id) || !doc.source_sha256}
              onClick={() => void select(doc)}>{selectedIds.includes(doc.document_id) ? "Déjà joint" : "Choisir"}</Button>
          </div>)}
        </div>}
        {preparing && <p role="status">Préparation du texte pour la conversation…</p>}
        <div className="flex justify-between">
          <Button variant="ghost" disabled={loading || preparing || offset === 0} onClick={() => void load(submitted, offset - 20)}>Précédents</Button>
          <Button variant="ghost" disabled={loading || preparing || !hasMore} onClick={() => void load(submitted, offset + 20)}>Suivants</Button>
        </div>
      </DialogContent>
    </Dialog>
  </>;
}
