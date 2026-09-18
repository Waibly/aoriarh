"use client";

import Image from "next/image";
import { Scale } from "lucide-react";
import { ChatInput, type ChatInputProps } from "@/components/chat/chat-input";

const suggestions = [
  "Un salarié en arrêt maladie peut-il être licencié ?",
  "Quelles sont les indemnités dues en cas de rupture conventionnelle ?",
  "Un employeur peut-il refuser une demande de télétravail ?",
  "Quelles sont les obligations lors d'un entretien préalable au licenciement ?",
];

export function WelcomeScreen(inputProps: ChatInputProps) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center rounded-xl bg-white px-4 dark:bg-card animate-in fade-in duration-500">
      <div className="mb-6">
        <Image src="/icon-aoria-dark.svg" alt="AORIA RH" width={48} height={48} priority className="dark:hidden" />
        <Image src="/icon-aoria-white.svg" alt="AORIA RH" width={48} height={48} priority className="hidden dark:block" />
      </div>
      <h1 className="text-2xl font-semibold tracking-tight">AORIA RH</h1>
      <p className="text-muted-foreground mt-1 text-base">Assistant juridique RH</p>
      <p className="text-muted-foreground mt-4 max-w-md text-center text-sm">
        Posez vos questions en droit social français. Je m&apos;appuie sur vos
        documents et la réglementation en vigueur pour vous répondre.
      </p>
      <div className="mt-8 w-full max-w-3xl">
        <ChatInput {...inputProps} />
      </div>
      <div className="mt-6 grid w-full max-w-2xl grid-cols-1 gap-3 sm:grid-cols-2">
        {suggestions.map((suggestion) => (
          <button key={suggestion} disabled={inputProps.disabled}
            className="flex items-start gap-2 rounded-xl bg-[#652bb0]/10 px-4 py-3 text-left text-sm text-foreground transition-colors hover:bg-[#652bb0]/20 disabled:opacity-50"
            onClick={() => void inputProps.onSend(suggestion)}>
            <Scale className="mt-0.5 size-4 shrink-0" />
            {suggestion}
          </button>
        ))}
      </div>
    </div>
  );
}
