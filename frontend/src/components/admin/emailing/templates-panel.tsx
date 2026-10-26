"use client";

import { useCallback, useEffect, useState } from "react";
import { AdminLoadError } from "@/components/admin/page-header";
import { useSession } from "next-auth/react";
import { Loader2, Plus, Pencil, Trash2, Send, Eye } from "lucide-react";
import { toast } from "@/lib/toast";
import { apiFetch } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Card, CardContent } from "@/components/ui/card";
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
  preview_text: string | null;
  html_body: string;
  created_at: string;
  updated_at: string;
}

export default function TemplatesPanel() {
  const { data: session } = useSession();
  const token = session?.access_token;

  const [templates, setTemplates] = useState<EmailTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  const [editOpen, setEditOpen] = useState(false);
  const [editId, setEditId] = useState<string | null>(null);
  const [formName, setFormName] = useState("");
  const [formSubject, setFormSubject] = useState("");
  const [formPreview, setFormPreview] = useState("");
  const [formHtml, setFormHtml] = useState("");
  const [saving, setSaving] = useState(false);

  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewHtml, setPreviewHtml] = useState("");

  const [deleteTarget, setDeleteTarget] = useState<EmailTemplate | null>(null);

  const fetchList = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    setError(false);
    try {
      const data = await apiFetch<EmailTemplate[]>(
        "/admin/emailing/templates",
        { token }
      );
      setTemplates(data);
    } catch {
      setError(true);
      toast.error("Erreur lors du chargement des modèles");
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
    setFormPreview("");
    setFormHtml("");
    setEditOpen(true);
  }

  function openEdit(tpl: EmailTemplate) {
    setEditId(tpl.id);
    setFormName(tpl.name);
    setFormSubject(tpl.subject);
    setFormPreview(tpl.preview_text ?? "");
    setFormHtml(tpl.html_body);
    setEditOpen(true);
  }

  async function handleSave() {
    if (!token || !formName.trim() || !formSubject.trim() || !formHtml.trim())
      return;
    setSaving(true);
    try {
      const body = JSON.stringify({
        name: formName.trim(),
        subject: formSubject.trim(),
        preview_text: formPreview.trim() || null,
        html_body: formHtml,
      });

      if (editId) {
        await apiFetch(`/admin/emailing/templates/${editId}`, {
          method: "PUT",
          token,
          body,
        });
        toast.success("Modèle modifié");
      } else {
        await apiFetch("/admin/emailing/templates", {
          method: "POST",
          token,
          body,
        });
        toast.success("Modèle créé");
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
        method: "DELETE",
        token,
      });
      toast.success("Modèle supprimé");
      setDeleteTarget(null);
      fetchList();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Erreur");
    }
  }

  async function handleSendTest(tplId: string) {
    if (!token) return;
    try {
      const result = await apiFetch<{
        results: { email: string; sent: boolean }[];
      }>(`/admin/emailing/templates/${tplId}/test`, { method: "POST", token });
      const sent = result.results.filter((r) => r.sent);
      if (sent.length > 0) {
        toast.success(
          `Email test envoyé à ${sent.map((r) => r.email).join(", ")}`
        );
      } else {
        toast.error("Échec de l'envoi test");
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Erreur");
    }
  }

  const fmt = (d: string) =>
    new Date(d).toLocaleDateString("fr-FR", {
      day: "numeric",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold tracking-tight">
            Modèles d’emails
          </h2>
          <p className="text-muted-foreground text-sm">
            Modèles d&apos;emails en HTML pour les séquences
          </p>
        </div>
        <Button onClick={openCreate}>
          <Plus className="mr-2 h-4 w-4" />
          Nouveau modèle
        </Button>
      </div>

      {error && (
        <AdminLoadError
          message="Impossible de charger les modèles d’emails."
          onRetry={fetchList}
        />
      )}
      <Card>
        <CardContent className="p-0 sm:p-2">
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
                  <TableCell colSpan={4} className="py-8 text-center">
                    <Loader2 className="text-muted-foreground mx-auto h-6 w-6 animate-spin" />
                  </TableCell>
                </TableRow>
              ) : error ? (
                <TableRow>
                  <TableCell
                    colSpan={4}
                    className="text-muted-foreground py-8 text-center"
                  >
                    Données indisponibles.
                  </TableCell>
                </TableRow>
              ) : templates.length === 0 ? (
                <TableRow>
                  <TableCell
                    colSpan={4}
                    className="text-muted-foreground py-8 text-center"
                  >
                    Aucun modèle créé
                  </TableCell>
                </TableRow>
              ) : (
                templates.map((tpl) => (
                  <TableRow key={tpl.id}>
                    <TableCell className="font-medium">{tpl.name}</TableCell>
                    <TableCell className="text-muted-foreground">
                      {tpl.subject}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {fmt(tpl.updated_at)}
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex items-center justify-end gap-1">
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() => {
                            setPreviewHtml(tpl.html_body);
                            setPreviewOpen(true);
                          }}
                          title="Aperçu"
                        >
                          <Eye className="h-4 w-4" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() => handleSendTest(tpl.id)}
                          title="Envoyer un test"
                        >
                          <Send className="h-4 w-4" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() => openEdit(tpl)}
                          title="Modifier"
                        >
                          <Pencil className="h-4 w-4" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() => setDeleteTarget(tpl)}
                          title="Supprimer"
                        >
                          <Trash2 className="text-destructive h-4 w-4" />
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
        <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-4xl">
          <DialogHeader>
            <DialogTitle>
              {editId ? "Modifier le modèle" : "Nouveau modèle"}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label>Nom</Label>
                <Input
                  placeholder="Ex : CSE — Mail 1 — Accès découverte"
                  value={formName}
                  onChange={(e) => setFormName(e.target.value)}
                />
              </div>
              <div className="space-y-2">
                <Label>Objet de l&apos;email</Label>
                <Input
                  placeholder="Ex : {{prenom}}, vous connaissez vos droits ?"
                  value={formSubject}
                  onChange={(e) => setFormSubject(e.target.value)}
                />
              </div>
            </div>
            <div className="space-y-2">
              <Label>
                Texte d’aperçu
                <span className="text-muted-foreground ml-2 text-xs">
                  Texte affiché après l&apos;objet dans la boîte mail, avant
                  d&apos;ouvrir
                </span>
              </Label>
              <Input
                placeholder="Ex : Vérifiez n'importe quel article du Code du travail en quelques secondes."
                value={formPreview}
                onChange={(e) => setFormPreview(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label>
                HTML
                <span className="text-muted-foreground ml-2 text-xs">
                  Variables : {"{{prenom}}"} {"{{nom}}"} {"{{entreprise}}"}{" "}
                  {"{{poste}}"}
                </span>
              </Label>
              <Textarea
                className="min-h-[300px] font-mono text-sm"
                placeholder="<html>..."
                value={formHtml}
                onChange={(e) => setFormHtml(e.target.value)}
              />
            </div>
            {formHtml && (
              <div className="space-y-2">
                <Label>Aperçu</Label>
                <div className="overflow-hidden rounded-lg border bg-white">
                  <iframe
                    srcDoc={formHtml
                      .replace(/\{\{prenom\}\}/g, "Jean")
                      .replace(/\{\{nom\}\}/g, "Dupont")
                      .replace(/\{\{entreprise\}\}/g, "Entreprise Test")
                      .replace(/\{\{poste\}\}/g, "DRH")}
                    className="min-h-[400px] w-full border-0"
                    title="Aperçu du modèle"
                    sandbox="allow-same-origin"
                  />
                </div>
              </div>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditOpen(false)}>
              Annuler
            </Button>
            <Button
              onClick={handleSave}
              disabled={
                saving ||
                !formName.trim() ||
                !formSubject.trim() ||
                !formHtml.trim()
              }
            >
              {saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              {editId ? "Enregistrer" : "Créer"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Dialog : Aperçu plein écran */}
      <Dialog open={previewOpen} onOpenChange={setPreviewOpen}>
        <DialogContent className="max-h-[90vh] sm:max-w-3xl">
          <DialogHeader>
            <DialogTitle>Aperçu</DialogTitle>
          </DialogHeader>
          <div className="overflow-hidden rounded-lg border bg-white">
            <iframe
              srcDoc={previewHtml
                .replace(/\{\{prenom\}\}/g, "Jean")
                .replace(/\{\{nom\}\}/g, "Dupont")
                .replace(/\{\{entreprise\}\}/g, "Entreprise Test")
                .replace(/\{\{poste\}\}/g, "DRH")}
              className="min-h-[500px] w-full border-0"
              title="Aperçu du modèle"
              sandbox="allow-same-origin"
            />
          </div>
        </DialogContent>
      </Dialog>

      {/* Dialog : Supprimer */}
      <Dialog
        open={deleteTarget !== null}
        onOpenChange={(open) => {
          if (!open) setDeleteTarget(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Supprimer ce modèle ?</DialogTitle>
          </DialogHeader>
          <p className="text-muted-foreground text-sm">
            Le modèle &laquo;&nbsp;{deleteTarget?.name}&nbsp;&raquo; sera
            supprimé définitivement.
          </p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteTarget(null)}>
              Annuler
            </Button>
            <Button variant="destructive" onClick={handleDelete}>
              Supprimer
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
