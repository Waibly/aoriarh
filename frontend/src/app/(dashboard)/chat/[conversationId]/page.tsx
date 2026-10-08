"use client";

import { useEffect, useRef, useState } from "react";
import { useParams, useSearchParams } from "next/navigation";
import { Conversation } from "@/components/chat/conversation";

export default function ConversationPage() {
  const { conversationId } = useParams<{ conversationId: string }>();
  const searchParams = useSearchParams();
  const [initial, setInitial] = useState<{
    id: string;
    query: string | null;
  } | null>(null);
  const initialized = useRef<string | null>(null);
  useEffect(() => {
    if (initialized.current === conversationId) return;
    initialized.current = conversationId;
    setInitial({
      id: conversationId,
      query:
        sessionStorage.getItem(`chat-initial:${conversationId}`) ||
        searchParams.get("q"),
    });
  }, [conversationId, searchParams]);
  if (!initial || initial.id !== conversationId)
    return <p role="status">Ouverture de la conversation…</p>;
  return (
    <Conversation
      key={conversationId}
      conversationId={conversationId}
      initialQuery={initial.query}
      onInitialQueryStarted={() => {
        sessionStorage.removeItem(`chat-initial:${conversationId}`);
        window.history.replaceState(
          window.history.state,
          "",
          `/chat/${conversationId}`
        );
      }}
    />
  );
}
