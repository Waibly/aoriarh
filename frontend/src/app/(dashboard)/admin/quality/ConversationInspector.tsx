"use client";

import { useEffect, useState } from "react";
import { useSession } from "next-auth/react";
import { toast } from "sonner";
import { apiFetch } from "@/lib/api";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { Play } from "lucide-react";
import { InspectorBody, type InspectorPayload, type RagTrace, type CitedSource } from "./InspectorBody";

interface MessageInspect extends InspectorPayload {
  message_id: string;
  conversation_id: string;
}

export function ConversationInspector({
  messageId,
  open,
  onOpenChange,
  onReplayRequest,
}: {
  messageId: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onReplayRequest?: (messageId: string) => void;
}) {
  const { data: session } = useSession();
  const [data, setData] = useState<MessageInspect | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!messageId || !session?.access_token) return;
    setLoading(true);
    setData(null);
    apiFetch<MessageInspect>(
      `/admin/quality/messages/${messageId}/inspect`,
      { token: session.access_token },
    )
      .then((d) => setData(d))
      .catch((err) => {
        console.error(err);
        toast.error("Impossible de charger le détail du message");
      })
      .finally(() => setLoading(false));
  }, [messageId, session?.access_token]);

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="sm:max-w-3xl w-full overflow-hidden flex flex-col p-0">
        <SheetHeader className="px-6 pt-6 pb-2">
          <div className="flex items-start justify-between gap-2">
            <div>
              <SheetTitle>Inspection du message</SheetTitle>
              <SheetDescription>
                Trace complète du pipeline RAG pour cette question.
              </SheetDescription>
            </div>
            {messageId && onReplayRequest && (
              <Button
                size="sm"
                variant="outline"
                onClick={() => {
                  onReplayRequest(messageId);
                  onOpenChange(false);
                }}
              >
                <Play className="h-3 w-3 mr-1" />
                Rejouer
              </Button>
            )}
          </div>
        </SheetHeader>

        <div className="flex-1 min-h-0 overflow-y-auto px-6 py-4">
          {loading || !data ? (
            <div className="space-y-3">
              <Skeleton className="h-20 w-full" />
              <Skeleton className="h-32 w-full" />
              <Skeleton className="h-40 w-full" />
            </div>
          ) : (
            <InspectorBody data={data} />
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}

// Re-export types for consumers
export type { InspectorPayload, RagTrace, CitedSource };
