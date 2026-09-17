"use client";

import { useState, useRef, useCallback } from "react";
import { ArrowUp, Loader2, Square, Paperclip, X } from "lucide-react";
import type { ChatDocumentReference } from "@/lib/chat-api";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface ChatInputProps {
  onSend: (content: string) => void;
  disabled?: boolean;
  onStop?: () => void;
  attachments?: ChatDocumentReference[];
  onAttach?: (file: File) => Promise<void>;
  onRemove?: (id: string) => void;
}

export function ChatInput({ onSend, disabled = false, onStop, attachments = [], onAttach, onRemove }: ChatInputProps) {
  const [value, setValue] = useState("");
  const [isFocused, setIsFocused] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const handleSend = useCallback(() => {
    const trimmed = value.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setValue("");
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
    textareaRef.current?.focus();
  }, [value, disabled, onSend]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleInput = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setValue(e.target.value);
    const el = e.target;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  };

  return (
    <div className="px-2 pt-4 sm:px-6">
      <div className="mx-auto max-w-4xl">
        {onAttach && <div className="mb-2 text-xs text-muted-foreground">
          <p>3 pièces actives maximum, 2 Mo par fichier. Les fichiers sont aussi partagés dans les documents de l’entreprise. Retirer une pièce ici ne supprime pas le fichier.</p>
          <p>Lecture du texte extrait : les images et certains éléments de mise en page peuvent manquer.</p>
          <div className="flex flex-wrap gap-2 mt-1">{attachments.map((doc) =>
            <span key={doc.document_id} className="flex items-center gap-1 rounded border px-2 py-1">
              {doc.name || "Document joint"}
              <button aria-label={`Retirer ${doc.name || "le document"}`} disabled={disabled} onClick={() => onRemove?.(doc.document_id)}><X className="size-3" /></button>
            </span>)}</div>
        </div>}
        <div
          data-slot="chat-input"
          className={cn(
            "flex min-h-[3.5rem] items-end gap-2 rounded-xl border bg-white px-4 py-3 shadow-sm transition-[color,box-shadow] dark:bg-card",
            isFocused
              ? "border-ring ring-ring/50 ring-[3px]"
              : "border-input",
          )}
        >
          {onAttach && <>
            <input ref={fileRef} type="file" hidden accept=".pdf,.docx,.txt" onChange={async (event) => {
              const file = event.target.files?.[0];
              event.target.value = "";
              if (file) await onAttach(file);
            }} />
            <Button type="button" variant="ghost" size="icon-sm" aria-label="Joindre un document" disabled={disabled || attachments.length >= 3} onClick={() => fileRef.current?.click()}><Paperclip /></Button>
          </>}
          <textarea
            ref={textareaRef}
            value={value}
            onChange={handleInput}
            onKeyDown={handleKeyDown}
            onFocus={() => setIsFocused(true)}
            onBlur={() => setIsFocused(false)}
            placeholder="Posez votre question ou indiquez quoi faire avec vos documents..."
            rows={1}
            disabled={disabled}
            className="flex-1 resize-none bg-transparent py-0.5 text-base text-foreground placeholder:text-muted-foreground outline-none disabled:cursor-not-allowed disabled:opacity-50"
          />
          {disabled && onStop ? (
            <Button
              size="icon-sm"
              variant="destructive"
              className="shrink-0 rounded-lg"
              onClick={onStop}
              aria-label="Arrêter la génération"
            >
              <Square className="size-3.5" />
            </Button>
          ) : (
            <Button
              size="icon-sm"
              className="shrink-0 rounded-lg"
              onClick={handleSend}
              disabled={disabled || !value.trim()}
            >
              {disabled ? (
                <Loader2 className="animate-spin" />
              ) : (
                <ArrowUp />
              )}
            </Button>
          )}
        </div>
        <p className="text-muted-foreground mt-2 text-center text-xs">
          Aoria RH est une IA et peut faire des erreurs. Vérifiez les informations importantes.
        </p>
      </div>
    </div>
  );
}
