import type { ComponentProps } from "react";

import { cn } from "@/lib/utils";
import styles from "./chat-markdown-table.module.css";

type ChatMarkdownTableProps = ComponentProps<"table"> & { node?: unknown };

/** Tableau Markdown partagé par la réponse en streaming et la réponse finale. */
export function ChatMarkdownTable({
  node,
  className,
  ...props
}: ChatMarkdownTableProps) {
  void node;

  return (
    <div className={styles.wrapper} data-chat-table>
      <table {...props} className={cn(styles.table, className)} />
    </div>
  );
}
