"use client";

import { useErrorState } from "@/hooks/use-error-state";

import { useEffect, useRef, useState } from "react";
import {
  Download,
  FileText,
  Plus,
  Upload,
  Pencil,
  Trash2,
  Replace,
} from "lucide-react";
import { toast } from "@/lib/toast";
import { useUnsavedChanges } from "@/hooks/use-unsaved-changes";
import { apiFetch } from "@/lib/api";
import {
  dossierOperation,
  getDossier,
  downloadDossierDocument,
  uploadDossierDocument,
  type DossierDetail,
} from "@/lib/dossiers-api";
import { EntryCard } from "@/components/chat/case-file-panel";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";

export function DossierContent({
  dossier: d,
  token,
  tab,
  onChange,
  onOpenMessage,
}: {
  dossier: DossierDetail;
  token: string;
  tab: "informations" | "documents";
  onChange: (d: DossierDetail) => void;
  onOpenMessage?: (id: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const working = useRef(false);
  const [error, setError] = useErrorState("");
  const [editing, setEditing] = useState(false);
  const [description, setDescription] = useState(d.description);
  const [instructions, setInstructions] = useState(d.instructions);
  const [adding, setAdding] = useState(false);
  const [label, setLabel] = useState("");
  const [value, setValue] = useState("");
  const [uploadOpen, setUploadOpen] = useState(false);
  const [library, setLibrary] = useState(false);
  const [query, setQuery] = useState("");
  const [items, setItems] = useState<{ document_id: string; name: string }[]>(
    []
  );
  const [libraryMore, setLibraryMore] = useState(false);
  const [libraryOffset, setLibraryOffset] = useState(0);
  const [replacement, setReplacement] = useState<{
    id: string;
    name: string;
  } | null>(null);
  const [rename, setRename] = useState<{
    id: string;
    name: string;
    description: string;
  } | null>(null);
  const [remove, setRemove] = useState<{
    linkId: string;
    name: string;
    scope: string;
  } | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  useEffect(() => {
    if (!editing) {
      setDescription(d.description);
      setInstructions(d.instructions);
    }
  }, [d.description, d.instructions, editing]);
  useUnsavedChanges(
    (editing &&
      (description !== d.description || instructions !== d.instructions)) ||
      (adding && (!!label || !!value)) ||
      (!!rename &&
        d.documents.some(
          (doc) =>
            doc.document_id === rename.id &&
            (doc.name !== rename.name || doc.description !== rename.description)
        ))
  );
  const readonly = !!d.archived_at;
  async function run(fn: () => Promise<DossierDetail | void>) {
    if (working.current) return false;
    working.current = true;
    setBusy(true);
    setError("");
    try {
      const next = await fn();
      if (mounted.current && next) onChange(next);
      return true;
    } catch (e) {
      if (mounted.current)
        setError(e instanceof Error ? e.message : "Opération impossible");
      return false;
    } finally {
      working.current = false;
      if (mounted.current) setBusy(false);
    }
  }
  async function upload(file: File) {
    if (file.size > 2 * 1024 * 1024) {
      setError("Maximum 2 Mo par fichier");
      return;
    }
    if (
      await run(() =>
        uploadDossierDocument(
          d.id,
          token,
          file,
          replacement?.id,
          d.case_file.version
        ).catch(async (error) => {
          // A failed preparation can still have saved the original file.
          try {
            const latest = await getDossier(d.id, token);
            if (mounted.current) onChange(latest);
          } catch {
            /* Preserve the original upload error and the current editor. */
          }
          throw error;
        })
      )
    )
      setUploadOpen(false);
  }
  async function search(offset = 0) {
    await run(async () => {
      const result = await apiFetch<{ items: typeof items; has_more: boolean }>(
        `/dossiers/${d.id}/library?q=${encodeURIComponent(query)}&offset=${offset}`,
        { token }
      );
      setItems(result.items);
      setLibraryMore(result.has_more);
      setLibraryOffset(offset);
    });
  }
  function message(id: string) {
    if (onOpenMessage) onOpenMessage(id);
    else
      void apiFetch<{ conversation_id: string }>(
        `/dossiers/${d.id}/messages/${id}`,
        { token }
      )
        .then((r) => {
          window.location.assign(`/chat/${r.conversation_id}#message-${id}`);
        })
        .catch((e) => toast.error(e.message));
  }
  const active = d.case_file.entries.filter(
    (e) =>
      ["active", "confirmed", "contested"].includes(e.status) &&
      ["fact", "party_statement", "assumption", "deadline"].includes(
        e.entry_type
      )
  );
  const old = d.case_file.entries.filter((e) =>
    ["archived", "superseded"].includes(e.status)
  );
  const card = (entry: (typeof active)[number], editable = true) => (
    <EntryCard
      key={entry.id}
      entry={entry}
      onOpenMessage={message}
      busy={busy}
      onAction={
        !readonly && editable
          ? async (e, operation, value, comment) =>
              run(() =>
                dossierOperation(d.id, token, `/entries/${e.id}/revisions`, {
                  operation,
                  expected_case_version: d.case_file.version,
                  ...(value !== undefined ? { value } : {}),
                  ...(comment !== undefined ? { comment } : {}),
                })
              )
          : undefined
      }
    />
  );
  return (
    <div className="space-y-5">
      {error && (
        <p
          role="alert"
          className="border-destructive/30 text-destructive rounded-lg border p-3 text-sm"
        >
          {error}
        </p>
      )}
      {busy && (
        <p role="status" className="text-muted-foreground text-sm">
          Enregistrement ou préparation…
        </p>
      )}
      {tab === "informations" ? (
        <>
          <section className="space-y-3 rounded-xl border p-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h2 className="font-medium">Contexte et consignes</h2>
              {!readonly && !editing && (
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => setEditing(true)}
                >
                  <Pencil className="size-4" /> Modifier
                </Button>
              )}
            </div>
            {editing ? (
              <form
                className="space-y-3"
                onSubmit={(e) => {
                  e.preventDefault();
                  void run(() =>
                    dossierOperation(
                      d.id,
                      token,
                      "",
                      {
                        expected_version: d.version,
                        description,
                        instructions,
                      },
                      "PATCH"
                    )
                  ).then((ok) => {
                    if (ok) setEditing(false);
                  });
                }}
              >
                <label className="block text-sm">
                  Description
                  <Textarea
                    className="mt-1"
                    aria-label="Description"
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    maxLength={20000}
                  />
                </label>
                <label className="block text-sm">
                  Consignes pour AORIA
                  <Textarea
                    className="mt-1"
                    aria-label="Consignes pour AORIA"
                    value={instructions}
                    onChange={(e) => setInstructions(e.target.value)}
                    maxLength={10000}
                    placeholder="Préparer des réponses destinées aux managers"
                  />
                </label>
                <div className="flex gap-2">
                  <Button disabled={busy}>Enregistrer</Button>
                  <Button
                    type="button"
                    variant="outline"
                    disabled={busy}
                    onClick={() => setEditing(false)}
                  >
                    Annuler
                  </Button>
                </div>
              </form>
            ) : (
              <>
                <p className="text-muted-foreground text-sm whitespace-pre-wrap">
                  {d.description ||
                    "Décrivez le sujet et l’objectif de ce dossier."}
                </p>
                {d.instructions && (
                  <div>
                    <p className="text-xs font-medium">Consignes pour AORIA</p>
                    <p className="mt-1 text-sm whitespace-pre-wrap">
                      {d.instructions}
                    </p>
                  </div>
                )}
              </>
            )}
          </section>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="font-medium">Informations du dossier</h2>
            {!readonly && (
              <Button
                size="sm"
                variant="outline"
                onClick={() => setAdding(true)}
              >
                <Plus className="size-4" />
                Ajouter une information
              </Button>
            )}
          </div>
          {active.some(
            (e) =>
              e.status === "contested" ||
              (e.entry_type === "assumption" && e.status !== "confirmed")
          ) && (
            <section className="space-y-2">
              <h3 className="text-sm font-medium">À vérifier</h3>
              {active
                .filter(
                  (e) =>
                    e.status === "contested" ||
                    (e.entry_type === "assumption" && e.status !== "confirmed")
                )
                .map((e) => card(e))}
            </section>
          )}
          <section className="space-y-2">
            <h3 className="text-sm font-medium">Informations retenues</h3>
            {active
              .filter(
                (e) =>
                  e.status !== "contested" &&
                  (e.entry_type !== "assumption" || e.status === "confirmed")
              )
              .map((e) => card(e))}
            {!active.length && (
              <p className="bg-muted/40 text-muted-foreground rounded-lg p-4 text-sm">
                Ajoutez une information ou décrivez votre situation dans une
                conversation.
              </p>
            )}
          </section>
          {!!old.length && (
            <details>
              <summary className="cursor-pointer text-sm">
                Anciennes informations ({old.length})
              </summary>
              <div className="mt-3 space-y-2">
                {old.map((e) => card(e, false))}
              </div>
            </details>
          )}
          {d.case_file.inherited_context && (
            <details>
              <summary className="cursor-pointer text-sm">
                Profil de l’entreprise
              </summary>
              <p className="text-muted-foreground my-2 text-xs">
                Informations issues de l’organisation, modifiables dans
                Organisation.
              </p>
              <dl className="space-y-2 text-sm">
                {Object.entries(d.case_file.inherited_context)
                  .filter(([, v]) => v !== null && v !== "")
                  .map(([k, v]) => (
                    <div key={k}>
                      <dt className="text-muted-foreground">
                        {(
                          {
                            nom: "Société",
                            taille: "Effectif",
                            convention_collective: "Convention collective",
                            secteur_activite: "Secteur d’activité",
                          } as Record<string, string>
                        )[k] || k}
                      </dt>
                      <dd>{String(v)}</dd>
                    </div>
                  ))}
              </dl>
            </details>
          )}
        </>
      ) : (
        <>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="font-medium">Documents ({d.documents.length})</h2>
            <Button
              size="sm"
              variant="ghost"
              disabled={busy}
              onClick={() => void run(() => getDossier(d.id, token))}
            >
              Actualiser
            </Button>
            {!readonly && (
              <Button
                size="sm"
                onClick={() => {
                  setReplacement(null);
                  setUploadOpen(true);
                  setLibrary(false);
                }}
              >
                <Plus className="size-4" />
                Ajouter un document
              </Button>
            )}
          </div>
          <p className="text-muted-foreground text-xs">
            Les fichiers importés restent dans ce dossier. Les documents
            d’entreprise référencés conservent leurs droits.
          </p>
          {!d.documents.length && (
            <div className="rounded-xl border border-dashed p-10 text-center">
              <FileText className="text-muted-foreground mx-auto mb-3 size-7" />
              <p className="text-sm">
                Ajoutez des documents pour préciser votre situation.
              </p>
              {!readonly && (
                <Button
                  className="mt-4"
                  variant="outline"
                  onClick={() => {
                    setReplacement(null);
                    setUploadOpen(true);
                  }}
                >
                  Ajouter un document
                </Button>
              )}
            </div>
          )}
          {d.documents.map((doc) => (
            <article
              key={doc.id}
              className="flex flex-wrap items-start gap-3 rounded-xl border p-3"
            >
              <FileText className="text-primary mt-1 size-4 shrink-0" />
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium break-words">{doc.name}</p>
                <p className="text-muted-foreground mt-1 text-xs">
                  {doc.scope === "dossier"
                    ? "Pièce privée du dossier"
                    : "Document de l’entreprise"}{" "}
                  · {doc.file_format?.toUpperCase()}
                </p>
                {doc.description && (
                  <p className="mt-2 text-sm whitespace-pre-wrap">
                    {doc.description}
                  </p>
                )}
                <p className="text-muted-foreground text-xs">
                  Ajouté le{" "}
                  {new Date(doc.created_at).toLocaleDateString("fr-FR")}
                </p>
                {doc.status !== "ready" && (
                  <p className="text-destructive mt-1 text-xs">
                    {doc.status === "preparing"
                      ? "Préparation en cours : actualisez dans un instant."
                      : doc.status === "error"
                        ? "Préparation incomplète"
                        : "Document indisponible"}
                  </p>
                )}
              </div>
              <div className="flex w-full flex-wrap justify-end gap-1 sm:w-auto">
                <Button
                  size="icon"
                  variant="ghost"
                  disabled={!doc.document_id || doc.status === "unavailable"}
                  aria-label={`Télécharger ${doc.name}`}
                  onClick={() =>
                    void downloadDossierDocument(d.id, token, doc).catch((e) =>
                      toast.error(e.message)
                    )
                  }
                >
                  <Download className="size-4" />
                </Button>
                {!readonly && (
                  <>
                    <Button
                      size="icon"
                      variant="ghost"
                      disabled={busy || !doc.document_id || doc.status === "unavailable"}
                      aria-label={`Renommer ${doc.name}`}
                      onClick={() =>
                        setRename({
                          id: doc.document_id!,
                          name: doc.name,
                          description: doc.description,
                        })
                      }
                    >
                      <Pencil className="size-4" />
                    </Button>
                    <Button
                      size="icon"
                      variant="ghost"
                      disabled={busy || !doc.document_id || doc.status === "unavailable"}
                      aria-label={`Remplacer ${doc.name}`}
                      onClick={() => {
                        setReplacement({ id: doc.document_id!, name: doc.name });
                        setLibrary(false);
                        setUploadOpen(true);
                      }}
                    >
                      <Replace className="size-4" />
                    </Button>
                    <Button
                      size="icon"
                      variant="ghost"
                      aria-label={`Retirer ${doc.name}`}
                      onClick={() =>
                        setRemove({
                          linkId: doc.id,
                          name: doc.name,
                          scope: doc.scope,
                        })
                      }
                    >
                      <Trash2 className="size-4" />
                    </Button>
                  </>
                )}
                {!readonly && doc.status === "error" && (
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={busy}
                    onClick={() =>
                      void run(() =>
                        dossierOperation(
                          d.id,
                          token,
                          `/documents/${doc.document_id}/prepare`,
                          {}
                        )
                      )
                    }
                  >
                    Réessayer
                  </Button>
                )}
              </div>
            </article>
          ))}
        </>
      )}
      <Dialog
        open={adding}
        onOpenChange={(v) => {
          if (!busy) setAdding(v);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Ajouter une information</DialogTitle>
            <DialogDescription>
              Cette information sera disponible dans les conversations du
              dossier.
            </DialogDescription>
          </DialogHeader>
          <form
            className="space-y-4"
            onSubmit={(e) => {
              e.preventDefault();
              void run(() =>
                dossierOperation(d.id, token, "/entries", {
                  label,
                  value,
                  expected_case_version: d.case_file.version,
                })
              ).then((ok) => {
                if (ok) {
                  setAdding(false);
                  setLabel("");
                  setValue("");
                }
              });
            }}
          >
            <label className="block text-sm">
              Intitulé
              <Input
                value={label}
                onChange={(e) => setLabel(e.target.value)}
                maxLength={500}
              />
            </label>
            <label className="block text-sm">
              Information
              <Textarea
                value={value}
                onChange={(e) => setValue(e.target.value)}
                maxLength={20000}
              />
            </label>
            {error && (
              <p role="alert" className="text-destructive text-sm">
                {error}
              </p>
            )}
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => setAdding(false)}
                disabled={busy}
              >
                Annuler
              </Button>
              <Button disabled={busy || !label.trim() || !value.trim()}>
                Enregistrer
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
      <Dialog
        open={uploadOpen}
        onOpenChange={(v) => {
          if (!busy) setUploadOpen(v);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Ajouter un document</DialogTitle>
            <DialogDescription>
              {replacement
                ? `Remplacer « ${replacement.name} ». La nouvelle pièce sera utilisée pour les prochaines questions. Les anciens échanges restent inchangés. `
                : "Nouvelle pièce distincte. "}
              {d.name} · Import privé au dossier · PDF, DOCX ou TXT, 2 Mo
              maximum.
            </DialogDescription>
          </DialogHeader>
          <div
            className="rounded-xl border border-dashed p-8 text-center"
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              if (!busy && e.dataTransfer.files[0])
                void upload(e.dataTransfer.files[0]);
            }}
          >
            <Upload className="text-muted-foreground mx-auto mb-3 size-6" />
            <p className="text-sm">Glissez un fichier ici</p>
            <Button
              className="mt-3"
              variant="outline"
              disabled={busy}
              onClick={() => input.current?.click()}
            >
              Importer un fichier
            </Button>
            <input
              type="file"
              hidden
              ref={input}
              accept=".pdf,.docx,.txt"
              onChange={(e) => {
                if (e.target.files?.[0]) void upload(e.target.files[0]);
                e.target.value = "";
              }}
            />
          </div>
          <Button
            variant="outline"
            disabled={busy}
            hidden={!!replacement}
            onClick={() => {
              setLibrary(true);
              void search();
            }}
          >
            Choisir dans les documents de l’entreprise
          </Button>
          {library && (
            <div className="space-y-2">
              <form
                className="flex gap-2"
                onSubmit={(e) => {
                  e.preventDefault();
                  void search();
                }}
              >
                <Input
                  aria-label="Nom du document"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Rechercher un document"
                />
                <Button disabled={busy}>Rechercher</Button>
              </form>
              <div className="max-h-52 space-y-2 overflow-auto">
                {items.map((doc) => (
                  <div
                    className="flex items-center gap-2 rounded-lg border p-2 text-sm"
                    key={doc.document_id}
                  >
                    <span className="min-w-0 flex-1 break-words">
                      {doc.name}
                    </span>
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={
                        busy ||
                        d.documents.some(
                          (x) => x.document_id === doc.document_id
                        )
                      }
                      onClick={() =>
                        void run(() =>
                          dossierOperation(d.id, token, "/documents/actions", {
                            operation: "attach",
                            document_id: doc.document_id,
                            expected_case_version: d.case_file.version,
                          })
                        ).then((ok) => {
                          if (ok) setUploadOpen(false);
                        })
                      }
                    >
                      Ajouter
                    </Button>
                  </div>
                ))}
                {!items.length && !busy && (
                  <p className="text-muted-foreground text-sm">
                    Aucun document trouvé.
                  </p>
                )}
              </div>
              <div className="flex justify-between">
                <Button
                  variant="ghost"
                  disabled={!libraryOffset || busy}
                  onClick={() => void search(libraryOffset - 20)}
                >
                  Précédents
                </Button>
                <Button
                  variant="ghost"
                  disabled={!libraryMore || busy}
                  onClick={() => void search(libraryOffset + 20)}
                >
                  Suivants
                </Button>
              </div>
            </div>
          )}
          {busy && <p role="status">Préparation du document…</p>}
          {error && (
            <p role="alert" className="text-destructive text-sm">
              {error}
            </p>
          )}
        </DialogContent>
      </Dialog>
      <Dialog
        open={!!rename}
        onOpenChange={(v) => {
          if (!v && !busy) setRename(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Modifier le document dans ce dossier</DialogTitle>
            <DialogDescription>
              Le nom du document d’entreprise reste inchangé.
            </DialogDescription>
          </DialogHeader>
          <Input
            aria-label="Nom du document dans le dossier"
            value={rename?.name ?? ""}
            onChange={(e) =>
              setRename((r) => r && { ...r, name: e.target.value })
            }
          />
          <Textarea
            aria-label="Description du document"
            placeholder="Description facultative"
            value={rename?.description ?? ""}
            onChange={(e) =>
              setRename((r) => r && { ...r, description: e.target.value })
            }
          />
          <Button
            disabled={busy || !rename?.name.trim()}
            onClick={() =>
              void run(() =>
                dossierOperation(d.id, token, "/documents/actions", {
                  operation: "rename",
                  document_id: rename!.id,
                  name: rename!.name,
                  description: rename!.description,
                  expected_case_version: d.case_file.version,
                })
              ).then((ok) => {
                if (ok) setRename(null);
              })
            }
          >
            Enregistrer
          </Button>
          {error && <p role="alert">{error}</p>}
        </DialogContent>
      </Dialog>
      <Dialog
        open={!!remove}
        onOpenChange={(v) => {
          if (!v && !busy) setRemove(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Retirer du dossier</DialogTitle>
            <DialogDescription>
              {remove?.name} ne sera plus une pièce active du dossier.{" "}
              {remove?.scope === "entreprise"
                ? "Le document reste dans les Documents de l’entreprise."
                : "Les échanges précédents restent conservés."}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              disabled={busy}
              onClick={() => setRemove(null)}
            >
              Annuler
            </Button>
            <Button
              variant="destructive"
              disabled={busy}
              onClick={() =>
                void run(() =>
                  dossierOperation(d.id, token, "/documents/actions", {
                    operation: "remove",
                    link_id: remove!.linkId,
                    expected_case_version: d.case_file.version,
                  })
                ).then((ok) => {
                  if (ok) setRemove(null);
                })
              }
            >
              Retirer
            </Button>
          </DialogFooter>
          {error && <p role="alert">{error}</p>}
        </DialogContent>
      </Dialog>
    </div>
  );
}
