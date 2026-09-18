"use client";

import { useState, useRef, useCallback } from "react";
import { ArrowUp, Loader2, Square, Paperclip, Plus, FolderOpen, FileText, X, ChevronRight } from "lucide-react";
import type { ChatDocumentReference } from "@/lib/chat-api";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";

export interface ChatInputProps {
  onSend: (content: string) => void | boolean | Promise<void | boolean>;
  disabled?: boolean;
  onStop?: () => void;
  attachments?: ChatDocumentReference[];
  onAttach?: (file: File) => Promise<void>;
  onBrowse?: () => void;
  onRemove?: (id: string) => void;
}

export function ChatInput({ onSend, disabled = false, onStop, attachments = [], onAttach, onBrowse, onRemove }: ChatInputProps) {
  const [value, setValue] = useState("");
  const [menuOpen, setMenuOpen] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const limitReached = attachments.length >= 3;

  const handleSend = useCallback(async () => {
    const trimmed = value.trim();
    if (!trimmed || disabled) return;
    if (await onSend(trimmed) === false) return;
    setValue("");
    if (textareaRef.current) textareaRef.current.style.height = "auto";
    textareaRef.current?.focus();
  }, [value, disabled, onSend]);

  return (
    <div className="w-full px-1 pt-3 sm:px-3">
      <div className="mx-auto max-w-3xl">
        <div data-slot="chat-input"
          className="rounded-3xl border border-border/80 bg-white shadow-[0_4px_24px_-12px_rgba(0,0,0,0.18)] transition-[border-color,box-shadow] focus-within:border-primary/35 focus-within:shadow-[0_4px_28px_-12px_rgba(101,43,176,0.16)] dark:bg-card">
          {attachments.length > 0 && <div className="flex flex-wrap gap-2 px-4 pt-4" aria-label="Pièces jointes">
            {attachments.map((doc) => <div key={doc.document_id}
              className="flex max-w-full items-center gap-2.5 rounded-xl border border-border/70 bg-muted/40 py-2 pl-2.5 pr-1.5">
              <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary/8 text-primary"><FileText className="size-4" /></span>
              <div className="min-w-0">
                <p className="max-w-44 truncate text-xs font-medium sm:max-w-56" title={doc.name}>{doc.name || "Document joint"}</p>
                <p className="mt-0.5 text-[10px] text-muted-foreground">Document joint</p>
              </div>
              <button type="button" aria-label={`Retirer ${doc.name || "le document"}`}
                title="Retirer de cette conversation" disabled={disabled} onClick={() => onRemove?.(doc.document_id)}
                className="ml-1 flex size-7 shrink-0 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-2 focus-visible:outline-ring disabled:opacity-40">
                <X className="size-3.5" />
              </button>
            </div>)}
          </div>}
          <textarea ref={textareaRef} value={value} disabled={disabled} rows={2}
            aria-label="Votre message" placeholder="Comment puis-je vous aider ?"
            onChange={(event) => {
              setValue(event.target.value);
              event.target.style.height = "auto";
              event.target.style.height = `${Math.min(event.target.scrollHeight, 200)}px`;
            }}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                event.preventDefault();
                void handleSend();
              }
            }}
            className="block min-h-20 w-full resize-none border-0 bg-transparent px-5 pb-2 pt-4 text-base leading-relaxed text-foreground outline-none placeholder:text-muted-foreground/75 disabled:cursor-wait sm:text-[15px]" />
          <div className="flex items-center justify-between gap-3 px-3 pb-3 pt-1">
            <div className="flex min-h-9 items-center gap-2">
              {(onAttach || onBrowse) && <Popover open={menuOpen} onOpenChange={setMenuOpen}>
                <PopoverTrigger asChild>
                  <Button type="button" variant="ghost" size="icon" aria-label="Ajouter des documents"
                    title="Ajouter des documents" disabled={disabled}
                    className="size-9 rounded-full text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:ring-2">
                    <Plus className="size-5" />
                  </Button>
                </PopoverTrigger>
                <PopoverContent align="start" side="top" sideOffset={12}
                  className="w-[330px] max-w-[calc(100vw-2rem)] rounded-2xl p-2 shadow-xl">
                  {onAttach && <button type="button" disabled={disabled || limitReached}
                    onClick={() => { setMenuOpen(false); fileRef.current?.click(); }}
                    className="flex w-full items-start gap-3 rounded-xl p-3 text-left transition-colors hover:bg-muted focus-visible:outline-2 focus-visible:outline-ring disabled:cursor-not-allowed disabled:opacity-40">
                    <Paperclip className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
                    <span><span className="block text-sm font-medium">Importer un fichier</span>
                      <span className="mt-1 block text-xs leading-relaxed text-muted-foreground">Ajouté aux documents de l’entreprise.</span></span>
                  </button>}
                  {onBrowse && <button type="button" disabled={disabled || limitReached}
                    onClick={() => { setMenuOpen(false); onBrowse(); }}
                    className="flex w-full items-start gap-3 rounded-xl p-3 text-left transition-colors hover:bg-muted focus-visible:outline-2 focus-visible:outline-ring disabled:cursor-not-allowed disabled:opacity-40">
                    <FolderOpen className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
                    <span><span className="block text-sm font-medium">Documents de l’entreprise</span>
                      <span className="mt-1 block text-xs text-muted-foreground">Choisir un document déjà enregistré.</span></span>
                  </button>}
                  {limitReached && <p role="status" className="px-3 py-2 text-xs text-muted-foreground">3 pièces sélectionnées. Retirez-en une pour en ajouter une autre.</p>}
                  <details className="group mt-1 border-t px-3 pb-2 pt-3 text-xs text-muted-foreground">
                    <summary className="flex cursor-pointer list-none items-center justify-between rounded py-1 focus-visible:outline-2 focus-visible:outline-ring">
                      Formats et informations <ChevronRight className="size-3.5 transition-transform group-open:rotate-90" />
                    </summary>
                    <div className="space-y-2 pb-1 pt-2 leading-relaxed">
                      <p>PDF, Word ou texte · 3 pièces maximum · 2 Mo par fichier importé.</p>
                      <p>Les fichiers importés sont enregistrés dans les documents de l’entreprise. Retirer une pièce du chat ne supprime pas le fichier.</p>
                      <p>Seul le texte extrait est lu. Les scans, images et certains éléments de mise en page peuvent ne pas être pris en compte.</p>
                    </div>
                  </details>
                </PopoverContent>
              </Popover>}
              {attachments.length > 0 && <span className="text-xs text-muted-foreground">{attachments.length}/3 pièces</span>}
              {disabled && !onStop && <span role="status" className="flex items-center gap-2 text-xs text-muted-foreground"><Loader2 className="size-3.5 animate-spin" /> Préparation…</span>}
            </div>
            {disabled && onStop ?
              <Button type="button" size="icon" variant="secondary" onClick={onStop} aria-label="Arrêter la génération" title="Arrêter"
                className="size-9 shrink-0 rounded-full"><Square className="size-3.5 fill-current" /></Button> :
              <Button type="button" size="icon" onClick={() => void handleSend()} disabled={disabled || !value.trim()}
                aria-label="Envoyer le message" title="Envoyer"
                className="size-9 shrink-0 rounded-full bg-primary text-primary-foreground shadow-none disabled:bg-muted disabled:text-muted-foreground disabled:opacity-100">
                <ArrowUp className="size-4" />
              </Button>}
          </div>
          {onAttach && <input ref={fileRef} type="file" hidden accept=".pdf,.docx,.txt" onChange={async (event) => {
            const file = event.target.files?.[0];
            event.target.value = "";
            if (file) await onAttach(file);
          }} />}
        </div>
        <p className="mt-2.5 text-center text-[11px] leading-relaxed text-muted-foreground/80">
          Aoria RH peut faire des erreurs. Vérifiez les informations importantes.
        </p>
      </div>
    </div>
  );
}
