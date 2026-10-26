"use client";

import { ChatWelcomeLayout, ChatWelcomeHeading } from "./chat-welcome-layout";
import {
  BriefcaseBusiness,
  CalendarDays,
  Clock3,
  HeartPulse,
} from "lucide-react";
import { ChatInput, type ChatInputProps } from "@/components/chat/chat-input";
import { useOrg } from "@/lib/org-context";

const defaultSuggestions = [
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

const payrollSuggestions = [
  {
    icon: HeartPulse,
    question:
      "Arrêt maladie : quelles règles de maintien de salaire prévoit la convention collective de cette entreprise ?",
  },
  {
    icon: CalendarDays,
    question:
      "Quels frais professionnels peuvent être remboursés avec une exonération de cotisations, et sous quelles conditions ?",
  },
  {
    icon: BriefcaseBusiness,
    question:
      "Comment vérifier si une prime d’ancienneté est due dans cette entreprise ?",
  },
  {
    icon: Clock3,
    question:
      "Départ d’un salarié : quelles règles de préavis et quelles indemnités faut-il examiner ?",
  },
];

const accountingFirmSuggestions = [
  {
    icon: HeartPulse,
    question:
      "Mon client prépare la paie d’un salarié en arrêt maladie : quelles règles et informations faut-il examiner ?",
  },
  {
    icon: CalendarDays,
    question:
      "Prépare une explication pour mon client sur les conditions d’exonération des remboursements de frais professionnels.",
  },
  {
    icon: BriefcaseBusiness,
    question:
      "Mon client doit-il verser une prime d’ancienneté au regard de sa convention collective ?",
  },
  {
    icon: Clock3,
    question:
      "Mon client prépare le départ d’un salarié : quelles règles et formalités faut-il lui expliquer ?",
  },
];

export function WelcomeScreen(inputProps: ChatInputProps) {
  const { profilMetier } = useOrg();
  const suggestions =
    profilMetier === "comptable_paie"
      ? payrollSuggestions
      : profilMetier === "expert_comptable"
        ? accountingFirmSuggestions
        : defaultSuggestions;

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
