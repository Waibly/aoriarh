"use client";

import { useState, useRef, useCallback, useEffect } from "react";
import {
  ArrowUp,
  Loader2,
  Square,
  Paperclip,
  Plus,
  FolderOpen,
  FileText,
  X,
  ChevronRight,
} from "lucide-react";
import type { ChatDocumentReference } from "@/lib/chat-api";
import { effectiveAttachments } from "@/lib/chat-attachments";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";

export interface ChatInputProps {
  variant?: "default" | "welcome";
  draftKey?: string;
  placeholder?: string;
  attachmentScope?: "entreprise" | "dossier" | "conversation";
  onAttachmentScopeChange?: (scope: "dossier" | "conversation") => void;
  onSend: (content: string) => void | boolean | Promise<void | boolean>;
  disabled?: boolean;
  onStop?: () => void;
  attachments?: ChatDocumentReference[];
  onAttach?: (file: File) => Promise<void>;
  onBrowse?: () => void;
  onRemove?: (id: string) => void;
}

export function ChatInput({
  onSend,
  disabled = false,
  onStop,
  attachments = [],
  onAttach,
  onBrowse,
  onRemove,
  variant = "default",
  draftKey,
  placeholder,
  attachmentScope = "entreprise",
  onAttachmentScopeChange,
}: ChatInputProps) {
  const [value, setValue] = useState("");
  useEffect(() => {
    if (draftKey)
      setValue(sessionStorage.getItem(`chat-draft:${draftKey}`) || "");
  }, [draftKey]);
  const [menuOpen, setMenuOpen] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const limitReached = attachments.length >= 3;
  const attachmentStates = effectiveAttachments(attachments);

  const handleSend = useCallback(async () => {
    const trimmed = value.trim();
    if (!trimmed || disabled) return;
    if ((await onSend(trimmed)) === false) return;
    setValue("");
    if (draftKey) sessionStorage.removeItem(`chat-draft:${draftKey}`);
    if (textareaRef.current) textareaRef.current.style.height = "auto";
    textareaRef.current?.focus();
  }, [value, disabled, onSend, draftKey]);

  return (
    <div className={cn("w-full", variant === "default" && "px-1 pt-3 sm:px-3")}>
      <div className="mx-auto max-w-3xl">
        <div
          data-slot="chat-input"
          className={cn(
            "border-border/80 focus-within:border-primary/35 dark:bg-card rounded-3xl border bg-white shadow-[0_4px_24px_-12px_rgba(0,0,0,0.18)] transition-[border-color,box-shadow] focus-within:shadow-[0_4px_28px_-12px_rgba(101,43,176,0.16)]",
            variant === "welcome" &&
              "border-primary/20 focus-within:border-primary/50 rounded-2xl shadow-[0_8px_32px_-16px_rgba(101,43,176,0.2)]"
          )}
        >
          {attachments.length > 0 && (
            <div
              className="flex flex-wrap gap-2 px-4 pt-4"
              aria-label="Pièces jointes"
            >
              {attachmentStates.map((doc) => (
                <div
                  key={doc.document_id}
                  className="border-border/70 bg-muted/40 flex max-w-full items-center gap-2.5 rounded-xl border py-2 pr-1.5 pl-2.5"
                >
                  <span className="bg-primary/8 text-primary flex size-8 shrink-0 items-center justify-center rounded-lg">
                    <FileText className="size-4" />
                  </span>
                  <div className="min-w-0">
                    <p
                      className="max-w-44 truncate text-xs font-medium sm:max-w-56"
                      title={doc.name}
                    >
                      {doc.name || "Document joint"}
                    </p>
                    <p
                      className={`mt-0.5 text-[10px] ${doc.effective_processing_status === "error" ? "text-destructive" : "text-muted-foreground"}`}
                    >
                      {doc.effective_processing_status === "preparing"
                        ? "Préparation de la lecture…"
                        : doc.effective_processing_status === "error"
                          ? "Préparation échouée"
                          : doc.effective_reading_mode === "targeted"
                            ? "Document long · lecture ciblée"
                            : "Lu intégralement"}
                    </p>
                  </div>
                  <button
                    type="button"
                    aria-label={`Retirer ${doc.name || "le document"}`}
                    title="Retirer de cette conversation"
                    disabled={disabled}
                    onClick={() => onRemove?.(doc.document_id)}
                    className="text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:outline-ring ml-1 flex size-7 shrink-0 items-center justify-center rounded-full transition-colors focus-visible:outline-2 disabled:opacity-40"
                  >
                    <X className="size-3.5" />
                  </button>
                </div>
              ))}
            </div>
          )}
          <textarea
            ref={textareaRef}
            value={value}
            disabled={disabled}
            rows={2}
            aria-label="Votre message"
            placeholder={
              placeholder ??
              (variant === "welcome"
                ? "Décrivez votre situation ou posez votre question…"
                : "Comment puis-je vous aider ?")
            }
            onChange={(event) => {
              setValue(event.target.value);
              if (draftKey)
                sessionStorage.setItem(
                  `chat-draft:${draftKey}`,
                  event.target.value
                );
              event.target.style.height = "auto";
              event.target.style.height = `${Math.min(event.target.scrollHeight, 200)}px`;
            }}
            onKeyDown={(event) => {
              if (
                event.key === "Enter" &&
                !event.shiftKey &&
                !event.nativeEvent.isComposing
              ) {
                event.preventDefault();
                void handleSend();
              }
            }}
            className="text-foreground placeholder:text-muted-foreground/75 block min-h-20 w-full resize-none border-0 bg-transparent px-5 pt-4 pb-2 text-base leading-relaxed outline-none disabled:cursor-wait sm:text-[15px]"
          />
          <div className="flex items-center justify-between gap-3 px-3 pt-1 pb-3">
            <div className="flex min-h-9 items-center gap-2">
              {(onAttach || onBrowse) && (
                <Popover open={menuOpen} onOpenChange={setMenuOpen}>
                  <PopoverTrigger asChild>
                    <Button
                      type="button"
                      variant="ghost"
                      size={variant === "welcome" ? "sm" : "icon"}
                      aria-label="Ajouter des documents"
                      title="Ajouter des documents"
                      disabled={disabled}
                      className={cn(
                        "text-muted-foreground hover:bg-muted hover:text-foreground h-9 rounded-full focus-visible:ring-2",
                        variant === "welcome" ? "gap-2 px-3 text-xs" : "size-9"
                      )}
                    >
                      <Plus aria-hidden="true" className="size-5" />
                      {variant === "welcome" && (
                        <span>Joindre un document</span>
                      )}
                    </Button>
                  </PopoverTrigger>
                  <PopoverContent
                    align="start"
                    side="top"
                    sideOffset={12}
                    className="w-[330px] max-w-[calc(100vw-2rem)] rounded-2xl p-2 shadow-xl"
                  >
                    {onAttach && onAttachmentScopeChange && (
                      <fieldset className="border-b px-3 pt-2 pb-3">
                        <legend className="text-muted-foreground mb-2 text-xs">
                          Enregistrer le fichier dans
                        </legend>
                        <div className="bg-muted flex gap-1 rounded-lg p-1">
                          {(
                            [
                              ["dossier", "Ce dossier"],
                              ["conversation", "Cet échange"],
                            ] as const
                          ).map(([scope, label]) => (
                            <button
                              key={scope}
                              type="button"
                              disabled={disabled || limitReached}
                              aria-pressed={attachmentScope === scope}
                              onClick={() => onAttachmentScopeChange(scope)}
                              className={cn(
                                "focus-visible:outline-ring flex-1 rounded-md px-2 py-2 text-xs transition-colors focus-visible:outline-2",
                                attachmentScope === scope
                                  ? "bg-background text-foreground shadow-sm"
                                  : "text-muted-foreground hover:text-foreground"
                              )}
                            >
                              {label}
                            </button>
                          ))}
                        </div>
                      </fieldset>
                    )}
                    {onAttach && (
                      <button
                        type="button"
                        disabled={disabled || limitReached}
                        onClick={() => {
                          setMenuOpen(false);
                          fileRef.current?.click();
                        }}
                        className="hover:bg-muted focus-visible:outline-ring flex w-full items-start gap-3 rounded-xl p-3 text-left transition-colors focus-visible:outline-2 disabled:cursor-not-allowed disabled:opacity-40"
                      >
                        <Paperclip className="text-muted-foreground mt-0.5 size-4 shrink-0" />
                        <span>
                          <span className="block text-sm font-medium">
                            Importer un fichier
                          </span>
                          <span className="text-muted-foreground mt-1 block text-xs leading-relaxed">
                            {attachmentScope === "dossier"
                              ? "Réservé aux conversations de ce dossier."
                              : attachmentScope === "conversation"
                                ? "Réservé à cette conversation."
                                : "Ajouté aux documents de l’entreprise."}
                          </span>
                        </span>
                      </button>
                    )}
                    {onBrowse && (
                      <button
                        type="button"
                        disabled={disabled || limitReached}
                        onClick={() => {
                          setMenuOpen(false);
                          onBrowse();
                        }}
                        className="hover:bg-muted focus-visible:outline-ring flex w-full items-start gap-3 rounded-xl p-3 text-left transition-colors focus-visible:outline-2 disabled:cursor-not-allowed disabled:opacity-40"
                      >
                        <FolderOpen className="text-muted-foreground mt-0.5 size-4 shrink-0" />
                        <span>
                          <span className="block text-sm font-medium">
                            Documents de l’entreprise
                          </span>
                          <span className="text-muted-foreground mt-1 block text-xs">
                            Choisir un document déjà enregistré.
                          </span>
                        </span>
                      </button>
                    )}
                    {limitReached && (
                      <p
                        role="status"
                        className="text-muted-foreground px-3 py-2 text-xs"
                      >
                        3 pièces sélectionnées. Retirez-en une pour en ajouter
                        une autre.
                      </p>
                    )}
                    <details className="group text-muted-foreground mt-1 border-t px-3 pt-3 pb-2 text-xs">
                      <summary className="focus-visible:outline-ring flex cursor-pointer list-none items-center justify-between rounded py-1 focus-visible:outline-2">
                        Formats et informations{" "}
                        <ChevronRight className="size-3.5 transition-transform group-open:rotate-90" />
                      </summary>
                      <div className="space-y-2 pt-2 pb-1 leading-relaxed">
                        <p>
                          PDF, Word ou texte · 3 pièces maximum · 2 Mo par
                          fichier importé.
                        </p>
                        <p>
                          {attachmentScope === "dossier"
                            ? "Les fichiers importés restent privés dans ce dossier."
                            : attachmentScope === "conversation"
                              ? "Les fichiers importés restent privés dans cette conversation."
                              : "Les fichiers importés sont enregistrés dans les documents de l’entreprise."}{" "}
                          Retirer une pièce du chat ne supprime pas le fichier.
                        </p>
                        <p>
                          Seul le texte extrait est lu. Les scans, images et
                          certains éléments de mise en page peuvent ne pas être
                          pris en compte.
                        </p>
                      </div>
                    </details>
                  </PopoverContent>
                </Popover>
              )}
              {attachments.length > 0 && (
                <span className="text-muted-foreground text-xs">
                  {attachments.length}/3 pièces
                </span>
              )}
              {disabled && !onStop && (
                <span
                  role="status"
                  className="text-muted-foreground flex items-center gap-2 text-xs"
                >
                  <Loader2 className="size-3.5 animate-spin" /> Préparation…
                </span>
              )}
            </div>
            {disabled && onStop ? (
              <Button
                type="button"
                size="icon"
                variant="secondary"
                onClick={onStop}
                aria-label="Arrêter la génération"
                title="Arrêter"
                className="size-9 shrink-0 rounded-full"
              >
                <Square className="size-3.5 fill-current" />
              </Button>
            ) : (
              <Button
                type="button"
                size="icon"
                onClick={() => void handleSend()}
                disabled={disabled || !value.trim()}
                aria-label="Envoyer le message"
                title="Envoyer"
                className="bg-primary text-primary-foreground disabled:bg-muted disabled:text-muted-foreground size-9 shrink-0 rounded-full shadow-none disabled:opacity-100"
              >
                <ArrowUp className="size-4" />
              </Button>
            )}
          </div>
          {onAttach && (
            <input
              ref={fileRef}
              type="file"
              hidden
              accept=".pdf,.docx,.txt"
              onChange={async (event) => {
                const file = event.target.files?.[0];
                event.target.value = "";
                if (file) await onAttach(file);
              }}
            />
          )}
        </div>
        {variant === "default" && (
          <p className="text-muted-foreground mt-2.5 text-center text-[11px] leading-relaxed">
            Aoria RH peut faire des erreurs. Vérifiez les informations
            importantes.
          </p>
        )}
      </div>
    </div>
  );
}
