"use client";

import Image from "next/image";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/** Shared welcome surface for free questions and project conversations. */
export function ChatWelcomeLayout({
  children,
  header,
  verticallyCentered = true,
  compact = false,
}: {
  children: ReactNode;
  header?: ReactNode;
  verticallyCentered?: boolean;
  compact?: boolean;
}) {
  return (
    <section
      aria-labelledby="chat-welcome-title"
      className="dark:bg-card flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl bg-white"
    >
      {header && (
        <div className="flex shrink-0 items-center justify-between px-4 pt-4 sm:px-6">
          {header}
        </div>
      )}
      <div className="min-h-0 flex-1 overflow-y-auto [scrollbar-gutter:stable]">
        <div
          className={cn(
            "flex min-h-full flex-col items-center px-3 sm:px-8",
            compact ? "py-4 sm:py-8 lg:py-10" : "py-5 sm:py-12 lg:py-14"
          )}
        >
          <div
            className={cn("w-full max-w-3xl", verticallyCentered && "my-auto")}
          >
            {children}
          </div>
        </div>
      </div>
      <p className="text-muted-foreground shrink-0 px-3 pt-2 pb-3 text-center text-[11px] leading-relaxed sm:px-8">
        Les réponses d’AORIA RH vous accompagnent dans votre analyse et restent
        à vérifier selon votre situation.
      </p>
    </section>
  );
}

export function ChatWelcomeHeading({
  title,
  description,
  badge = "AORIA RH · Votre assistant juridique",
  compact = false,
}: {
  title: ReactNode;
  description: ReactNode;
  badge?: ReactNode;
  compact?: boolean;
}) {
  return (
    <div
      className={cn("text-center", compact ? "mb-5 sm:mb-6" : "mb-7 sm:mb-9")}
    >
      <div
        className={cn(
          "border-primary/10 bg-card text-muted-foreground inline-flex max-w-full items-center gap-2.5 rounded-full border px-3.5 py-2 text-xs font-medium",
          compact ? "mb-4" : "mb-5"
        )}
      >
        <Image
          src="/icon-aoria-dark.svg"
          alt=""
          width={22}
          height={22}
          priority
          className="shrink-0 dark:hidden"
        />
        <Image
          src="/icon-aoria-white.svg"
          alt=""
          width={22}
          height={22}
          priority
          className="hidden shrink-0 dark:block"
        />
        <span className="min-w-0 truncate">{badge}</span>
      </div>
      <h1
        id="chat-welcome-title"
        className="text-3xl leading-tight font-semibold tracking-tight text-balance break-words sm:text-4xl lg:text-[2.625rem]"
      >
        {title}
      </h1>
      <p
        className={cn(
          "text-muted-foreground mx-auto max-w-xl text-sm leading-relaxed text-pretty sm:text-base",
          compact ? "mt-3" : "mt-4"
        )}
      >
        {description}
      </p>
    </div>
  );
}
