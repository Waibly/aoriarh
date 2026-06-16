"use client";

import { useCallback, useEffect, useState } from "react";
import { useSession } from "next-auth/react";
import { Loader2, Users, ChevronLeft } from "lucide-react";
import { toast } from "sonner";
import { apiFetch } from "@/lib/api";
import { Button } from "@/components/ui/button";
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

export default function AdminEmailListsPage() {
  const { data: session } = useSession();
  const token = session?.access_token;

  const [lists, setLists] = useState<BrevoList[]>([]);
  const [loading, setLoading] = useState(true);

  const [selectedList, setSelectedList] = useState<BrevoList | null>(null);
  const [contacts, setContacts] = useState<BrevoContact[]>([]);
  const [loadingContacts, setLoadingContacts] = useState(false);

  const fetchLists = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    try {
      const data = await apiFetch<BrevoList[]>("/admin/emailing/lists", { token });
      setLists(data);
    } catch {
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
    try {
      const data = await apiFetch<BrevoContact[]>(
        `/admin/emailing/lists/${list.id}/contacts`,
        { token },
      );
      setContacts(data);
    } catch {
      toast.error("Erreur lors du chargement des contacts");
    } finally {
      setLoadingContacts(false);
    }
  }

  if (selectedList) {
    return (
      <div className="space-y-6 p-6">
        <div className="flex items-center gap-3">
          <Button variant="ghost" size="icon" onClick={() => setSelectedList(null)}>
            <ChevronLeft className="h-5 w-5" />
          </Button>
          <div>
            <h1 className="text-2xl font-bold">{selectedList.name}</h1>
            <p className="text-sm text-muted-foreground">
              {selectedList.total_subscribers} contacts
            </p>
          </div>
        </div>

        <Card>
          <CardContent className="p-4">
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
                    <TableCell colSpan={4} className="text-center py-8">
                      <Loader2 className="mx-auto h-6 w-6 animate-spin text-muted-foreground" />
                    </TableCell>
                  </TableRow>
                ) : contacts.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={4} className="text-center py-8 text-muted-foreground">
                      Aucun contact dans cette liste
                    </TableCell>
                  </TableRow>
                ) : (
                  contacts.map((c) => (
                    <TableRow key={c.id}>
                      <TableCell className="font-medium">{c.email}</TableCell>
                      <TableCell>{c.first_name ?? "—"}</TableCell>
                      <TableCell>{c.last_name ?? "—"}</TableCell>
                      <TableCell className="text-muted-foreground">{c.company ?? "—"}</TableCell>
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
    <div className="space-y-6 p-6">
      <div>
        <h1 className="text-2xl font-bold">Listes Brevo</h1>
        <p className="text-sm text-muted-foreground">
          Vos listes de contacts dans Brevo (lecture seule)
        </p>
      </div>

      {loading ? (
        <div className="flex justify-center py-12">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      ) : lists.length === 0 ? (
        <Card>
          <CardContent className="p-8 text-center text-muted-foreground">
            Aucune liste trouvée dans Brevo
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {lists.map((list) => (
            <Card
              key={list.id}
              className="cursor-pointer hover:border-primary/50 transition-colors"
              onClick={() => openList(list)}
            >
              <CardHeader className="pb-2">
                <CardTitle className="text-base flex items-center gap-2">
                  <Users className="h-4 w-4 text-muted-foreground" />
                  {list.name}
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="flex items-baseline gap-2">
                  <span className="text-2xl font-bold">{list.total_subscribers}</span>
                  <span className="text-sm text-muted-foreground">contacts</span>
                </div>
                {list.total_blacklisted > 0 && (
                  <p className="text-xs text-muted-foreground mt-1">
                    {list.total_blacklisted} désinscrits
                  </p>
                )}
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
