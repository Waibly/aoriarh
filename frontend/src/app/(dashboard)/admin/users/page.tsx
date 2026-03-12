"use client";

import { useCallback, useEffect, useState } from "react";
import { useSession } from "next-auth/react";
import { Search, Users, Building2 } from "lucide-react";
import { toast } from "sonner";
import { apiFetch } from "@/lib/api";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
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

interface UserOrgItem {
  organisation_id: string;
  organisation_name: string;
  role_in_org: string;
}

interface AdminUserItem {
  id: string;
  email: string;
  full_name: string;
  role: string;
  is_active: boolean;
  created_at: string;
  organisations: UserOrgItem[];
}

interface UserListResponse {
  items: AdminUserItem[];
  total: number;
  page: number;
  page_size: number;
}

const roleBadge: Record<string, { label: string; variant: "default" | "secondary" | "outline" }> = {
  admin: { label: "Admin", variant: "default" },
  manager: { label: "Manager", variant: "secondary" },
  user: { label: "Utilisateur", variant: "outline" },
};

function orgRoleLabel(role: string): string {
  switch (role) {
    case "manager": return "Manager";
    case "user": return "Membre";
    default: return role;
  }
}

export default function AdminUsersPage() {
  const { data: session } = useSession();
  const token = session?.access_token;

  const [data, setData] = useState<UserListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const PAGE_SIZE = 50;

  const fetchUsers = useCallback(async () => {
    if (!token) return;
    try {
      const res = await apiFetch<UserListResponse>(
        `/admin/users/?page=${page}&page_size=${PAGE_SIZE}`,
        { token },
      );
      setData(res);
    } catch {
      toast.error("Erreur lors du chargement des utilisateurs");
    } finally {
      setLoading(false);
    }
  }, [token, page]);

  useEffect(() => {
    setLoading(true);
    fetchUsers();
  }, [fetchUsers]);

  const filteredItems = data?.items.filter((u) => {
    if (!search.trim()) return true;
    const q = search.toLowerCase();
    return (
      u.full_name.toLowerCase().includes(q) ||
      u.email.toLowerCase().includes(q) ||
      u.organisations.some((o) => o.organisation_name.toLowerCase().includes(q))
    );
  });

  const totalPages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1;

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold tracking-tight">Utilisateurs</h1>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Users className="size-5" />
            Tous les utilisateurs
          </CardTitle>
          <CardDescription>
            {data ? `${data.total} utilisateur${data.total > 1 ? "s" : ""} au total` : "Chargement..."}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="mb-4">
            <div className="relative max-w-sm">
              <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                placeholder="Rechercher par nom ou email..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="pl-9"
              />
            </div>
          </div>

          {loading ? (
            <div className="space-y-3">
              {[1, 2, 3, 4, 5].map((i) => (
                <Skeleton key={i} className="h-12 w-full" />
              ))}
            </div>
          ) : !filteredItems || filteredItems.length === 0 ? (
            <p className="py-8 text-center text-muted-foreground">
              {search ? "Aucun utilisateur trouvé." : "Aucun utilisateur pour le moment."}
            </p>
          ) : (
            <>
              <TooltipProvider delayDuration={300}>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Nom</TableHead>
                      <TableHead>Email</TableHead>
                      <TableHead>Rôle</TableHead>
                      <TableHead>Organisations</TableHead>
                      <TableHead>Statut</TableHead>
                      <TableHead>Inscription</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {filteredItems!.map((user) => {
                      const badge = roleBadge[user.role] || roleBadge.user;
                      return (
                        <TableRow key={user.id}>
                          <TableCell className="font-medium text-sm">
                            {user.full_name}
                          </TableCell>
                          <TableCell className="text-sm">
                            {user.email}
                          </TableCell>
                          <TableCell>
                            <Badge variant={badge.variant}>{badge.label}</Badge>
                          </TableCell>
                          <TableCell className="text-sm">
                            {user.organisations.length === 0 ? (
                              <span className="text-muted-foreground">Aucune</span>
                            ) : (
                              <Tooltip>
                                <TooltipTrigger asChild>
                                  <span className="flex cursor-default items-center gap-1">
                                    <Building2 className="size-3.5 text-muted-foreground" />
                                    {user.organisations.length} org{user.organisations.length > 1 ? "s" : ""}
                                  </span>
                                </TooltipTrigger>
                                <TooltipContent side="bottom" className="max-w-xs">
                                  <ul className="space-y-1">
                                    {user.organisations.map((o) => (
                                      <li key={o.organisation_id} className="flex items-center justify-between gap-3 text-sm">
                                        <span>{o.organisation_name}</span>
                                        <span className="text-xs text-muted-foreground">{orgRoleLabel(o.role_in_org)}</span>
                                      </li>
                                    ))}
                                  </ul>
                                </TooltipContent>
                              </Tooltip>
                            )}
                          </TableCell>
                          <TableCell>
                            {user.is_active ? (
                              <Badge variant="outline" className="border-green-500 text-green-600">Actif</Badge>
                            ) : (
                              <Badge variant="outline" className="border-red-500 text-red-600">Inactif</Badge>
                            )}
                          </TableCell>
                          <TableCell className="text-sm text-muted-foreground whitespace-nowrap">
                            {new Date(user.created_at).toLocaleDateString("fr-FR", {
                              day: "2-digit",
                              month: "2-digit",
                              year: "numeric",
                            })}
                          </TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              </TooltipProvider>

              {totalPages > 1 && (
                <div className="flex items-center justify-between border-t pt-4 mt-4">
                  <p className="text-sm text-muted-foreground">
                    {(page - 1) * PAGE_SIZE + 1}–{Math.min(page * PAGE_SIZE, data!.total)} sur {data!.total}
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
