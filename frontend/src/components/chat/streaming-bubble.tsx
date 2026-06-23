"use client";

import { useMemo, type ComponentProps } from "react";
import ReactMarkdown from "react-markdown";
import rehypeSanitize from "rehype-sanitize";
import remarkGfm from "remark-gfm";
import { MessageSources } from "./message-sources";
import {
  LegalRefAnchor,
  SourceViewerProvider,
} from "./source-viewer-context";
import { buildRefIndex } from "@/lib/legal-refs";
import { rehypeLegalRefs } from "@/lib/legal-refs/rehype-legal-refs";
import type { MessageSource } from "@/types/api";

const MD_COMPONENTS = { a: LegalRefAnchor };

interface StreamingBubbleProps {
  content: string;
  sources?: MessageSource[] | null;
}

export function StreamingBubble({ content, sources }: StreamingBubbleProps) {
  const safeSources = useMemo(() => sources ?? [], [sources]);
  const rehypePlugins = useMemo<
    ComponentProps<typeof ReactMarkdown>["rehypePlugins"]
  >(
    () => [
      [rehypeLegalRefs, { index: buildRefIndex(safeSources) }],
      rehypeSanitize,
    ],
    [safeSources],
  );

  return (
    <SourceViewerProvider sources={safeSources}>
      <div className="flex w-full min-w-0 flex-col items-start">
        <div className="w-full min-w-0">
          <div className="prose prose-sm dark:prose-invert max-w-none break-words text-[0.9375rem] leading-7 text-foreground [&_h1]:mt-6 [&_h1]:mb-3 [&_h1]:text-lg [&_h1]:font-bold [&_h1]:text-foreground [&_h2]:mt-6 [&_h2]:mb-3 [&_h2]:text-[1.0625rem] [&_h2]:font-bold [&_h2]:text-foreground [&_h3]:mt-5 [&_h3]:mb-2 [&_h3]:text-base [&_h3]:font-bold [&_h3]:text-foreground [&_p]:my-3 [&_p]:leading-7 [&_a]:text-primary [&_a]:underline-offset-2 [&_strong]:font-semibold [&_strong]:text-foreground [&_ul]:my-3 [&_ul]:pl-5 [&_ul]:list-disc [&_ol]:my-3 [&_ol]:pl-5 [&_ol]:list-decimal [&_li]:my-0.5 [&_li]:leading-7 [&_li::marker]:text-foreground/70 [&_pre]:overflow-x-auto [&_table]:block [&_table]:overflow-x-auto [&>*:first-child]:mt-0 [&>*:last-child]:mb-0">
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              rehypePlugins={rehypePlugins}
              components={MD_COMPONENTS}
            >
              {content}
            </ReactMarkdown>
            <span className="ml-0.5 inline-block h-4 w-1.5 animate-pulse rounded-sm bg-[#652bb0]" />
          </div>
          {safeSources.length > 0 && <MessageSources sources={safeSources} />}
        </div>
      </div>
    </SourceViewerProvider>
  );
}
