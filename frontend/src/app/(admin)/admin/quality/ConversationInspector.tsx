"use client";

import { useEffect, useState } from "react";
import { useSession } from "next-auth/react";
import { toast } from "@/lib/toast";
import { apiFetch } from "@/lib/api";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { AdminLoadError } from "@/components/admin/page-header";
import { Button } from "@/components/ui/button";
import { Play } from "lucide-react";
import {
  InspectorBody,
  type InspectorPayload,
  type RagTrace,
  type CitedSource,
} from "./InspectorBody";

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
  const [error, setError] = useState(false);
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    if (!messageId || !session?.access_token) return;
    let cancelled = false;
    setLoading(true);
    setError(false);
    setData(null);
    apiFetch<MessageInspect>(`/admin/quality/messages/${messageId}/inspect`, {
      token: session.access_token,
    })
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(true);
        console.error(err);
        toast.error("Impossible de charger le détail du message");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [messageId, session?.access_token, retry]);

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        className="flex w-full flex-col overflow-hidden p-0 sm:max-w-3xl"
      >
        <SheetHeader className="px-6 pt-6 pb-2">
          <div className="flex items-start justify-between gap-2">
            <div>
              <SheetTitle>Détail de la conversation</SheetTitle>
              <SheetDescription>
                Question, réponse intégrale, sources et diagnostic technique.
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
                <Play className="mr-1 h-3 w-3" />
                Rejouer
              </Button>
            )}
          </div>
        </SheetHeader>

        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-4">
          {error ? (
            <AdminLoadError
              message="Impossible de charger ce message."
              onRetry={() => setRetry((value) => value + 1)}
            />
          ) : loading || !data ? (
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
