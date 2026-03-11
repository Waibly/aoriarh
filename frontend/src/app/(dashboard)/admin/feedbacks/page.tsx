"use client";

import { useCallback, useEffect, useState } from "react";
import { useSession } from "next-auth/react";
import { ThumbsUp, ThumbsDown } from "lucide-react";
import { toast } from "sonner";
import { apiFetch } from "@/lib/api";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { Skeleton } from "@/components/ui/skeleton";

interface FeedbackItem {
  message_id: string;
  user_email: string;
  organisation_name: string;
  question: string;
  answer: string;
  feedback: string;
  feedback_comment: string | null;
  created_at: string;
}

interface FeedbackListResponse {
  items: FeedbackItem[];
  total: number;
  page: number;
  page_size: number;
}

function truncate(text: string, max: number): string {
  if (text.length <= max) return text;
  return text.slice(0, max) + "…";
}

export default function FeedbacksPage() {
  const { data: session } = useSession();
  const token = session?.access_token;

  const [data, setData] = useState<FeedbackListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const PAGE_SIZE = 50;

  const fetchFeedbacks = useCallback(async () => {
    if (!token) return;
    try {
      const res = await apiFetch<FeedbackListResponse>(
        `/admin/feedbacks/?page=${page}&page_size=${PAGE_SIZE}`,
        { token },
      );
      setData(res);
    } catch {
      toast.error("Erreur lors du chargement des feedbacks");
    } finally {
      setLoading(false);
    }
  }, [token, page]);

  useEffect(() => {
    setLoading(true);
    fetchFeedbacks();
  }, [fetchFeedbacks]);

  const totalPages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1;

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold tracking-tight">Avis utilisateurs</h1>

      <Card>
        <CardHeader>
          <CardTitle>Feedbacks</CardTitle>
          <CardDescription>
            {data ? `${data.total} avis au total` : "Chargement…"}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="space-y-3">
              {[1, 2, 3, 4, 5].map((i) => (
                <Skeleton key={i} className="h-12 w-full" />
              ))}
            </div>
          ) : !data || data.items.length === 0 ? (
            <p className="py-8 text-center text-muted-foreground">
              Aucun avis pour le moment.
            </p>
          ) : (
            <>
              <TooltipProvider delayDuration={300}>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Utilisateur</TableHead>
                      <TableHead>Question</TableHead>
                      <TableHead className="w-[30%]">Réponse</TableHead>
                      <TableHead>Avis</TableHead>
                      <TableHead>Commentaire</TableHead>
                      <TableHead>Date</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {data.items.map((item) => (
                      <TableRow key={item.message_id}>
                        <TableCell className="text-sm">
                          <div className="font-medium">{item.user_email}</div>
                          <div className="text-xs text-muted-foreground">
                            {item.organisation_name}
                          </div>
                        </TableCell>
                        <TableCell className="text-sm max-w-[200px]">
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <span className="cursor-default block truncate">
                                {truncate(item.question, 80)}
                              </span>
                            </TooltipTrigger>
                            <TooltipContent side="bottom" className="max-w-md whitespace-pre-wrap">
                              {item.question}
                            </TooltipContent>
                          </Tooltip>
                        </TableCell>
                        <TableCell className="text-sm max-w-[250px]">
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <span className="cursor-default block truncate">
                                {truncate(item.answer, 100)}
                              </span>
                            </TooltipTrigger>
                            <TooltipContent side="bottom" className="max-w-lg max-h-64 overflow-y-auto whitespace-pre-wrap">
                              {item.answer}
                            </TooltipContent>
                          </Tooltip>
                        </TableCell>
                        <TableCell>
                          {item.feedback === "up" ? (
                            <ThumbsUp className="size-4 text-primary" />
                          ) : (
                            <ThumbsDown className="size-4 text-destructive" />
                          )}
                        </TableCell>
                        <TableCell className="text-sm text-muted-foreground max-w-[200px]">
                          {item.feedback_comment ? (
                            <Tooltip>
                              <TooltipTrigger asChild>
                                <span className="cursor-default block truncate">
                                  {truncate(item.feedback_comment, 50)}
                                </span>
                              </TooltipTrigger>
                              <TooltipContent side="bottom" className="max-w-md whitespace-pre-wrap">
                                {item.feedback_comment}
                              </TooltipContent>
                            </Tooltip>
                          ) : (
                            "—"
                          )}
                        </TableCell>
                        <TableCell className="text-sm text-muted-foreground whitespace-nowrap">
                          {new Date(item.created_at).toLocaleDateString("fr-FR", {
                            day: "2-digit",
                            month: "2-digit",
                            year: "numeric",
                            hour: "2-digit",
                            minute: "2-digit",
                          })}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </TooltipProvider>

              {totalPages > 1 && (
                <div className="flex items-center justify-between border-t pt-4 mt-4">
                  <p className="text-sm text-muted-foreground">
                    {(page - 1) * PAGE_SIZE + 1}–{Math.min(page * PAGE_SIZE, data.total)} sur {data.total}
                  </p>
                  <div className="flex items-center gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={page <= 1}
                      onClick={() => setPage((p) => p - 1)}
                    >
                      Précédent
                    </Button>
                    <span className="text-sm text-muted-foreground">
                      {page} / {totalPages}
                    </span>
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={page >= totalPages}
                      onClick={() => setPage((p) => p + 1)}
                    >
                      Suivant
                    </Button>
                  </div>
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
