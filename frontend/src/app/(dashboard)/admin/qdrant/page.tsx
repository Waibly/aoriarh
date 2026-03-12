"use client";

import { useCallback, useEffect, useState } from "react";
import { useSession } from "next-auth/react";
import { Database, Search, ChevronLeft, ChevronRight } from "lucide-react";
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
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Input } from "@/components/ui/input";

interface CollectionInfo {
  name: string;
  points_count: number;
  status: string;
}

interface PointPayload {
  id: string;
  text: string;
  organisation_id: string | null;
  document_id: string | null;
  doc_name: string | null;
  source_type: string | null;
  norme_niveau: number | null;
  norme_poids: number | null;
  chunk_index: number | null;
}

interface PointsResponse {
  points: PointPayload[];
  total: number;
  offset: number;
  limit: number;
}

const PAGE_SIZE = 20;

export default function QdrantPage() {
  const { data: session } = useSession();
  const token = session?.access_token;

  const [collections, setCollections] = useState<CollectionInfo[]>([]);
  const [loadingCollections, setLoadingCollections] = useState(false);
  const [selectedCollection, setSelectedCollection] = useState<string | null>(
    null
  );
  const [points, setPoints] = useState<PointPayload[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [loadingPoints, setLoadingPoints] = useState(false);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  // Filters
  const [filterOrgId, setFilterOrgId] = useState("");
  const [filterDocId, setFilterDocId] = useState("");

  const fetchCollections = useCallback(async () => {
    if (!token) return;
    setLoadingCollections(true);
    try {
      const data = await apiFetch<CollectionInfo[]>(
        "/admin/qdrant/collections",
        { token }
      );
      setCollections(data);
      if (data.length > 0 && !selectedCollection) {
        setSelectedCollection(data[0].name);
      }
    } catch {
      toast.error("Erreur lors du chargement des collections Qdrant");
    } finally {
      setLoadingCollections(false);
    }
  }, [token, selectedCollection]);

  const fetchPoints = useCallback(async () => {
    if (!token || !selectedCollection) return;
    setLoadingPoints(true);
    try {
      const params = new URLSearchParams({
        offset: String(offset),
        limit: String(PAGE_SIZE),
      });
      if (filterOrgId) params.set("organisation_id", filterOrgId);
      if (filterDocId) params.set("document_id", filterDocId);

      const data = await apiFetch<PointsResponse>(
        `/admin/qdrant/collections/${selectedCollection}/points?${params}`,
        { token }
      );
      setPoints(data.points);
      setTotal(data.total);
    } catch {
      toast.error("Erreur lors du chargement des points");
    } finally {
      setLoadingPoints(false);
    }
  }, [token, selectedCollection, offset, filterOrgId, filterDocId]);

  useEffect(() => {
    fetchCollections();
  }, [fetchCollections]);

  useEffect(() => {
    if (selectedCollection) {
      fetchPoints();
    }
  }, [selectedCollection, fetchPoints]);

  const handleSearch = () => {
    setOffset(0);
    fetchPoints();
  };

  const totalPages = Math.ceil(total / PAGE_SIZE);
  const currentPage = Math.floor(offset / PAGE_SIZE) + 1;

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold tracking-tight">Qdrant — Index vectoriel</h1>

      {/* Collections cards */}
      <div className="grid gap-4 md:grid-cols-3">
        {loadingCollections ? (
          [1, 2, 3].map((i) => <Skeleton key={i} className="h-28" />)
        ) : collections.length === 0 ? (
          <Card className="md:col-span-3">
            <CardContent className="py-8 text-center text-muted-foreground">
              Aucune collection Qdrant. Uploadez un document pour créer la
              collection.
            </CardContent>
          </Card>
        ) : (
          collections.map((col) => (
            <Card
              key={col.name}
              className={
                selectedCollection === col.name
                  ? "border-primary"
                  : "cursor-pointer"
              }
              onClick={() => {
                setSelectedCollection(col.name);
                setOffset(0);
              }}
            >
              <CardHeader className="pb-2">
                <CardTitle className="flex items-center gap-2 text-base">
                  <Database className="h-4 w-4" />
                  {col.name}
                </CardTitle>
                <CardDescription>
                  Statut : {col.status}
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div className="text-sm">
                  <span className="text-muted-foreground">Points : </span>
                  <span className="font-semibold">{col.points_count}</span>
                </div>
              </CardContent>
            </Card>
          ))
        )}
      </div>

      {/* Points browser */}
      {selectedCollection && (
        <Card>
          <CardHeader>
            <CardTitle>
              Chunks — {selectedCollection}
            </CardTitle>
            <CardDescription>
              {total} chunk{total !== 1 ? "s" : ""} indexé
              {total !== 1 ? "s" : ""}
            </CardDescription>

            {/* Filters */}
            <div className="flex flex-wrap items-end gap-3 pt-2">
              <div className="space-y-1">
                <label className="text-xs text-muted-foreground">
                  Organisation ID
                </label>
                <Input
                  placeholder="UUID ou common"
                  value={filterOrgId}
                  onChange={(e) => setFilterOrgId(e.target.value)}
                  className="h-8 w-64"
                />
              </div>
              <div className="space-y-1">
                <label className="text-xs text-muted-foreground">
                  Document ID
                </label>
                <Input
                  placeholder="UUID du document"
                  value={filterDocId}
                  onChange={(e) => setFilterDocId(e.target.value)}
                  className="h-8 w-64"
                />
              </div>
              <Button size="sm" variant="secondary" onClick={handleSearch}>
                <Search className="mr-1 h-3 w-3" />
                Filtrer
              </Button>
              {(filterOrgId || filterDocId) && (
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    setFilterOrgId("");
                    setFilterDocId("");
                    setOffset(0);
                  }}
                >
                  Réinitialiser
                </Button>
              )}
            </div>
          </CardHeader>
          <CardContent>
            {loadingPoints ? (
              <div className="space-y-3">
                {[1, 2, 3].map((i) => (
                  <Skeleton key={i} className="h-12 w-full" />
                ))}
              </div>
            ) : points.length === 0 ? (
              <p className="py-8 text-center text-muted-foreground">
                Aucun chunk trouvé.
              </p>
            ) : (
              <>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="w-12">#</TableHead>
                      <TableHead>Document</TableHead>
                      <TableHead>Type</TableHead>
                      <TableHead>Org</TableHead>
                      <TableHead className="w-16">Niveau</TableHead>
                      <TableHead className="w-16">Poids</TableHead>
                      <TableHead>Texte (aperçu)</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {points.map((point) => (
                      <TableRow
                        key={point.id}
                        className="cursor-pointer"
                        onClick={() =>
                          setExpandedId(
                            expandedId === point.id ? null : point.id
                          )
                        }
                      >
                        <TableCell className="text-xs text-muted-foreground">
                          {point.chunk_index ?? "—"}
                        </TableCell>
                        <TableCell className="max-w-[150px] truncate text-sm font-medium">
                          {point.doc_name ?? "—"}
                        </TableCell>
                        <TableCell>
                          <Badge variant="outline" className="rounded-full text-xs">
                            {point.source_type ?? "—"}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-xs font-mono">
                          {point.organisation_id === "common" ? (
                            <Badge variant="outline" className="rounded-full border-[#9952b8] bg-[#9952b8]/10 text-[#9952b8] text-xs">
                              commun
                            </Badge>
                          ) : (
                            <span
                              className="max-w-[100px] truncate block"
                              title={point.organisation_id ?? ""}
                            >
                              {point.organisation_id?.slice(0, 8) ?? "—"}
                            </span>
                          )}
                        </TableCell>
                        <TableCell className="text-center text-sm">
                          {point.norme_niveau ?? "—"}
                        </TableCell>
                        <TableCell className="text-center text-sm">
                          {point.norme_poids ?? "—"}
                        </TableCell>
                        <TableCell className="max-w-[300px] text-sm">
                          {expandedId === point.id ? (
                            <pre className="max-h-96 overflow-auto whitespace-pre-wrap rounded bg-muted p-3 text-xs">
                              {point.text}
                            </pre>
                          ) : (
                            <span className="line-clamp-2 text-muted-foreground">
                              {point.text.slice(0, 150)}
                              {point.text.length > 150 ? "…" : ""}
                            </span>
                          )}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>

                {/* Pagination */}
                {totalPages > 1 && (
                  <div className="flex items-center justify-between pt-4">
                    <p className="text-sm text-muted-foreground">
                      Page {currentPage} / {totalPages} — {total} résultats
                    </p>
                    <div className="flex gap-2">
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={offset === 0}
                        onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
                      >
                        <ChevronLeft className="h-4 w-4" />
                        Précédent
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={offset + PAGE_SIZE >= total}
                        onClick={() => setOffset(offset + PAGE_SIZE)}
                      >
                        Suivant
                        <ChevronRight className="h-4 w-4" />
                      </Button>
                    </div>
                  </div>
                )}
              </>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
