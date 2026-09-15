"use client";

import { useCallback, useRef, useState } from "react";
import {
  AlertTriangle,
  Check,
  Code2,
  Copy,
  Download,
  FileCode2,
  Loader2,
  RefreshCw,
  RotateCcw,
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  generateXPost,
  renderSocialMediaHtml,
  type XPostFormat,
  type XPostResult,
} from "@/lib/chat-api";
import { cn } from "@/lib/utils";
import { ExportPreview } from "./social-media-dialog";

interface XPostDialogProps {
  messageId: string;
  token: string | undefined;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

const FORMAT_DETAILS: Record<
  XPostFormat,
  { label: string; description: string; limit: number | null }
> = {
  short: {
    label: "Post court",
    description: "1 post · 280 caractères · Tous les comptes",
    limit: 280,
  },
  thread: {
    label: "Fil de 3 posts (recommandé)",
    description: "3 posts · 280 caractères chacun · Tous les comptes",
    limit: null,
  },
};

function base64ToArrayBuffer(value: string): ArrayBuffer {
  const binary = window.atob(value);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return bytes.buffer;
}

function downloadBlob(blob: Blob, filename: string) {
  const url = window.URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.URL.revokeObjectURL(url);
}

export function XPostDialog({
  messageId,
  token,
  open,
  onOpenChange,
}: XPostDialogProps) {
  const [format, setFormat] = useState<XPostFormat>("thread");
  const [post, setPost] = useState<XPostResult | null>(null);
  const [html, setHtml] = useState("");
  const [loading, setLoading] = useState(false);
  const [rendering, setRendering] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const inFlightRef = useRef(false);

  const requestPost = useCallback(async () => {
    if (inFlightRef.current) return;
    if (!token) {
      setError("Session indisponible. Veuillez actualiser la page.");
      return;
    }
    inFlightRef.current = true;
    setLoading(true);
    setError(null);
    setExportError(null);
    try {
      const generated = await generateXPost(messageId, token, format);
      setPost(generated);
      setHtml(generated.visual_html ?? "");
      setExportError(generated.visual_error);
      setCopied(false);
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : "La génération du post X a échoué."
      );
    } finally {
      inFlightRef.current = false;
      setLoading(false);
    }
  }, [format, messageId, token]);

  const handleFormatChange = useCallback((value: XPostFormat) => {
    setFormat(value);
    setPost(null);
    setHtml("");
    setError(null);
    setExportError(null);
    setCopied(false);
  }, []);

  const handleCopy = useCallback(async () => {
    if (!post) return;
    try {
      await navigator.clipboard.writeText(post.content);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.error(
        "Impossible de copier la publication. Sélectionnez le texte manuellement."
      );
    }
  }, [post]);

  const htmlModified = Boolean(post?.visual_html) && html !== post?.visual_html;

  const handleRegenerate = useCallback(() => {
    if (
      htmlModified &&
      !window.confirm(
        "Le HTML du visuel a été modifié. Une nouvelle génération remplacera ces modifications. Continuer ?"
      )
    ) {
      return;
    }
    void requestPost();
  }, [htmlModified, requestPost]);

  const handleResetHtml = useCallback(() => {
    if (post?.visual_html) setHtml(post.visual_html);
  }, [post]);

  const handleDownloadHtml = useCallback(() => {
    if (!html) return;
    downloadBlob(
      new Blob([html], { type: "text/html;charset=utf-8" }),
      "aoria-post-x.html"
    );
  }, [html]);

  const handleDownloadPng = useCallback(async () => {
    if (!token || !html || rendering) return;
    setRendering(true);
    setExportError(null);
    try {
      const result = await renderSocialMediaHtml(messageId, html, token);
      const image = result.images[0];
      if (!image) throw new Error("Le rendu n’a produit aucune image.");
      downloadBlob(
        new Blob([base64ToArrayBuffer(image.content_base64)], {
          type: "image/png",
        }),
        "aoria-post-x-1260x675.png"
      );
    } catch (requestError) {
      setExportError(
        requestError instanceof Error
          ? requestError.message
          : "L’export PNG a échoué. Le HTML reste disponible sans modification."
      );
    } finally {
      setRendering(false);
    }
  }, [html, messageId, rendering, token]);

  const details = FORMAT_DETAILS[format];
  const overLimit =
    details.limit !== null && (post?.character_count ?? 0) > details.limit;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex h-[94dvh] max-h-[94dvh] w-[96vw] max-w-[96vw] flex-col sm:max-w-[96vw] xl:max-w-[1800px]">
        <DialogHeader>
          <DialogTitle>Générer une publication X</DialogTitle>
          <DialogDescription>
            Choisissez un format compatible avec votre compte X gratuit et
            vérifiez le contenu avant publication.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-1.5">
          <label htmlFor="x-post-format" className="text-sm font-medium">
            Format
          </label>
          <Select
            value={format}
            onValueChange={handleFormatChange}
            disabled={loading}
          >
            <SelectTrigger
              id="x-post-format"
              aria-label="Format de publication X"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {Object.entries(FORMAT_DETAILS).map(([value, item]) => (
                <SelectItem key={value} value={value}>
                  {item.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <p className="text-muted-foreground text-xs">{details.description}</p>
        </div>

        {!post && !loading && !error && (
          <div className="text-muted-foreground flex min-h-0 flex-1 items-center justify-center text-center text-sm">
            Le fil de trois posts offre assez d’espace pour la règle, ses
            nuances et les références, tout en restant visible comme un ensemble
            sur X.
          </div>
        )}

        {loading && !post && (
          <div
            className="text-muted-foreground flex min-h-0 flex-1 flex-col items-center justify-center gap-3"
            role="status"
          >
            <Loader2 className="text-primary size-7 animate-spin" />
            <p className="text-sm">Génération de la publication…</p>
          </div>
        )}

        {error && !post && (
          <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-4 text-center">
            <AlertTriangle className="text-destructive size-7" />
            <p className="text-muted-foreground max-w-md text-sm">{error}</p>
            <Button variant="outline" onClick={requestPost} disabled={loading}>
              {loading ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <RefreshCw className="size-4" />
              )}
              Réessayer
            </Button>
          </div>
        )}

        {post && (
          <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto pr-1 lg:overflow-hidden">
            {(post.warnings.length > 0 ||
              post.visual_warnings.length > 0 ||
              exportError) && (
              <div
                className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-2.5 text-amber-900 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-200"
                role="alert"
              >
                <div className="flex gap-2">
                  <AlertTriangle className="mt-0.5 size-4 shrink-0" />
                  <ul className="space-y-1 text-xs">
                    {[...post.warnings, ...post.visual_warnings].map(
                      (warning, index) => (
                        <li key={`${index}-${warning}`}>{warning}</li>
                      )
                    )}
                    {exportError && <li>{exportError}</li>}
                  </ul>
                </div>
              </div>
            )}

            <div className="grid gap-4 lg:min-h-0 lg:flex-1 lg:grid-cols-[minmax(340px,0.72fr)_minmax(0,1.8fr)]">
              <section className="space-y-3 rounded-xl border p-4 lg:min-h-0 lg:overflow-y-auto">
                <div>
                  <h3 className="font-semibold">Texte de la publication</h3>
                  <p className="text-muted-foreground text-xs">
                    Le texte est compatible avec un compte X gratuit.
                  </p>
                </div>
                <textarea
                  aria-label="Publication X générée"
                  value={post.content}
                  readOnly
                  spellCheck={false}
                  className="border-input bg-background text-foreground focus-visible:ring-ring min-h-80 w-full resize-y rounded-lg border p-4 text-sm leading-6 focus-visible:ring-2 focus-visible:outline-none lg:min-h-[58dvh]"
                />
                <p
                  className={cn(
                    "text-muted-foreground text-right text-xs tabular-nums",
                    overLimit && "text-destructive font-medium"
                  )}
                >
                  {format === "thread"
                    ? `${post.character_count.toLocaleString("fr-FR")} caractères au total · 280 maximum par post`
                    : `${post.character_count.toLocaleString("fr-FR")} / ${details.limit?.toLocaleString("fr-FR")} caractères`}
                </p>
              </section>

              <section className="space-y-3 rounded-xl border p-4 lg:min-h-0 lg:overflow-y-auto">
                <div>
                  <h3 className="font-semibold">Visuel X</h3>
                  <p className="text-muted-foreground text-xs">
                    Carte horizontale AORIA RH, 1260 × 675 pixels, à joindre au
                    premier post.
                  </p>
                </div>

                {html ? (
                  <>
                    <details className="rounded-lg border">
                      <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2.5 text-sm font-medium">
                        <Code2 className="size-4" />
                        Modifier le HTML du visuel
                      </summary>
                      <div className="space-y-2 border-t p-3">
                        <div className="flex justify-end">
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={handleResetHtml}
                            disabled={!htmlModified || rendering}
                          >
                            <RotateCcw className="size-4" />
                            Revenir au HTML généré
                          </Button>
                        </div>
                        <textarea
                          aria-label="HTML du visuel X"
                          value={html}
                          onChange={(event) => setHtml(event.target.value)}
                          spellCheck={false}
                          className="border-input bg-background text-foreground focus-visible:ring-ring min-h-72 w-full resize-y rounded-lg border p-4 font-mono text-xs leading-5 focus-visible:ring-2 focus-visible:outline-none"
                        />
                      </div>
                    </details>

                    <ExportPreview
                      html={html}
                      messageId={messageId}
                      token={token}
                      active={open}
                      title="Aperçu du visuel X"
                    />

                    <details className="rounded-lg border">
                      <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2.5 text-sm font-medium">
                        <FileCode2 className="size-4" />
                        Voir la sortie brute du visuel
                      </summary>
                      <div className="space-y-2 border-t p-3">
                        <p className="text-muted-foreground text-xs">
                          Cette sortie est exactement celle reçue du LLM.
                        </p>
                        <textarea
                          aria-label="Sortie brute du visuel X"
                          value={post.visual_raw_content ?? ""}
                          readOnly
                          spellCheck={false}
                          className="border-input bg-muted/30 text-foreground min-h-48 w-full resize-y rounded-lg border p-4 font-mono text-xs leading-5"
                        />
                      </div>
                    </details>
                  </>
                ) : (
                  <p className="text-muted-foreground rounded-lg border border-dashed p-4 text-sm">
                    Le visuel n’est pas disponible. Le texte généré reste
                    intégralement accessible.
                  </p>
                )}
              </section>
            </div>
          </div>
        )}

        <DialogFooter className="mt-auto shrink-0">
          {!post ? (
            <Button onClick={requestPost} disabled={loading || !token}>
              {loading && <Loader2 className="size-4 animate-spin" />}
              Générer
            </Button>
          ) : (
            <>
              <Button
                variant="outline"
                onClick={handleRegenerate}
                disabled={loading}
              >
                {loading ? (
                  <Loader2 className="size-4 animate-spin" />
                ) : (
                  <RefreshCw className="size-4" />
                )}
                Régénérer
              </Button>
              <Button
                variant="outline"
                onClick={handleDownloadHtml}
                disabled={!html || rendering}
              >
                <FileCode2 className="size-4" />
                Télécharger le HTML
              </Button>
              <Button
                variant="outline"
                onClick={handleDownloadPng}
                disabled={!html || rendering}
              >
                {rendering ? (
                  <Loader2 className="size-4 animate-spin" />
                ) : (
                  <Download className="size-4" />
                )}
                {rendering ? "Préparation du PNG…" : "Télécharger le PNG"}
              </Button>
              <Button onClick={handleCopy} disabled={loading}>
                {copied ? (
                  <Check className="size-4" />
                ) : (
                  <Copy className="size-4" />
                )}
                {copied ? "Publication copiée" : "Copier la publication"}
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
