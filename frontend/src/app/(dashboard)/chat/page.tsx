"use client";

import { useRouter } from "next/navigation";
import { useCallback } from "react";
import { useSession } from "next-auth/react";
import { WelcomeScreen } from "@/components/chat/welcome-screen";
import { useOrg } from "@/lib/org-context";
import { createConversation } from "@/lib/chat-api";

export default function ChatPage() {
  const router = useRouter();
  const { data: session } = useSession();
  const { currentOrg } = useOrg();

  const handleSend = useCallback(
    async (content: string) => {
      const token = session?.access_token;
      if (!token || !currentOrg) return;

      try {
        const conversation = await createConversation(
          currentOrg.id,
          token,
        );
        router.push(
          `/chat/${conversation.id}?q=${encodeURIComponent(content)}`,
        );
      } catch {
        // Fallback: navigate without creating conversation
        router.push(`/chat/new?q=${encodeURIComponent(content)}`);
      }
    },
    [session, currentOrg, router],
  );

  return <WelcomeScreen onSend={handleSend} />;
}
