"use client";

import { ChatWelcomeLayout, ChatWelcomeHeading } from "./chat-welcome-layout";
import {
  BriefcaseBusiness,
  CalendarDays,
  Clock3,
  HeartPulse,
} from "lucide-react";
import { ChatInput, type ChatInputProps } from "@/components/chat/chat-input";

const suggestions = [
  {
    icon: CalendarDays,
    question:
      "Entretiens professionnels : que vérifier avant le 1er octobre 2026 ?",
  },
  {
    icon: HeartPulse,
    question:
      "Un ancien salarié peut-il réclamer des congés acquis pendant un arrêt maladie ?",
  },
  {
    icon: BriefcaseBusiness,
    question:
      "Rupture conventionnelle : quels droits au chômage depuis septembre 2026 ?",
  },
  {
    icon: Clock3,
    question: "Faut-il payer des heures supplémentaires non autorisées ?",
  },
];

export function WelcomeScreen(inputProps: ChatInputProps) {
  return (
    <ChatWelcomeLayout>
      <ChatWelcomeHeading
        title="Une question en droit social ?"
        description={
          <>
            Une situation à comprendre, une décision à préparer ?{" "}
            <br className="hidden sm:block" />
            Explorez le droit social à partir de vos documents et des textes
            applicables.
          </>
        }
      />
      <ChatInput {...inputProps} variant="welcome" />
      <div className="mt-8">
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {suggestions.map(({ icon: Icon, question }) => (
            <button
              key={question}
              type="button"
              disabled={inputProps.disabled}
              className="bg-primary/8 hover:border-primary/20 hover:bg-primary/12 focus-visible:outline-ring flex items-start gap-2.5 rounded-xl border border-transparent px-3 py-2.5 text-left transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
              onClick={() => void inputProps.onSend(question)}
            >
              <Icon
                aria-hidden="true"
                className="text-primary mt-0.5 size-4 shrink-0"
              />
              <span className="min-w-0 text-sm leading-5">{question}</span>
            </button>
          ))}
        </div>
      </div>
    </ChatWelcomeLayout>
  );
}
