"use client";

import { useParams, useSearchParams } from "next/navigation";
import { Conversation } from "@/components/chat/conversation";

export default function ConversationPage() {
  const { conversationId } = useParams<{ conversationId: string }>();
  const searchParams = useSearchParams();
  return <Conversation key={conversationId} conversationId={conversationId}
    initialQuery={searchParams.get("q")}
    onInitialQueryStarted={() => window.history.replaceState({}, "", `/chat/${conversationId}`)} />;
}
