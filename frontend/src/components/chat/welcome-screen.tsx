"use client";

import Image from "next/image";
import {
  BriefcaseBusiness,
  HeartPulse,
  House,
  Scale,
} from "lucide-react";
import { ChatInput, type ChatInputProps } from "@/components/chat/chat-input";

const suggestions = [
  {
    icon: HeartPulse,
    question: "Un salarié en arrêt maladie peut-il être licencié ?",
  },
  {
    icon: BriefcaseBusiness,
    question:
      "Quelles sont les indemnités dues en cas de rupture conventionnelle ?",
  },
  {
    icon: House,
    question: "Un employeur peut-il refuser une demande de télétravail ?",
  },
  {
    icon: Scale,
    question:
      "Quelles sont les obligations lors d'un entretien préalable au licenciement ?",
  },
];

export function WelcomeScreen(inputProps: ChatInputProps) {
  return (
    <section
      aria-labelledby="chat-welcome-title"
      className="dark:bg-card flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl bg-white"
    >
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="flex min-h-full flex-col items-center px-4 py-8 sm:px-8 sm:py-12 lg:py-14">
          <div className="my-auto w-full max-w-3xl">
            <div className="mb-7 text-center sm:mb-9">
              <div className="border-primary/10 bg-card text-muted-foreground mb-5 inline-flex items-center gap-2.5 rounded-full border px-3.5 py-2 text-xs font-medium">
                <Image
                  src="/icon-aoria-dark.svg"
                  alt=""
                  width={22}
                  height={22}
                  priority
                  className="dark:hidden"
                />
                <Image
                  src="/icon-aoria-white.svg"
                  alt=""
                  width={22}
                  height={22}
                  priority
                  className="hidden dark:block"
                />
                AORIA RH · Votre assistant juridique
              </div>
              <h1
                id="chat-welcome-title"
                className="text-3xl leading-tight font-semibold tracking-tight text-balance sm:text-4xl lg:text-[2.625rem]"
              >
                Une question en droit social ?
              </h1>
              <p className="text-muted-foreground mx-auto mt-4 max-w-xl text-sm leading-relaxed text-pretty sm:text-base">
                Une situation à comprendre, une décision à préparer ?{" "}
                <br className="hidden sm:block" />
                Explorez le droit social à partir de vos documents et des textes
                applicables.
              </p>
            </div>
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
                    <Icon aria-hidden="true" className="text-primary mt-0.5 size-4 shrink-0" />
                    <span className="min-w-0 text-sm leading-5">{question}</span>
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>
      <p className="text-muted-foreground shrink-0 pl-4 pr-16 pt-4 pb-3 text-center text-[11px] leading-relaxed sm:px-8">
        Les réponses d’AORIA RH vous accompagnent dans votre analyse et restent
        à vérifier selon votre situation.
      </p>
    </section>
  );
}
