"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  Check,
  Code2,
  Copy,
  FileArchive,
  FileCode2,
  FileText,
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
import {
  downloadSocialMediaPdf,
  generateSocialMedia,
  renderSocialMediaHtml,
  type SocialMediaGenerationResult,
  type SocialMediaImageResult,
} from "@/lib/chat-api";

interface SocialMediaDialogProps {
  messageId: string;
  token: string | undefined;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  variant?: "media" | "linkedin-carousel";
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

function downloadPngFiles(images: SocialMediaImageResult[]) {
  if (images.length === 1) {
    const image = images[0];
    downloadBlob(
      new Blob([bytesToArrayBuffer(base64ToBytes(image.content_base64))], {
        type: "image/png",
      }),
      image.filename
    );
    return;
  }

  const files = Object.fromEntries(
    images.map((image) => [image.filename, base64ToBytes(image.content_base64)])
  );
  downloadBlob(
    new Blob([bytesToArrayBuffer(zipSync(files))], {
      type: "application/zip",
    }),
    "aoria-carrousel-linkedin-png.zip"
  );
}

const LIVE_PREVIEW_DEFAULT_WIDTH = 1144;
const LIVE_PREVIEW_DEFAULT_HEIGHT = 1414;

function LiveHtmlPreview({ html, title }: { html: string; title: string }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const [previewSize, setPreviewSize] = useState({
    width: LIVE_PREVIEW_DEFAULT_WIDTH,
    height: LIVE_PREVIEW_DEFAULT_HEIGHT,
  });
  const [scale, setScale] = useState(1);

  useEffect(() => {
    setPreviewSize({
      width: LIVE_PREVIEW_DEFAULT_WIDTH,
      height: LIVE_PREVIEW_DEFAULT_HEIGHT,
    });
  }, [html]);

  const measurePreview = useCallback(() => {
    const container = containerRef.current;
    const iframe = iframeRef.current;
    if (!container || !iframe || container.clientWidth === 0) return;

    const document = iframe.contentDocument;
    const width = Math.max(
      document?.documentElement.scrollWidth ?? 0,
      document?.body.scrollWidth ?? 0,
      LIVE_PREVIEW_DEFAULT_WIDTH
    );
    const height = Math.max(
      document?.documentElement.scrollHeight ?? 0,
      document?.body.scrollHeight ?? 0,
      LIVE_PREVIEW_DEFAULT_HEIGHT
    );

    setPreviewSize({ width, height });
    setScale(Math.min(1, container.clientWidth / width));
  }, []);

  useEffect(() => {
    const container = containerRef.current;
    if (!container || typeof ResizeObserver === "undefined") return;

    const observer = new ResizeObserver(measurePreview);
    observer.observe(container);
    return () => observer.disconnect();
  }, [measurePreview]);

  return (
    <div
      ref={containerRef}
      className="h-[58dvh] min-h-96 overflow-auto rounded-lg border bg-neutral-100 dark:bg-neutral-950"
    >
      <div className="relative" style={{ height: previewSize.height * scale }}>
        <iframe
          ref={iframeRef}
          srcDoc={html}
          title={title}
          sandbox="allow-same-origin"
          onLoad={measurePreview}
          className="absolute top-0 left-0 border-0 bg-white"
          style={{
            width: previewSize.width,
            height: previewSize.height,
            transform: `scale(${scale})`,
            transformOrigin: "top left",
          }}
        />
      </div>
    </div>
  );
}

export function SocialMediaDialog({
  messageId,
  token,
  open,
  onOpenChange,
  variant = "media",
}: SocialMediaDialogProps) {
  const includePost = variant === "linkedin-carousel";
  const [generation, setGeneration] =
    useState<SocialMediaGenerationResult | null>(null);
  const [html, setHtml] = useState("");
  const [loading, setLoading] = useState(false);
  const [rendering, setRendering] = useState(false);
  const [pdfDownloading, setPdfDownloading] = useState(false);
  const [postCopied, setPostCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);
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
    setExportError(null);
    try {
      const result = await generateSocialMedia(messageId, token, includePost);
      setGeneration(result);
      setHtml(result.html);
      setExportError(result.post_error ?? result.render_error);
      setPostCopied(false);
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : includePost
            ? "La génération du post et du carrousel LinkedIn a échoué."
            : "La génération du média a échoué."
      );
    } finally {
      inFlightRef.current = false;
      setLoading(false);
    }
  }, [includePost, messageId, token]);

  useEffect(() => {
    if (open && !generation && !error && !inFlightRef.current) {
      void requestGeneration();
    }
  }, [error, generation, open, requestGeneration]);

  const htmlModified = generation !== null && html !== generation.html;

  const handleRetry = useCallback(() => {
    setError(null);
    void requestGeneration();
  }, [requestGeneration]);

  const handleRegenerate = useCallback(() => {
    if (
      htmlModified &&
      !window.confirm(
        "Le HTML du carrousel a été modifié. Une nouvelle génération remplacera ces modifications. Continuer ?"
      )
    ) {
      return;
    }
    setGeneration(null);
    setHtml("");
    setError(null);
    setExportError(null);
    setPostCopied(false);
    void requestGeneration();
  }, [htmlModified, requestGeneration]);

  const handleResetHtml = useCallback(() => {
    if (!generation) return;
    setHtml(generation.html);
  }, [generation]);

  const handleCopyPost = useCallback(async () => {
    if (!generation?.post) return;
    try {
      await navigator.clipboard.writeText(generation.post.content);
      setPostCopied(true);
      setTimeout(() => setPostCopied(false), 2000);
    } catch {
      setExportError(
        "Impossible de copier le post. Sélectionnez son texte manuellement."
      );
    }
  }, [generation]);

  const handleDownloadHtml = useCallback(() => {
    downloadBlob(
      new Blob([html], { type: "text/html;charset=utf-8" }),
      includePost ? "aoria-carrousel-linkedin.html" : "aoria-media.html"
    );
  }, [html, includePost]);

  const handleDownloadPngs = useCallback(async () => {
    if (!token || !html || rendering) return;
    setRendering(true);
    setExportError(null);
    try {
      const result = await renderSocialMediaHtml(messageId, html, token);
      downloadPngFiles(result.images);
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

  const handleDownloadPdf = useCallback(async () => {
    if (!token || !html || pdfDownloading) return;
    setPdfDownloading(true);
    setExportError(null);
    try {
      const pdf = await downloadSocialMediaPdf(messageId, html, token);
      downloadBlob(
        pdf,
        includePost ? "aoria-carrousel-linkedin.pdf" : "aoria-media.pdf"
      );
    } catch (requestError) {
      setExportError(
        requestError instanceof Error
          ? requestError.message
          : "L’export PDF a échoué. Le HTML reste disponible sans modification."
      );
    } finally {
      setPdfDownloading(false);
    }
  }, [html, includePost, messageId, pdfDownloading, token]);

  const warnings = useMemo(
    () => [
      ...(includePost ? (generation?.post?.warnings ?? []) : []),
      ...(generation?.warnings ?? []),
    ],
    [generation, includePost]
  );

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex h-[94dvh] max-h-[94dvh] w-[96vw] max-w-[96vw] flex-col sm:max-w-[96vw] xl:max-w-[1800px]">
        <DialogHeader>
          <DialogTitle>
            {includePost ? "Post + carrousel LinkedIn" : "Générer un média"}
          </DialogTitle>
          <DialogDescription>
            {includePost
              ? "Copiez d’abord le post d’accompagnement, vérifiez ensuite le carrousel, puis téléchargez le format à publier."
              : "Vérifiez et ajustez le média dans l’aperçu en direct, puis téléchargez le format qui vous convient."}
          </DialogDescription>
        </DialogHeader>

        {loading && !generation && (
          <div
            className="text-muted-foreground flex min-h-0 flex-1 flex-col items-center justify-center gap-3"
            role="status"
          >
            <Loader2 className="text-primary size-7 animate-spin" />
            <p className="text-sm">
              {includePost
                ? "Génération du post et du carrousel…"
                : "Génération du média…"}
            </p>
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
          <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto pr-1 lg:overflow-hidden">
            {(warnings.length > 0 || exportError) && (
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
                    {exportError && <li>{exportError}</li>}
                  </ul>
                </div>
              </div>
            )}

            <div
              className={
                includePost
                  ? "grid gap-4 lg:min-h-0 lg:flex-1 lg:grid-cols-[minmax(340px,0.72fr)_minmax(0,1.8fr)]"
                  : "min-h-0 flex-1 lg:overflow-y-auto"
              }
            >
              {includePost && (
                <section className="space-y-3 rounded-xl border p-4 lg:min-h-0 lg:overflow-y-auto">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <div className="mb-1 flex items-center gap-2">
                        <span className="bg-primary text-primary-foreground flex size-6 items-center justify-center rounded-full text-xs font-semibold">
                          1
                        </span>
                        <h3 className="font-semibold">Post d’accompagnement</h3>
                      </div>
                      <p className="text-muted-foreground text-xs">
                        Une introduction courte qui donne envie de parcourir le
                        carrousel sans répéter ses slides.
                      </p>
                    </div>
                    <Button
                      size="sm"
                      onClick={handleCopyPost}
                      disabled={!generation.post}
                    >
                      {postCopied ? (
                        <Check className="size-4" />
                      ) : (
                        <Copy className="size-4" />
                      )}
                      {postCopied ? "Post copié" : "Copier le post"}
                    </Button>
                  </div>

                  {generation.post ? (
                    <>
                      <textarea
                        aria-label="Post LinkedIn du carrousel"
                        value={generation.post.content}
                        readOnly
                        spellCheck={false}
                        className="border-input bg-background text-foreground min-h-52 w-full resize-y rounded-lg border p-4 text-sm leading-6 lg:min-h-[52dvh]"
                      />
                      <p className="text-muted-foreground text-right text-xs tabular-nums">
                        {generation.post.character_count.toLocaleString(
                          "fr-FR"
                        )}{" "}
                        caractères
                      </p>
                    </>
                  ) : (
                    <p className="text-muted-foreground rounded-lg border border-dashed p-4 text-sm">
                      Le post d’accompagnement n’est pas disponible. Le
                      carrousel généré reste intégralement accessible
                      ci-dessous.
                    </p>
                  )}
                </section>
              )}

              <section className="space-y-3 rounded-xl border p-4 lg:min-h-0 lg:overflow-y-auto">
                <div>
                  <div className="mb-1 flex items-center gap-2">
                    {includePost && (
                      <span className="bg-primary text-primary-foreground flex size-6 items-center justify-center rounded-full text-xs font-semibold">
                        2
                      </span>
                    )}
                    <h3 className="font-semibold">
                      {includePost ? "Carrousel LinkedIn" : "Média"}
                    </h3>
                  </div>
                  <p className="text-muted-foreground text-xs">
                    Cet aperçu unique correspond toujours au HTML actuel. Quand
                    il vous convient, téléchargez directement le PDF ou les PNG.
                  </p>
                </div>

                <details className="rounded-lg border">
                  <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2.5 text-sm font-medium">
                    <Code2 className="size-4" />
                    {includePost
                      ? "Modifier le HTML du carrousel"
                      : "Modifier le HTML du média"}
                  </summary>
                  <div className="space-y-2 border-t p-3">
                    <div className="flex justify-end">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={handleResetHtml}
                        disabled={!htmlModified || rendering || pdfDownloading}
                      >
                        <RotateCcw className="size-4" />
                        Revenir au HTML généré
                      </Button>
                    </div>
                    <textarea
                      aria-label={
                        includePost ? "HTML du carrousel" : "HTML du média"
                      }
                      value={html}
                      onChange={(event) => setHtml(event.target.value)}
                      spellCheck={false}
                      className="border-input bg-background text-foreground focus-visible:ring-ring min-h-80 w-full resize-y rounded-lg border p-4 font-mono text-xs leading-5 focus-visible:ring-2 focus-visible:outline-none"
                    />
                    <p className="text-muted-foreground text-xs">
                      L’aperçu ci-dessous se met à jour directement pendant vos
                      modifications.
                    </p>
                  </div>
                </details>

                <div className="space-y-1.5">
                  <p className="text-muted-foreground text-xs font-medium">
                    {includePost ? "Aperçu du carrousel" : "Aperçu du média"}
                  </p>
                  <LiveHtmlPreview
                    html={html}
                    title={
                      includePost
                        ? "Aperçu du carrousel LinkedIn"
                        : "Aperçu du média"
                    }
                  />
                </div>

                <details className="rounded-lg border">
                  <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2.5 text-sm font-medium">
                    <FileCode2 className="size-4" />
                    {includePost
                      ? "Voir la sortie brute du carrousel"
                      : "Voir la sortie brute du média"}
                  </summary>
                  <div className="space-y-2 border-t p-3">
                    <p className="text-muted-foreground text-xs">
                      Cette sortie est exactement celle reçue du LLM. Elle n’est
                      ni nettoyée, ni complétée, ni remplacée par le HTML édité.
                    </p>
                    <textarea
                      aria-label={
                        includePost
                          ? "Sortie brute du carrousel"
                          : "Sortie brute du média"
                      }
                      value={generation.raw_content}
                      readOnly
                      spellCheck={false}
                      className="border-input bg-muted/30 text-foreground min-h-64 w-full resize-y rounded-lg border p-4 font-mono text-xs leading-5"
                    />
                  </div>
                </details>
              </section>
            </div>
          </div>
        )}

        <DialogFooter className="mt-auto shrink-0 flex-wrap">
          <Button
            variant="outline"
            onClick={handleRegenerate}
            disabled={!generation || loading || rendering || pdfDownloading}
          >
            <RefreshCw className="size-4" />
            {includePost ? "Régénérer l’ensemble" : "Régénérer"}
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
            onClick={handleDownloadPngs}
            disabled={!html || rendering || pdfDownloading}
          >
            {rendering ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <FileArchive className="size-4" />
            )}
            {rendering ? "Préparation des PNG…" : "Télécharger les PNG"}
          </Button>
          <Button
            onClick={handleDownloadPdf}
            disabled={!html || pdfDownloading || rendering}
          >
            {pdfDownloading ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <FileText className="size-4" />
            )}
            {pdfDownloading
              ? "Préparation du PDF…"
              : includePost
                ? "Télécharger le PDF LinkedIn"
                : "Télécharger le PDF"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
