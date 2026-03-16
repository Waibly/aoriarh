"use client";

import { useCallback, useEffect, useState } from "react";
import { useSession } from "next-auth/react";
import {
  Building2,
  RefreshCw,
  Search,
  Trash2,
  Plus,
  Scale,
} from "lucide-react";
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
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import type { CcnReference } from "@/types/api";
import { CcnSelector } from "@/components/ccn-selector";

interface InstalledCcn {
  idcc: string;
  titre: string;
  titre_court: string | null;
  documents_count: number;
  orgs_count: number;
  articles_count: number | null;
  source_date: string | null;
  status: string;
}

interface InstalledCcnResponse {
  items: InstalledCcn[];
  total: number;
}

export default function AdminCcnPage() {
  const { data: session } = useSession();
  const token = session?.access_token;

  const [data, setData] = useState<InstalledCcnResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [installOpen, setInstallOpen] = useState(false);
  const [selectedCcn, setSelectedCcn] = useState<CcnReference[]>([]);
  const [installing, setInstalling] = useState(false);
  const [deleteIdcc, setDeleteIdcc] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(search), 300);
    return () => clearTimeout(timer);
  }, [search]);

  const fetchData = useCallback(async () => {
    if (!token) return;
    try {
      const params = debouncedSearch ? `?search=${encodeURIComponent(debouncedSearch)}` : "";
      const res = await apiFetch<InstalledCcnResponse>(
        `/admin/ccn/installed${params}`,
        { token },
      );
      setData(res);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Erreur");
    } finally {
      setLoading(false);
    }
  }, [token, debouncedSearch]);

  useEffect(() => {
    setLoading(true);
    fetchData();
  }, [fetchData]);

  // Auto-refresh every 10s
  useEffect(() => {
    const interval = setInterval(fetchData, 10000);
    return () => clearInterval(interval);
  }, [fetchData]);

  const handleInstall = async () => {
    if (!token || selectedCcn.length === 0) return;
    setInstalling(true);
    try {
      for (const ccn of selectedCcn) {
        await apiFetch("/admin/ccn/install", {
          method: "POST",
          token,
          body: JSON.stringify({ idcc: ccn.idcc }),
        });
      }
      toast.success(
        selectedCcn.length === 1
          ? "Installation lancée"
          : `${selectedCcn.length} installations lancées`
      );
      setSelectedCcn([]);
      setInstallOpen(false);
      fetchData();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Erreur");
    } finally {
      setInstalling(false);
    }
  };

  const handleSync = async (idcc: string) => {
    if (!token) return;
    try {
      await apiFetch(`/admin/ccn/${idcc}/sync`, { method: "POST", token });
      toast.success("Mise à jour lancée");
      fetchData();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Erreur");
    }
  };

  const handleDelete = async () => {
    if (!token || !deleteIdcc) return;
    setDeleting(true);
    try {
      await apiFetch(`/admin/ccn/${deleteIdcc}`, { method: "DELETE", token });
      toast.success("CCN supprimée du référentiel");
      setDeleteIdcc(null);
      fetchData();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Erreur");
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            Conventions collectives
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Référentiel partagé des CCN. Les documents sont communs à toutes les organisations.
          </p>
        </div>
        <Button size="sm" onClick={() => setInstallOpen(true)}>
          <Plus className="mr-2 h-4 w-4" />
          Installer une CCN
        </Button>
      </div>

      {/* Search */}
      <div className="relative max-w-md">
        <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          placeholder="Rechercher par IDCC ou nom..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="pl-9"
        />
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Scale className="h-5 w-5" />
            CCN installées
          </CardTitle>
          <CardDescription>
            {data ? `${data.total} convention${data.total > 1 ? "s" : ""} dans le référentiel` : "Chargement..."}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="space-y-2">
              {[1, 2, 3].map((i) => <Skeleton key={i} className="h-10 w-full" />)}
            </div>
          ) : !data || data.items.length === 0 ? (
            <p className="py-8 text-center text-muted-foreground">
              {debouncedSearch ? "Aucun résultat." : "Aucune CCN installée. Cliquez sur \"Installer une CCN\" pour commencer."}
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-16">IDCC</TableHead>
                  <TableHead>Convention</TableHead>
                  <TableHead className="text-right">Docs</TableHead>
                  <TableHead className="text-right">Orgs</TableHead>
                  <TableHead>Date source</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.items.map((ccn) => {
                  const ageMs = ccn.source_date ? Date.now() - new Date(ccn.source_date).getTime() : null;
                  const ageYears = ageMs ? ageMs / (365.25 * 24 * 60 * 60 * 1000) : null;
                  const dateColor = ageYears === null
                    ? ""
                    : ageYears > 2
                      ? "border-red-500 bg-red-500/10 text-red-700"
                      : ageYears > 1
                        ? "border-orange-500 bg-orange-500/10 text-orange-700"
                        : "border-green-500 bg-green-500/10 text-green-700";

                  return (
                    <TableRow key={ccn.idcc}>
                      <TableCell className="font-mono text-sm">{ccn.idcc}</TableCell>
                      <TableCell>
                        <p className="text-sm font-medium line-clamp-1">
                          {ccn.titre_court || ccn.titre}
                        </p>
                        {ccn.articles_count != null && (
                          <p className="text-xs text-muted-foreground">{ccn.articles_count} articles</p>
                        )}
                      </TableCell>
                      <TableCell className="text-right text-sm">{ccn.documents_count}</TableCell>
                      <TableCell className="text-right">
                        <div className="flex items-center justify-end gap-1">
                          <Building2 className="h-3 w-3 text-muted-foreground" />
                          <span className="text-sm">{ccn.orgs_count}</span>
                        </div>
                      </TableCell>
                      <TableCell>
                        {ccn.source_date ? (
                          <Badge variant="outline" className={`rounded-full text-[11px] ${dateColor}`}>
                            {new Date(ccn.source_date).toLocaleDateString("fr-FR")}
                          </Badge>
                        ) : (
                          <span className="text-xs text-muted-foreground">—</span>
                        )}
                      </TableCell>
                      <TableCell className="text-right">
                        <div className="flex justify-end gap-1">
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-8 w-8"
                            title="Mettre à jour depuis KALI"
                            onClick={() => handleSync(ccn.idcc)}
                          >
                            <RefreshCw className="h-4 w-4" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-8 w-8 text-destructive hover:text-destructive"
                            title={ccn.orgs_count > 0 ? "Utilisée par des organisations" : "Supprimer"}
                            disabled={ccn.orgs_count > 0}
                            onClick={() => setDeleteIdcc(ccn.idcc)}
                          >
                            <Trash2 className="h-4 w-4" />
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* Install dialog */}
      <Dialog open={installOpen} onOpenChange={setInstallOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>Installer une convention collective</DialogTitle>
            <DialogDescription>
              La CCN sera téléchargée depuis l&apos;API Légifrance et ajoutée au référentiel partagé.
            </DialogDescription>
          </DialogHeader>
          {token && (
            <CcnSelector
              token={token}
              selected={selectedCcn}
              onChange={setSelectedCcn}
            />
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setInstallOpen(false)}>
              Annuler
            </Button>
            <Button
              onClick={handleInstall}
              disabled={selectedCcn.length === 0 || installing}
            >
              {installing ? "Installation..." : "Installer"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete confirmation */}
      <Dialog open={deleteIdcc !== null} onOpenChange={(open) => { if (!open) setDeleteIdcc(null); }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Supprimer du référentiel</DialogTitle>
            <DialogDescription>
              Cette action supprimera la CCN IDCC {deleteIdcc} et tous ses documents
              indexés. Cette action est irréversible.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteIdcc(null)}>
              Annuler
            </Button>
            <Button variant="destructive" onClick={handleDelete} disabled={deleting}>
              {deleting ? "Suppression..." : "Supprimer"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
