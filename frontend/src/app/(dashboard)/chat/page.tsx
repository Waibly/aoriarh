"use client";

import { useRouter } from "next/navigation";
import { useSession } from "next-auth/react";
import { NewConversation } from "@/components/chat/new-conversation";
import { NoOrgWelcome } from "@/components/chat/no-org-welcome";
import { useOrg } from "@/lib/org-context";

export default function ChatPage() {
  const router = useRouter();
  const { data: session } = useSession();
  const { currentOrg, organisations, loading } = useOrg();
  if (!loading && organisations.length === 0) return <NoOrgWelcome />;
  return <NewConversation key={`${session?.user?.email}:${currentOrg?.id}`}
    organisationId={currentOrg?.id} token={session?.access_token}
    onSaved={(id) => router.replace(`/chat/${id}`)} />;
}
