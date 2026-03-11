"use client";

import { useState, useRef, useCallback } from "react";
import { Scale, ArrowUp } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface WelcomeScreenProps {
  onSend: (content: string) => void;
}

const suggestions = [
  "Un salarié en arrêt maladie peut-il être licencié ?",
  "Quelles sont les indemnités dues en cas de rupture conventionnelle ?",
  "Un employeur peut-il refuser une demande de télétravail ?",
  "Quelles sont les obligations lors d'un entretien préalable au licenciement ?",
];

export function WelcomeScreen({ onSend }: WelcomeScreenProps) {
  const [value, setValue] = useState("");
  const [isFocused, setIsFocused] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const handleSend = useCallback(() => {
    const trimmed = value.trim();
    if (!trimmed) return;
    onSend(trimmed);
    setValue("");
  }, [value, onSend]);

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
    <div className="flex flex-1 flex-col items-center justify-center rounded-xl bg-white px-4 dark:bg-card">
      <div className="bg-primary/10 mb-6 flex size-16 items-center justify-center rounded-2xl">
        <Scale className="text-primary size-8" />
      </div>
      <h1 className="text-2xl font-semibold tracking-tight">AORIA RH</h1>
      <p className="text-muted-foreground mt-1 text-base">
        Assistant juridique RH
      </p>
      <p className="text-muted-foreground mt-4 max-w-md text-center text-sm">
        Posez vos questions en droit social français. Je m&apos;appuie sur vos
        documents et la réglementation en vigueur pour vous répondre.
      </p>

      {/* Champ de saisie centré */}
      <div className="mt-8 w-full max-w-2xl">
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
            className="flex-1 resize-none bg-transparent py-0.5 text-base text-foreground placeholder:text-muted-foreground outline-none"
          />
          <Button
            size="icon-sm"
            className="shrink-0 rounded-lg"
            onClick={handleSend}
            disabled={!value.trim()}
          >
            <ArrowUp />
          </Button>
        </div>
      </div>

      {/* Suggestions */}
      <div className="mt-6 grid w-full max-w-2xl grid-cols-1 gap-3 sm:grid-cols-2">
        {suggestions.map((suggestion) => (
          <Button
            key={suggestion}
            variant="outline"
            className="h-auto justify-start whitespace-normal px-4 py-3 text-left text-sm"
            onClick={() => onSend(suggestion)}
          >
            <Scale className="text-muted-foreground mr-2 size-4 shrink-0" />
            {suggestion}
          </Button>
        ))}
      </div>
    </div>
  );
}
