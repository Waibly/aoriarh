"use client";

import Image from "next/image";
import {
  ArrowUpRight,
  BriefcaseBusiness,
  HeartPulse,
  House,
  Scale,
} from "lucide-react";
import { ChatInput, type ChatInputProps } from "@/components/chat/chat-input";

const suggestions = [
  {
    topic: "Santé & absences",
    icon: HeartPulse,
    question: "Un salarié en arrêt maladie peut-il être licencié ?",
  },
  {
    topic: "Rupture du contrat",
    icon: BriefcaseBusiness,
    question:
      "Quelles sont les indemnités dues en cas de rupture conventionnelle ?",
  },
  {
    topic: "Organisation du travail",
    icon: House,
    question: "Un employeur peut-il refuser une demande de télétravail ?",
  },
  {
    topic: "Procédure de licenciement",
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
            <div className="mt-7 sm:mt-8">
              <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
                {suggestions.map(({ topic, icon: Icon, question }) => (
                  <button
                    key={topic}
                    type="button"
                    disabled={inputProps.disabled}
                    className="group bg-primary/8 hover:border-primary/20 hover:bg-primary/12 focus-visible:outline-ring flex items-start gap-3 rounded-xl border border-transparent p-4 text-left transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
                    onClick={() => void inputProps.onSend(question)}
                  >
                    <span className="bg-primary/7 text-primary flex size-8 shrink-0 items-center justify-center rounded-lg">
                      <Icon aria-hidden="true" className="size-4" />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="text-muted-foreground mb-1.5 block text-[11px] font-medium tracking-wide">
                        {topic}
                      </span>
                      <span className="block text-sm leading-relaxed">
                        {question}
                      </span>
                    </span>
                    <ArrowUpRight
                      aria-hidden="true"
                      className="text-muted-foreground/60 group-hover:text-primary mt-1 size-3.5 shrink-0 transition-colors"
                    />
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
