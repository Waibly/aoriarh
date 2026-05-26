"use client";

import { useCallback, useEffect, useState } from "react";
import { useSession } from "next-auth/react";
import { Loader2, Plus, Pencil, Trash2, Send, Eye } from "lucide-react";
import { toast } from "sonner";
import { apiFetch } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
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

interface EmailTemplate {
  id: string;
  name: string;
  subject: string;
  html_body: string;
  created_at: string;
  updated_at: string;
}

export default function AdminEmailTemplatesPage() {
  const { data: session } = useSession();
  const token = session?.access_token;

  const [templates, setTemplates] = useState<EmailTemplate[]>([]);
  const [loading, setLoading] = useState(true);

  const [editOpen, setEditOpen] = useState(false);
  const [editId, setEditId] = useState<string | null>(null);
  const [formName, setFormName] = useState("");
  const [formSubject, setFormSubject] = useState("");
  const [formHtml, setFormHtml] = useState("");
  const [saving, setSaving] = useState(false);

  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewHtml, setPreviewHtml] = useState("");

  const [deleteTarget, setDeleteTarget] = useState<EmailTemplate | null>(null);

  const fetchList = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    try {
      const data = await apiFetch<EmailTemplate[]>("/admin/emailing/templates", { token });
      setTemplates(data);
    } catch {
      toast.error("Erreur lors du chargement des templates");
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    fetchList();
  }, [fetchList]);

  function openCreate() {
    setEditId(null);
    setFormName("");
    setFormSubject("");
    setFormHtml("");
    setEditOpen(true);
  }

  function openEdit(tpl: EmailTemplate) {
    setEditId(tpl.id);
    setFormName(tpl.name);
    setFormSubject(tpl.subject);
    setFormHtml(tpl.html_body);
    setEditOpen(true);
  }

  async function handleSave() {
    if (!token || !formName.trim() || !formSubject.trim() || !formHtml.trim()) return;
    setSaving(true);
    try {
      const body = JSON.stringify({
        name: formName.trim(),
        subject: formSubject.trim(),
        html_body: formHtml,
      });

      if (editId) {
        await apiFetch(`/admin/emailing/templates/${editId}`, {
          method: "PUT", token, body,
        });
        toast.success("Template modifié");
      } else {
        await apiFetch("/admin/emailing/templates", {
          method: "POST", token, body,
        });
        toast.success("Template créé");
      }

      setEditOpen(false);
      fetchList();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Erreur");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    if (!token || !deleteTarget) return;
    try {
      await apiFetch(`/admin/emailing/templates/${deleteTarget.id}`, {
        method: "DELETE", token,
      });
      toast.success("Template supprimé");
      setDeleteTarget(null);
      fetchList();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Erreur");
    }
  }

  async function handleSendTest(tplId: string) {
    if (!token) return;
    try {
      const result = await apiFetch<{ sent: boolean; to: string }>(
        `/admin/emailing/templates/${tplId}/test`,
        { method: "POST", token },
      );
      if (result.sent) {
        toast.success(`Email test envoyé à ${result.to}`);
      } else {
        toast.error("Échec de l'envoi test");
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Erreur");
    }
  }

  const fmt = (d: string) =>
    new Date(d).toLocaleDateString("fr-FR", {
      day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit",
    });

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Templates email</h1>
          <p className="text-sm text-muted-foreground">
            Modèles d&apos;emails en HTML pour les séquences
          </p>
        </div>
        <Button onClick={openCreate}>
          <Plus className="mr-2 h-4 w-4" />
          Nouveau template
        </Button>
      </div>

      <Card>
        <CardContent className="p-4">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Nom</TableHead>
                <TableHead>Objet</TableHead>
                <TableHead>Modifié le</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {loading ? (
                <TableRow>
                  <TableCell colSpan={4} className="text-center py-8">
                    <Loader2 className="mx-auto h-6 w-6 animate-spin text-muted-foreground" />
                  </TableCell>
                </TableRow>
              ) : templates.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={4} className="text-center py-8 text-muted-foreground">
                    Aucun template créé
                  </TableCell>
                </TableRow>
              ) : (
                templates.map((tpl) => (
                  <TableRow key={tpl.id}>
                    <TableCell className="font-medium">{tpl.name}</TableCell>
                    <TableCell className="text-muted-foreground">{tpl.subject}</TableCell>
                    <TableCell className="text-muted-foreground">{fmt(tpl.updated_at)}</TableCell>
                    <TableCell className="text-right">
                      <div className="flex items-center justify-end gap-1">
                        <Button
                          variant="ghost" size="icon"
                          onClick={() => { setPreviewHtml(tpl.html_body); setPreviewOpen(true); }}
                          title="Aperçu"
                        >
                          <Eye className="h-4 w-4" />
                        </Button>
                        <Button variant="ghost" size="icon" onClick={() => handleSendTest(tpl.id)} title="Envoyer un test">
                          <Send className="h-4 w-4" />
                        </Button>
                        <Button variant="ghost" size="icon" onClick={() => openEdit(tpl)} title="Modifier">
                          <Pencil className="h-4 w-4" />
                        </Button>
                        <Button variant="ghost" size="icon" onClick={() => setDeleteTarget(tpl)} title="Supprimer">
                          <Trash2 className="h-4 w-4 text-destructive" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {/* Dialog : Créer / Modifier */}
      <Dialog open={editOpen} onOpenChange={setEditOpen}>
        <DialogContent className="sm:max-w-4xl max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{editId ? "Modifier le template" : "Nouveau template"}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label>Nom</Label>
                <Input
                  placeholder="Ex : Prospection RH - Email 1"
                  value={formName}
                  onChange={(e) => setFormName(e.target.value)}
                />
              </div>
              <div className="space-y-2">
                <Label>Objet de l&apos;email</Label>
                <Input
                  placeholder="Ex : {{prenom}}, vos recherches en droit social ?"
                  value={formSubject}
                  onChange={(e) => setFormSubject(e.target.value)}
                />
              </div>
            </div>
            <div className="space-y-2">
              <Label>
                HTML
                <span className="text-muted-foreground text-xs ml-2">
                  Variables : {"{{prenom}}"} {"{{nom}}"} {"{{entreprise}}"} {"{{poste}}"}
                </span>
              </Label>
              <Textarea
                className="font-mono text-sm min-h-[300px]"
                placeholder="<html>..."
                value={formHtml}
                onChange={(e) => setFormHtml(e.target.value)}
              />
            </div>
            {formHtml && (
              <div className="space-y-2">
                <Label>Aperçu</Label>
                <div className="border rounded-lg overflow-hidden bg-white">
                  <iframe
                    srcDoc={formHtml
                      .replace(/\{\{prenom\}\}/g, "Jean")
                      .replace(/\{\{nom\}\}/g, "Dupont")
                      .replace(/\{\{entreprise\}\}/g, "Entreprise Test")
                      .replace(/\{\{poste\}\}/g, "DRH")}
                    className="w-full min-h-[400px] border-0"
                    title="Aperçu du template"
                    sandbox="allow-same-origin"
                  />
                </div>
              </div>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditOpen(false)}>Annuler</Button>
            <Button
              onClick={handleSave}
              disabled={saving || !formName.trim() || !formSubject.trim() || !formHtml.trim()}
            >
              {saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              {editId ? "Enregistrer" : "Créer"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Dialog : Aperçu plein écran */}
      <Dialog open={previewOpen} onOpenChange={setPreviewOpen}>
        <DialogContent className="sm:max-w-3xl max-h-[90vh]">
          <DialogHeader>
            <DialogTitle>Aperçu</DialogTitle>
          </DialogHeader>
          <div className="border rounded-lg overflow-hidden bg-white">
            <iframe
              srcDoc={previewHtml
                .replace(/\{\{prenom\}\}/g, "Jean")
                .replace(/\{\{nom\}\}/g, "Dupont")
                .replace(/\{\{entreprise\}\}/g, "Entreprise Test")
                .replace(/\{\{poste\}\}/g, "DRH")}
              className="w-full min-h-[500px] border-0"
              title="Aperçu du template"
              sandbox="allow-same-origin"
            />
          </div>
        </DialogContent>
      </Dialog>

      {/* Dialog : Supprimer */}
      <Dialog open={deleteTarget !== null} onOpenChange={(open) => { if (!open) setDeleteTarget(null); }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Supprimer ce template ?</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">
            Le template &laquo;&nbsp;{deleteTarget?.name}&nbsp;&raquo; sera supprimé définitivement.
          </p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteTarget(null)}>Annuler</Button>
            <Button variant="destructive" onClick={handleDelete}>Supprimer</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
