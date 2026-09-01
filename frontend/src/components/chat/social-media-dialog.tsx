"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Image from "next/image";
import {
  AlertTriangle,
  Code2,
  Download,
  FileArchive,
  FileCode2,
  Images,
  Loader2,
  RefreshCw,
  RotateCcw,
} from "lucide-react";
import { zipSync } from "fflate";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  generateSocialMedia,
  renderSocialMediaHtml,
  type SocialMediaGenerationResult,
  type SocialMediaImageResult,
} from "@/lib/chat-api";
import { cn } from "@/lib/utils";

interface SocialMediaDialogProps {
  messageId: string;
  token: string | undefined;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

function base64ToBytes(value: string): Uint8Array {
  const binary = window.atob(value);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return bytes;
}

function bytesToArrayBuffer(bytes: Uint8Array): ArrayBuffer {
  const copy = new Uint8Array(bytes.byteLength);
  copy.set(bytes);
  return copy.buffer;
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

function imageDataUrl(image: SocialMediaImageResult): string {
  return `data:image/png;base64,${image.content_base64}`;
}

export function SocialMediaDialog({
  messageId,
  token,
  open,
  onOpenChange,
}: SocialMediaDialogProps) {
  const [generation, setGeneration] =
    useState<SocialMediaGenerationResult | null>(null);
  const [html, setHtml] = useState("");
  const [renderedHtml, setRenderedHtml] = useState<string | null>(null);
  const [images, setImages] = useState<SocialMediaImageResult[]>([]);
  const [activeImage, setActiveImage] = useState(0);
  const [loading, setLoading] = useState(false);
  const [rendering, setRendering] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [renderError, setRenderError] = useState<string | null>(null);
  const inFlightRef = useRef(false);

  const requestGeneration = useCallback(async () => {
    if (inFlightRef.current) return;
    if (!token) {
      setError("Session indisponible. Veuillez actualiser la page.");
      return;
    }

    inFlightRef.current = true;
    setLoading(true);
    setError(null);
    setRenderError(null);
    try {
      const result = await generateSocialMedia(messageId, token);
      setGeneration(result);
      setHtml(result.html);
      setImages(result.images);
      setRenderedHtml(result.images.length > 0 ? result.html : null);
      setRenderError(result.render_error);
      setActiveImage(0);
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : "La génération du média a échoué."
      );
    } finally {
      inFlightRef.current = false;
      setLoading(false);
    }
  }, [messageId, token]);

  useEffect(() => {
    if (open && !generation && !error && !inFlightRef.current) {
      void requestGeneration();
    }
  }, [error, generation, open, requestGeneration]);

  const htmlModified = generation !== null && html !== generation.html;
  const pngOutdated = renderedHtml === null || html !== renderedHtml;
  const currentImage = images[activeImage] ?? null;

  const handleRender = useCallback(async () => {
    if (!token || !html || rendering) return;
    setRendering(true);
    setRenderError(null);
    try {
      const result = await renderSocialMediaHtml(messageId, html, token);
      setImages(result.images);
      setRenderedHtml(html);
      setActiveImage(0);
    } catch (requestError) {
      setRenderError(
        requestError instanceof Error
          ? requestError.message
          : "Le rendu PNG a échoué. Le HTML reste disponible sans modification."
      );
    } finally {
      setRendering(false);
    }
  }, [html, messageId, rendering, token]);

  const handleRetry = useCallback(() => {
    setError(null);
    void requestGeneration();
  }, [requestGeneration]);

  const handleRegenerate = useCallback(() => {
    if (
      htmlModified &&
      !window.confirm(
        "Le HTML a été modifié. Une nouvelle génération remplacera ces modifications. Continuer ?"
      )
    ) {
      return;
    }
    setGeneration(null);
    setHtml("");
    setRenderedHtml(null);
    setImages([]);
    setActiveImage(0);
    setError(null);
    setRenderError(null);
    void requestGeneration();
  }, [htmlModified, requestGeneration]);

  const handleResetHtml = useCallback(() => {
    if (!generation) return;
    setHtml(generation.html);
    setRenderError(generation.render_error);
  }, [generation]);

  const handleDownloadHtml = useCallback(() => {
    downloadBlob(
      new Blob([html], { type: "text/html;charset=utf-8" }),
      "aoria-media.html"
    );
  }, [html]);

  const handleDownloadImage = useCallback(() => {
    if (!currentImage || pngOutdated) return;
    downloadBlob(
      new Blob(
        [bytesToArrayBuffer(base64ToBytes(currentImage.content_base64))],
        {
          type: "image/png",
        }
      ),
      currentImage.filename
    );
  }, [currentImage, pngOutdated]);

  const handleDownloadPngs = useCallback(() => {
    if (images.length === 0 || pngOutdated) return;
    const files = Object.fromEntries(
      images.map((image) => [
        image.filename,
        base64ToBytes(image.content_base64),
      ])
    );
    downloadBlob(
      new Blob([bytesToArrayBuffer(zipSync(files))], {
        type: "application/zip",
      }),
      "aoria-media-png.zip"
    );
  }, [images, pngOutdated]);

  const warnings = useMemo(() => generation?.warnings ?? [], [generation]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex h-[94dvh] max-h-[94dvh] flex-col sm:max-w-6xl">
        <DialogHeader>
          <DialogTitle>Générer un média</DialogTitle>
          <DialogDescription>
            Le HTML produit par le modèle reste visible, éditable et
            téléchargeable sans correction automatique.
          </DialogDescription>
        </DialogHeader>

        {loading && !generation && (
          <div
            className="text-muted-foreground flex min-h-0 flex-1 flex-col items-center justify-center gap-3"
            role="status"
          >
            <Loader2 className="text-primary size-7 animate-spin" />
            <p className="text-sm">Génération du média et des aperçus…</p>
          </div>
        )}

        {error && !generation && (
          <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-4 text-center">
            <AlertTriangle className="text-destructive size-7" />
            <p className="text-muted-foreground max-w-md text-sm">{error}</p>
            <Button variant="outline" onClick={handleRetry} disabled={loading}>
              <RefreshCw className="size-4" />
              Réessayer
            </Button>
          </div>
        )}

        {generation && (
          <div className="flex min-h-0 flex-1 flex-col gap-3">
            {(warnings.length > 0 || renderError) && (
              <div
                className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-2.5 text-amber-900 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-200"
                role="alert"
              >
                <div className="flex gap-2">
                  <AlertTriangle className="mt-0.5 size-4 shrink-0" />
                  <ul className="space-y-1 text-xs">
                    {warnings.map((warning, index) => (
                      <li key={`${index}-${warning}`}>{warning}</li>
                    ))}
                    {renderError && <li>{renderError}</li>}
                  </ul>
                </div>
              </div>
            )}

            <Tabs defaultValue="preview" className="min-h-0 flex-1">
              <TabsList>
                <TabsTrigger value="preview">
                  <Images className="size-4" />
                  Aperçu
                </TabsTrigger>
                <TabsTrigger value="html">
                  <Code2 className="size-4" />
                  Modifier le HTML
                </TabsTrigger>
                <TabsTrigger value="raw">
                  <FileCode2 className="size-4" />
                  Sortie brute du LLM
                </TabsTrigger>
              </TabsList>

              <TabsContent value="preview" className="min-h-0 overflow-auto">
                {images.length > 0 ? (
                  <div className="grid min-h-0 gap-4 lg:grid-cols-[150px_minmax(0,1fr)]">
                    <div className="flex gap-2 overflow-x-auto lg:max-h-[66dvh] lg:flex-col lg:overflow-y-auto">
                      {images.map((image, index) => (
                        <button
                          type="button"
                          key={image.filename}
                          onClick={() => setActiveImage(index)}
                          aria-label={`Afficher l'image ${index + 1}`}
                          className={cn(
                            "shrink-0 overflow-hidden rounded-md border-2 bg-white transition-colors",
                            activeImage === index
                              ? "border-primary"
                              : "border-transparent"
                          )}
                        >
                          <Image
                            src={imageDataUrl(image)}
                            alt={`Aperçu ${index + 1}`}
                            width={1080}
                            height={1350}
                            unoptimized
                            className="h-28 w-auto object-contain lg:h-auto lg:w-full"
                          />
                        </button>
                      ))}
                    </div>
                    <div className="flex min-h-0 flex-col items-center gap-2 overflow-auto rounded-lg border bg-neutral-100 p-3 dark:bg-neutral-950">
                      {currentImage && (
                        <Image
                          src={imageDataUrl(currentImage)}
                          alt={`Média AORIA RH ${activeImage + 1}`}
                          width={1080}
                          height={1350}
                          unoptimized
                          className="max-h-[62dvh] max-w-full rounded-md object-contain shadow-sm"
                        />
                      )}
                      <p className="text-muted-foreground text-xs tabular-nums">
                        {activeImage + 1} / {images.length}
                      </p>
                    </div>
                  </div>
                ) : (
                  <div className="text-muted-foreground flex h-full min-h-64 flex-col items-center justify-center gap-3 text-center">
                    <Images className="size-8" />
                    <p className="max-w-md text-sm">
                      Aucun PNG n’est disponible. Le HTML généré reste
                      accessible dans l’éditeur et peut être rendu à nouveau.
                    </p>
                  </div>
                )}
              </TabsContent>

              <TabsContent value="html" className="flex min-h-0 flex-col gap-2">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="text-muted-foreground text-xs">
                    Les modifications restent locales jusqu’au prochain rendu
                    PNG.
                  </p>
                  <div className="flex gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={handleResetHtml}
                      disabled={!htmlModified || rendering}
                    >
                      <RotateCcw className="size-4" />
                      Revenir au HTML généré
                    </Button>
                    <Button
                      size="sm"
                      onClick={handleRender}
                      disabled={rendering || !html}
                    >
                      {rendering ? (
                        <Loader2 className="size-4 animate-spin" />
                      ) : (
                        <Images className="size-4" />
                      )}
                      {rendering ? "Rendu…" : "Rendre les PNG"}
                    </Button>
                  </div>
                </div>
                {pngOutdated && (
                  <p className="rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-900 dark:bg-amber-950/40 dark:text-amber-200">
                    Le HTML visible ne correspond pas aux PNG actuels. Lancez le
                    rendu pour appliquer exactement cette version.
                  </p>
                )}
                <textarea
                  aria-label="HTML du média"
                  value={html}
                  onChange={(event) => setHtml(event.target.value)}
                  spellCheck={false}
                  className="border-input bg-background text-foreground focus-visible:ring-ring min-h-0 flex-1 resize-none rounded-lg border p-4 font-mono text-xs leading-5 focus-visible:ring-2 focus-visible:outline-none"
                />
              </TabsContent>

              <TabsContent value="raw" className="flex min-h-0 flex-col gap-2">
                <p className="text-muted-foreground text-xs">
                  Cette sortie est exactement celle reçue du LLM. Elle n’est ni
                  nettoyée, ni complétée, ni remplacée par le HTML édité.
                </p>
                <textarea
                  aria-label="Sortie brute du LLM"
                  value={generation.raw_content}
                  readOnly
                  spellCheck={false}
                  className="border-input bg-muted/30 text-foreground min-h-0 flex-1 resize-none rounded-lg border p-4 font-mono text-xs leading-5"
                />
              </TabsContent>
            </Tabs>
          </div>
        )}

        <DialogFooter className="mt-auto shrink-0 flex-wrap">
          <Button
            variant="outline"
            onClick={handleRegenerate}
            disabled={!generation || loading || rendering}
          >
            <RefreshCw className="size-4" />
            Régénérer
          </Button>
          <Button
            variant="outline"
            onClick={handleDownloadHtml}
            disabled={!html}
          >
            <FileCode2 className="size-4" />
            Télécharger le HTML
          </Button>
          <Button
            variant="outline"
            onClick={handleDownloadImage}
            disabled={!currentImage || pngOutdated}
          >
            <Download className="size-4" />
            Télécharger l’image
          </Button>
          <Button
            onClick={handleDownloadPngs}
            disabled={images.length === 0 || pngOutdated}
          >
            <FileArchive className="size-4" />
            Télécharger les PNG
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
