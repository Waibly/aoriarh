"use client";

import { useState, useRef, useCallback } from "react";
import { ArrowUp, Loader2, Square } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface ChatInputProps {
  onSend: (content: string) => void;
  disabled?: boolean;
  onStop?: () => void;
}

export function ChatInput({ onSend, disabled = false, onStop }: ChatInputProps) {
  const [value, setValue] = useState("");
  const [isFocused, setIsFocused] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

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
        <div
          data-slot="chat-input"
          className={cn(
            "flex min-h-[3.5rem] items-end gap-2 rounded-xl border bg-white px-4 py-3 shadow-sm transition-[color,box-shadow] dark:bg-card",
            isFocused
              ? "border-ring ring-ring/50 ring-[3px]"
              : "border-input",
          )}
        >
          <textarea
            ref={textareaRef}
            value={value}
            onChange={handleInput}
            onKeyDown={handleKeyDown}
            onFocus={() => setIsFocused(true)}
            onBlur={() => setIsFocused(false)}
            placeholder="Posez votre question juridique..."
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
