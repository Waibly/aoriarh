"use client";

import { useCallback, useEffect, useState } from "react";
import { AdminLoadError } from "@/components/admin/page-header";
import { useSession } from "next-auth/react";
import { Loader2, Users, ChevronLeft, RefreshCw } from "lucide-react";
import { toast } from "@/lib/toast";
import { apiFetch } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

interface BrevoList {
  id: number;
  name: string;
  total_subscribers: number;
  total_blacklisted: number;
}

interface BrevoContact {
  id: number;
  email: string;
  first_name: string | null;
  last_name: string | null;
  company: string | null;
}

export default function ListsPanel() {
  const { data: session } = useSession();
  const token = session?.access_token;

  const [lists, setLists] = useState<BrevoList[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [contactsError, setContactsError] = useState(false);

  const [selectedList, setSelectedList] = useState<BrevoList | null>(null);
  const [contacts, setContacts] = useState<BrevoContact[]>([]);
  const [loadingContacts, setLoadingContacts] = useState(false);

  const fetchLists = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    setError(false);
    try {
      const data = await apiFetch<BrevoList[]>("/admin/emailing/lists", {
        token,
      });
      setLists(data);
    } catch {
      setError(true);
      toast.error("Erreur lors du chargement des listes Brevo");
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    fetchLists();
  }, [fetchLists]);

  async function openList(list: BrevoList) {
    if (!token) return;
    setSelectedList(list);
    setLoadingContacts(true);
    setContacts([]);
    setContactsError(false);
    try {
      const data = await apiFetch<BrevoContact[]>(
        `/admin/emailing/lists/${list.id}/contacts`,
        { token }
      );
      setContacts(data);
    } catch {
      setContactsError(true);
      toast.error("Erreur lors du chargement des contacts");
    } finally {
      setLoadingContacts(false);
    }
  }

  if (selectedList) {
    return (
      <div className="space-y-5">
        <div className="flex items-center gap-3">
          <Button
            variant="ghost"
            size="icon"
            aria-label="Retour aux listes de contacts"
            onClick={() => setSelectedList(null)}
          >
            <ChevronLeft className="h-5 w-5" />
          </Button>
          <div>
            <h2 className="text-lg font-semibold tracking-tight">
              {selectedList.name}
            </h2>
            <p className="text-muted-foreground text-sm">
              {selectedList.total_subscribers} contacts
            </p>
          </div>
        </div>

        {contactsError && (
          <AdminLoadError
            message="Impossible de charger les contacts de cette liste."
            onRetry={() => openList(selectedList)}
          />
        )}
        <Card>
          <CardContent className="p-0 sm:p-2">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Email</TableHead>
                  <TableHead>Prénom</TableHead>
                  <TableHead>Nom</TableHead>
                  <TableHead>Entreprise</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {loadingContacts ? (
                  <TableRow>
                    <TableCell colSpan={4} className="py-8 text-center">
                      <Loader2 className="text-muted-foreground mx-auto h-6 w-6 animate-spin" />
                    </TableCell>
                  </TableRow>
                ) : contactsError ? (
                  <TableRow>
                    <TableCell
                      colSpan={4}
                      className="text-muted-foreground py-8 text-center"
                    >
                      Données indisponibles.
                    </TableCell>
                  </TableRow>
                ) : contacts.length === 0 ? (
                  <TableRow>
                    <TableCell
                      colSpan={4}
                      className="text-muted-foreground py-8 text-center"
                    >
                      Aucun contact dans cette liste
                    </TableCell>
                  </TableRow>
                ) : (
                  contacts.map((c) => (
                    <TableRow key={c.id}>
                      <TableCell className="font-medium">{c.email}</TableCell>
                      <TableCell>{c.first_name ?? "—"}</TableCell>
                      <TableCell>{c.last_name ?? "—"}</TableCell>
                      <TableCell className="text-muted-foreground">
                        {c.company ?? "—"}
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold tracking-tight">
            Listes de contacts
          </h2>
          <p className="text-muted-foreground text-sm">
            Consultez votre audience. Les listes et les contacts se gèrent dans
            Brevo.
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={fetchLists}
          disabled={loading}
        >
          <RefreshCw className="size-4" /> Actualiser
        </Button>
      </div>

      {loading ? (
        <div className="flex justify-center py-12">
          <Loader2 className="text-muted-foreground h-8 w-8 animate-spin" />
        </div>
      ) : error ? (
        <AdminLoadError
          message="Impossible de charger les listes Brevo."
          onRetry={fetchLists}
        />
      ) : lists.length === 0 ? (
        <Card>
          <CardContent className="text-muted-foreground p-8 text-center">
            Aucune liste trouvée dans Brevo
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {lists.map((list) => (
            <Card
              key={list.id}
              className="hover:border-primary/50 transition-colors"
            >
              <button
                type="button"
                onClick={() => openList(list)}
                className="focus-visible:outline-primary w-full rounded-xl text-left focus-visible:outline-2 focus-visible:outline-offset-4"
              >
                <CardHeader className="pb-2">
                  <CardTitle className="flex items-center gap-2 text-base">
                    <Users className="text-muted-foreground h-4 w-4" />
                    {list.name}
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="flex items-baseline gap-2">
                    <span className="text-2xl font-bold">
                      {list.total_subscribers}
                    </span>
                    <span className="text-muted-foreground text-sm">
                      contacts
                    </span>
                  </div>
                  {list.total_blacklisted > 0 && (
                    <p className="text-muted-foreground mt-1 text-xs">
                      {list.total_blacklisted} désinscrits
                    </p>
                  )}
                </CardContent>
              </button>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
