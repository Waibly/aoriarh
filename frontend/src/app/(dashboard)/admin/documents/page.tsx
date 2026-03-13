"use client";

import { useCallback, useEffect, useState } from "react";
import { useSession } from "next-auth/react";
import {
  CheckCircle,
  FileText,
  HardDrive,
  Loader2,
  RefreshCw,
} from "lucide-react";
import { toast } from "sonner";
import { apiFetch } from "@/lib/api";
import { SOURCE_TYPE_OPTIONS } from "@/types/api";
import {
  Card,
  CardContent,
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
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";

interface AdminDocument {
  id: string;
  organisation_id: string | null;
  organisation_name: string | null;
  name: string;
  source_type: string;
  norme_niveau: number | null;
  indexation_status: string;
  indexation_duration_ms: number | null;
  file_size: number | null;
  file_format: string | null;
  created_at: string;
}

interface StorageStats {
  total_documents: number;
  indexed_count: number;
  pending_count: number;
  indexing_count: number;
  error_count: number;
  total_storage_bytes: number;
  common_documents: number;
  org_documents: number;
}

const STATUS_CLASSES: Record<string, string> = {
  pending: "rounded-full",
  indexing: "rounded-full border-orange-400 bg-orange-500/10 text-orange-600 dark:text-orange-400",
  indexed: "rounded-full border-green-500 bg-green-500/10 text-green-600 dark:text-green-400",
  error: "rounded-full border-red-500 bg-red-500/10 text-red-600 dark:text-red-400",
};

const STATUS_LABEL: Record<string, string> = {
  pending: "En attente",
  indexing: "En cours",
  indexed: "Indexé",
  error: "Erreur",
};

function formatFileSize(bytes: number | null): string {
  if (!bytes) return "—";
  if (bytes < 1024) return `${bytes} o`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} Ko`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} Mo`;
}

function formatDuration(ms: number | null): string {
  if (ms === null) return "—";
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.floor(ms / 60000)}m${Math.round((ms % 60000) / 1000)}s`;
}

export default function AdminDocumentsPage() {
  const { data: session } = useSession();
  const token = session?.access_token;

  const [documents, setDocuments] = useState<AdminDocument[]>([]);
  const [stats, setStats] = useState<StorageStats | null>(null);
  const [loading, setLoading] = useState(false);

  const fetchDocuments = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    try {
      const docs = await apiFetch<AdminDocument[]>("/admin/documents/all", {
        token,
      });
      setDocuments(docs);
    } catch {
      toast.error("Erreur lors du chargement des documents");
    } finally {
      setLoading(false);
    }
  }, [token]);

  const fetchStats = useCallback(async () => {
    if (!token) return;
    try {
      const data = await apiFetch<StorageStats>("/admin/documents/stats", {
        token,
      });
      setStats(data);
    } catch {
      // Non critique
    }
  }, [token]);

  useEffect(() => {
    fetchDocuments();
    fetchStats();
  }, [fetchDocuments, fetchStats]);

  // Polling
  useEffect(() => {
    const hasPending = documents.some(
      (d) =>
        d.indexation_status === "pending" ||
        d.indexation_status === "indexing"
    );
    if (!hasPending) return;
    const interval = setInterval(() => {
      fetchDocuments();
      fetchStats();
    }, 5000);
    return () => clearInterval(interval);
  }, [documents, fetchDocuments, fetchStats]);

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold tracking-tight">Tous les documents</h1>

      {/* Stats cards */}
      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-base">
              <FileText className="h-4 w-4" />
              Documents
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-semibold tracking-tight">
              {stats?.total_documents ?? "—"}
            </div>
            <p className="text-xs text-muted-foreground">
              {stats
                ? `${stats.common_documents} communs · ${stats.org_documents} organisations`
                : "Chargement..."}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-base">
              <CheckCircle className="h-4 w-4" />
              Indexés
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-semibold tracking-tight">
              {stats
                ? `${stats.indexed_count}/${stats.total_documents}`
                : "—"}
            </div>
            <p className="text-xs text-muted-foreground">
              {stats?.error_count
                ? `${stats.error_count} en erreur`
                : "Aucune erreur"}
              {stats?.indexing_count
                ? ` · ${stats.indexing_count} en cours`
                : ""}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-base">
              <HardDrive className="h-4 w-4" />
              Stockage
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-semibold tracking-tight">
              {stats ? formatFileSize(stats.total_storage_bytes) : "—"}
            </div>
            <p className="text-xs text-muted-foreground">
              Taille totale des fichiers
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Documents table */}
      <Card>
        <CardContent className="pt-6">
          {loading ? (
            <div className="space-y-3">
              {[1, 2, 3, 4, 5].map((i) => (
                <Skeleton key={i} className="h-12 w-full" />
              ))}
            </div>
          ) : documents.length === 0 ? (
            <p className="py-8 text-center text-muted-foreground">
              Aucun document.
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-[35%]">Nom</TableHead>
                  <TableHead>Scope</TableHead>
                  <TableHead className="w-[15%]">Type</TableHead>
                  <TableHead>Statut</TableHead>
                  <TableHead className="w-[10%]">Indexation</TableHead>
                  <TableHead>Taille</TableHead>
                  <TableHead>Format</TableHead>
                  <TableHead>Date</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {documents.map((doc) => (
                  <DocRow key={doc.id} doc={doc} />
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function DocRow({ doc }: { doc: AdminDocument }) {
  const sourceLabel =
    SOURCE_TYPE_OPTIONS.find((s) => s.value === doc.source_type)?.label ??
    doc.source_type;

  return (
    <TableRow>
      <TableCell className="max-w-[200px] truncate font-medium">
        {doc.name}
      </TableCell>
      <TableCell>
        {doc.organisation_name ? (
          <span
            className="max-w-[120px] truncate block text-sm"
            title={doc.organisation_name}
          >
            {doc.organisation_name}
          </span>
        ) : (
          <Badge variant="outline" className="rounded-full border-[#9952b8] bg-[#9952b8]/10 text-[#9952b8] text-xs">
            Commun
          </Badge>
        )}
      </TableCell>
      <TableCell className="text-sm">{sourceLabel}</TableCell>
      <TableCell>
        <Badge
          variant="outline"
          className={STATUS_CLASSES[doc.indexation_status] ?? "rounded-full"}
        >
          {doc.indexation_status === "indexing" && (
            <Loader2 className="mr-1 h-3 w-3 animate-spin" />
          )}
          {STATUS_LABEL[doc.indexation_status] ?? doc.indexation_status}
        </Badge>
      </TableCell>
      <TableCell className="text-sm text-muted-foreground">
        {doc.indexation_status === "indexing" ? (
          <span className="flex items-center gap-1 text-orange-600 dark:text-orange-400">
            <Loader2 className="h-3 w-3 animate-spin" />
            En cours
          </span>
        ) : doc.indexation_status === "error" ? (
          <span className="flex items-center gap-1 text-destructive">
            <RefreshCw className="h-3 w-3" />
            Échoué
          </span>
        ) : (
          formatDuration(doc.indexation_duration_ms)
        )}
      </TableCell>
      <TableCell className="text-sm">
        {formatFileSize(doc.file_size)}
      </TableCell>
      <TableCell className="text-sm uppercase">
        {doc.file_format ?? "—"}
      </TableCell>
      <TableCell className="text-sm">
        {new Date(doc.created_at).toLocaleDateString("fr-FR")}
      </TableCell>
    </TableRow>
  );
}
