"use client";

import { useCallback, useEffect, useId, useRef, useState } from "react";
import {
  FileText,
  FolderOpen,
  LoaderCircle,
  Ellipsis,
  Pencil,
  RefreshCw,
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Textarea } from "@/components/ui/textarea";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import {
  getConversationCaseFile,
  updateConversationCaseEntry,
  type CaseEntryOperation,
} from "@/lib/chat-api";
import type {
  CaseDocumentLink,
  CaseEntry,
  ConversationCaseFile,
} from "@/types/api";

const COMPANY_FIELDS: Record<string, string> = {
  nom: "Société",
  taille: "Effectif",
  convention_collective: "Convention collective",
  secteur_activite: "Secteur d’activité",
};
const FACT_TYPES = new Set([
  "fact",
  "party_statement",
  "assumption",
  "deadline",
]);
const CURRENT_STATUSES = new Set(["active", "confirmed", "contested"]);
function needsConfirmation(entry: CaseEntry): boolean {
  return (
    entry.status === "contested" ||
    (entry.entry_type === "assumption" && entry.status !== "confirmed")
  );
}
type EntryAction = (
  entry: CaseEntry,
  operation: CaseEntryOperation,
  value?: string,
  comment?: string
) => Promise<boolean>;

function dateLabel(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "Date non précisée"
    : new Intl.DateTimeFormat("fr-FR", {
        day: "numeric",
        month: "long",
        year: "numeric",
      }).format(date);
}

function EntryCard({
  entry,
  document,
  onOpenMessage,
  onAction,
  busy = false,
}: {
  entry: CaseEntry;
  document?: CaseDocumentLink;
  onOpenMessage: (id: string) => void;
  onAction?: EntryAction;
  busy?: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const detailsId = useId();
  const [value, setValue] = useState(entry.value_text ?? "");
  const [comment, setComment] = useState("");
  const uncertain = needsConfirmation(entry);
  const act = async (
    operation: CaseEntryOperation,
    corrected?: string,
    note?: string
  ) => {
    if (await onAction?.(entry, operation, corrected, note)) {
      setEditing(false);
      setComment("");
    }
  };
  return (
    <article className="rounded-lg border border-slate-200 bg-white p-3 text-slate-900">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <h4 className="text-xs font-medium break-words text-slate-500">
            {entry.label}
          </h4>
          {entry.value_text !== null && (
            <p className="mt-0.5 text-sm leading-snug break-words whitespace-pre-wrap">
              {entry.value_text}
            </p>
          )}
        </div>
        <div className="flex shrink-0 items-center">
          {onAction && !editing && (
            <Button
              type="button"
              size="xs"
              variant="ghost"
              disabled={busy}
              className="size-8 p-0 text-slate-500"
              aria-label="Corriger"
              title="Corriger cette information"
              onClick={() => {
                setValue(entry.value_text ?? "");
                setEditing(true);
              }}
            >
              <Pencil className="size-3.5" />
            </Button>
          )}
          {(entry.source_excerpt ||
            entry.source_message_id ||
            document ||
            onAction) && (
            <Button
              type="button"
              size="xs"
              variant="ghost"
              className="size-8 p-0 text-slate-500"
              aria-label="Détails et actions"
              title="Détails et actions"
              aria-expanded={detailsOpen}
              aria-controls={detailsId}
              onClick={() => setDetailsOpen((previous) => !previous)}
            >
              <Ellipsis className="size-4" />
            </Button>
          )}
        </div>
      </div>
      <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs text-slate-500 empty:hidden">
        {uncertain && (
          <span className="text-amber-700 dark:text-amber-400">
            {entry.status === "contested"
              ? "Information à vérifier"
              : "Hypothèse à confirmer"}
          </span>
        )}
        {entry.status === "confirmed" && <span>Confirmé par vous</span>}
        {entry.entry_type === "party_statement" && (
          <span>Déclaration rapportée</span>
        )}
        {entry.status === "superseded" && <span>Ancienne information</span>}
        {entry.status === "archived" && <span>Retirée du dossier</span>}
        {(entry.valid_from || entry.valid_to) && (
          <span>
            {entry.valid_from ? dateLabel(entry.valid_from) : "Jusqu’au"}
            {entry.valid_to
              ? " " + (entry.valid_from ? "– " : "") + dateLabel(entry.valid_to)
              : ""}
          </span>
        )}
      </div>
      {editing && (
        <div className="mt-3 space-y-3 border-t pt-3">
          <label className="block text-xs font-medium">
            Information corrigée
            <Textarea
              className="mt-1 min-h-20"
              value={value}
              disabled={busy}
              onChange={(e) => setValue(e.target.value)}
            />
          </label>
          <label className="block text-xs font-medium">
            Précision facultative
            <Textarea
              className="mt-1 min-h-16"
              value={comment}
              disabled={busy}
              placeholder="Par exemple : vérifié sur le bulletin de salaire"
              onChange={(e) => setComment(e.target.value)}
            />
          </label>
          <p className="text-muted-foreground text-xs leading-relaxed">
            Cette correction sera prise en compte pour vos prochaines questions.
            Les réponses déjà reçues restent inchangées.
          </p>
          <div className="flex flex-wrap justify-end gap-2">
            <Button
              type="button"
              size="sm"
              variant="ghost"
              disabled={busy}
              onClick={() => setEditing(false)}
            >
              Annuler
            </Button>
            <Button
              type="button"
              size="sm"
              disabled={busy || !value.trim()}
              onClick={() => void act("correct", value, comment || undefined)}
            >
              Enregistrer
            </Button>
          </div>
        </div>
      )}
      <div id={detailsId} hidden={!detailsOpen}>
        {(entry.source_excerpt || entry.source_message_id || document) && (
          <details className="mt-3 text-xs">
            <summary className="text-muted-foreground cursor-pointer">
              D’où vient cette information ?
            </summary>
            <div className="text-muted-foreground mt-2 space-y-2">
              {document && (
                <p className="break-words">
                  Document : {document.document_name}
                </p>
              )}
              {document?.reading_scope === "targeted_passages" && (
                <p>Seuls certains passages ont été consultés.</p>
              )}
              {entry.source_excerpt && (
                <blockquote className="border-l-2 pl-3 break-words whitespace-pre-wrap">
                  {entry.source_excerpt}
                </blockquote>
              )}
              {entry.source_message_id && (
                <Button
                  type="button"
                  size="xs"
                  variant="link"
                  className="h-auto px-0"
                  onClick={() => onOpenMessage(entry.source_message_id!)}
                >
                  Voir le message d’origine
                </Button>
              )}
            </div>
          </details>
        )}
        {onAction && !editing && (
          <details className="mt-2 text-xs">
            <summary className="text-muted-foreground cursor-pointer">
              Autres actions
            </summary>
            <div className="mt-2 flex flex-wrap gap-2">
              {entry.status !== "confirmed" && (
                <Button
                  type="button"
                  size="xs"
                  variant="outline"
                  disabled={busy}
                  onClick={() => void act("confirm")}
                >
                  Confirmer
                </Button>
              )}
              {entry.status !== "contested" && (
                <Button
                  type="button"
                  size="xs"
                  variant="outline"
                  disabled={busy}
                  onClick={() => void act("contest")}
                >
                  Signaler un doute
                </Button>
              )}
              <Button
                type="button"
                size="xs"
                variant="ghost"
                disabled={busy}
                onClick={() => {
                  if (
                    window.confirm(
                      "Retirer cette information du dossier ? Elle restera accessible dans les anciennes informations."
                    )
                  )
                    void act("archive");
                }}
              >
                Retirer du dossier
              </Button>
            </div>
          </details>
        )}
      </div>
    </article>
  );
}

export function CaseFilePanel({
  conversationId,
  token,
  open,
  onOpenChange,
  refreshVersion,
  onOpenMessage,
}: {
  conversationId: string;
  token: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  refreshVersion: number;
  onOpenMessage: (messageId: string) => void;
}) {
  const [loadedCase, setLoadedCase] = useState<ConversationCaseFile | null>(
    null
  );
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const [actingEntryId, setActingEntryId] = useState<string | null>(null);
  const sequence = useRef(0);
  const caseFile =
    loadedCase?.conversation_id === conversationId ? loadedCase : null;
  const load = useCallback(async () => {
    const request = ++sequence.current;
    setLoading(true);
    setError(false);
    try {
      const result = await getConversationCaseFile(conversationId, token);
      if (request === sequence.current) setLoadedCase(result);
    } catch {
      if (request === sequence.current) setError(true);
    } finally {
      if (request === sequence.current) setLoading(false);
    }
  }, [conversationId, token]);
  useEffect(() => {
    if (!open) return;
    void load();
    return () => {
      sequence.current += 1;
    };
  }, [open, refreshVersion, load]);
  const applyAction: EntryAction = async (entry, operation, value, comment) => {
    if (!caseFile || actingEntryId) return false;
    const request = ++sequence.current;
    setActingEntryId(entry.id);
    try {
      const result = await updateConversationCaseEntry(
        conversationId,
        entry.id,
        token,
        {
          operation,
          expected_case_version: caseFile.version,
          ...(value !== undefined ? { value } : {}),
          ...(comment !== undefined ? { comment } : {}),
        }
      );
      if (request !== sequence.current) return false;
      setLoadedCase(result);
      toast.success(
        operation === "correct"
          ? "Information corrigée."
          : operation === "archive"
            ? "Information retirée du dossier."
            : operation === "contest"
              ? "Information à vérifier."
              : "Information confirmée."
      );
      return true;
    } catch {
      if (request === sequence.current) {
        toast.error(
          "La modification n’a pas pu être enregistrée. Vérifiez le dossier actualisé avant de réessayer."
        );
        await load();
      }
      return false;
    } finally {
      setActingEntryId(null);
    }
  };
  const facts = (caseFile?.entries ?? []).filter((entry) =>
    FACT_TYPES.has(entry.entry_type)
  );
  const current = facts.filter((entry) => CURRENT_STATUSES.has(entry.status));
  const needsChecking = current.filter(needsConfirmation);
  const retained = current.filter((entry) => !needsConfirmation(entry));
  const history = facts.filter((entry) => !CURRENT_STATUSES.has(entry.status));
  const company = Object.entries(COMPANY_FIELDS).filter(([key]) => {
    const value = caseFile?.inherited_context?.[key];
    return value !== undefined && value !== null && value !== "";
  });
  const card = (entry: CaseEntry, editable = true) => (
    <EntryCard
      key={entry.id}
      entry={entry}
      document={caseFile?.documents.find(
        (doc) =>
          doc.document_id === entry.source_document_id &&
          doc.extraction_id === entry.source_extraction_id
      )}
      onOpenMessage={onOpenMessage}
      onAction={editable ? applyAction : undefined}
      busy={actingEntryId !== null}
    />
  );
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-full gap-0 p-0 sm:max-w-lg">
        <SheetHeader className="border-b px-4 py-4 pr-12">
          <SheetTitle className="flex items-center gap-2">
            <FolderOpen className="size-5 text-[#652bb0]" /> Votre dossier
          </SheetTitle>
          <SheetDescription>
            Les faits de cette conversation, actualisés au fil des échanges.
          </SheetDescription>
        </SheetHeader>
        <ScrollArea className="min-h-0 flex-1 bg-slate-50">
          <div className="space-y-4 p-4">
            {loading && !caseFile && (
              <p
                role="status"
                className="text-muted-foreground flex items-center justify-center gap-2 py-12 text-sm"
              >
                <LoaderCircle className="size-4 animate-spin" /> Chargement du
                dossier…
              </p>
            )}
            {error && (
              <div role="alert" className="rounded-lg border p-4 text-sm">
                Le dossier n’a pas pu être actualisé.
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  className="mt-3 flex"
                  onClick={load}
                >
                  <RefreshCw /> Réessayer
                </Button>
              </div>
            )}
            {caseFile && (
              <>
                {needsChecking.length > 0 && (
                  <section aria-labelledby="case-check-heading">
                    <h3
                      id="case-check-heading"
                      className="mb-1 text-sm font-semibold"
                    >
                      À vérifier
                    </h3>
                    <div className="space-y-2">
                      {needsChecking.map((entry) => card(entry))}
                    </div>
                  </section>
                )}
                <section aria-labelledby="case-facts-heading">
                  <h3
                    id="case-facts-heading"
                    className="mb-2 text-sm font-semibold"
                  >
                    Informations retenues
                  </h3>
                  {retained.length > 0 ? (
                    <div className="space-y-2">
                      {retained.map((entry) => card(entry))}
                    </div>
                  ) : (
                    <p className="bg-muted/40 text-muted-foreground rounded-xl p-4 text-sm leading-relaxed">
                      {needsChecking.length
                        ? "Les informations à préciser sont regroupées ci-dessus."
                        : "Votre dossier se complétera au fil de vos prochaines questions. Décrivez votre situation dans la conversation pour commencer."}
                    </p>
                  )}
                </section>
                <div className="space-y-3 border-t pt-5">
                  {company.length > 0 && (
                    <details className="text-sm">
                      <summary className="cursor-pointer py-1 font-medium">
                        Profil de l’entreprise
                      </summary>
                      <p className="text-muted-foreground my-3 text-xs leading-relaxed">
                        Ces informations viennent du profil de l’entreprise.
                        Elles peuvent différer de la situation décrite dans
                        cette conversation.
                      </p>
                      <dl className="bg-muted/40 space-y-3 rounded-xl p-4">
                        {company.map(([key, label]) => (
                          <div key={key}>
                            <dt className="text-muted-foreground text-xs">
                              {label}
                            </dt>
                            <dd className="mt-1 break-words whitespace-pre-wrap">
                              {String(caseFile.inherited_context?.[key])}
                            </dd>
                          </div>
                        ))}
                      </dl>
                    </details>
                  )}
                  {caseFile.documents.length > 0 && (
                    <details className="text-sm">
                      <summary className="cursor-pointer py-1 font-medium">
                        Documents consultés ({caseFile.documents.length})
                      </summary>
                      <ul className="mt-3 space-y-3">
                        {caseFile.documents.map((doc) => (
                          <li key={doc.id} className="rounded-lg border p-3">
                            <div className="flex items-start gap-2">
                              <FileText className="mt-0.5 size-4 shrink-0" />
                              <span className="break-words">
                                {doc.document_name}
                              </span>
                            </div>
                            {doc.reading_scope === "targeted_passages" && (
                              <p className="text-muted-foreground mt-1 text-xs">
                                Certains passages seulement ont été consultés.
                              </p>
                            )}
                            {doc.added_from_message_id && (
                              <Button
                                type="button"
                                size="xs"
                                variant="link"
                                className="mt-1 px-0"
                                onClick={() =>
                                  onOpenMessage(doc.added_from_message_id!)
                                }
                              >
                                Voir le message associé
                              </Button>
                            )}
                          </li>
                        ))}
                      </ul>
                    </details>
                  )}
                  {history.length > 0 && (
                    <details className="text-sm">
                      <summary className="cursor-pointer py-1 font-medium">
                        Anciennes informations
                      </summary>
                      <p className="text-muted-foreground my-3 text-xs">
                        Conservées pour mémoire, elles ne décrivent plus la
                        situation actuelle.
                      </p>
                      <div className="space-y-3">
                        {history.map((entry) => card(entry, false))}
                      </div>
                    </details>
                  )}
                </div>
              </>
            )}
          </div>
        </ScrollArea>
      </SheetContent>
    </Sheet>
  );
}
