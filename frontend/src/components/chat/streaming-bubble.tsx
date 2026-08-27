"use client";

import { useMemo, type ComponentProps } from "react";
import ReactMarkdown from "react-markdown";
import rehypeSanitize from "rehype-sanitize";
import remarkGfm from "remark-gfm";
import { MessageSources } from "./message-sources";
import { ChatMarkdownTable } from "./chat-markdown-table";
import { LegalRefAnchor, SourceViewerProvider } from "./source-viewer-context";
import { buildRefIndex } from "@/lib/legal-refs";
import { rehypeLegalRefs } from "@/lib/legal-refs/rehype-legal-refs";
import type { MessageSource } from "@/types/api";

const MD_COMPONENTS = { a: LegalRefAnchor, table: ChatMarkdownTable };

interface StreamingBubbleProps {
  content: string;
  sources?: MessageSource[] | null;
  /** Affiche le curseur clignotant. Défaut true (comportement chat inchangé) ;
   *  passer false pour une réponse déjà terminée (réutilisation hors streaming). */
  streaming?: boolean;
}

export function StreamingBubble({
  content,
  sources,
  streaming = true,
}: StreamingBubbleProps) {
  const safeSources = useMemo(() => sources ?? [], [sources]);
  const rehypePlugins = useMemo<
    ComponentProps<typeof ReactMarkdown>["rehypePlugins"]
  >(
    () => [
      [rehypeLegalRefs, { index: buildRefIndex(safeSources) }],
      rehypeSanitize,
    ],
    [safeSources]
  );

  return (
    <SourceViewerProvider sources={safeSources}>
      <div className="flex w-full min-w-0 flex-col items-start">
        <div className="w-full min-w-0">
          <div className="prose prose-sm dark:prose-invert text-foreground [&_h1]:text-foreground [&_h2]:text-foreground [&_h3]:text-foreground [&_a]:text-primary [&_strong]:text-foreground [&_li::marker]:text-foreground/70 max-w-none text-[0.9375rem] leading-7 break-words [&_a]:underline-offset-2 [&_h1]:mt-6 [&_h1]:mb-3 [&_h1]:text-lg [&_h1]:font-bold [&_h2]:mt-6 [&_h2]:mb-3 [&_h2]:text-[1.0625rem] [&_h2]:font-bold [&_h3]:mt-5 [&_h3]:mb-2 [&_h3]:text-base [&_h3]:font-bold [&_li]:my-0.5 [&_li]:leading-7 [&_ol]:my-3 [&_ol]:list-decimal [&_ol]:pl-5 [&_p]:my-3 [&_p]:leading-7 [&_pre]:overflow-x-auto [&_strong]:font-semibold [&_ul]:my-3 [&_ul]:list-disc [&_ul]:pl-5 [&>*:first-child]:mt-0 [&>*:last-child]:mb-0">
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              rehypePlugins={rehypePlugins}
              components={MD_COMPONENTS}
            >
              {content}
            </ReactMarkdown>
            {streaming && (
              <span className="ml-0.5 inline-block h-4 w-1.5 animate-pulse rounded-sm bg-[#652bb0]" />
            )}
          </div>
          {safeSources.length > 0 && (
            <MessageSources
              sources={safeSources}
              answer={streaming ? "" : content}
            />
          )}
        </div>
      </div>
    </SourceViewerProvider>
  );
}
