"use client";

import { useState } from "react";
import { useSession } from "next-auth/react";
import { Check, Copy, Loader2, Sparkles } from "lucide-react";
import ReactMarkdown from "react-markdown";
import rehypeSanitize from "rehype-sanitize";
import remarkGfm from "remark-gfm";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { LinkedInFilledIcon } from "@/components/icons/linkedin-filled-icon";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  getLinkedinErrorMessage,
  type LinkedinResult,
  streamLinkedinPost,
} from "@/lib/linkedin-api";
import { cn } from "@/lib/utils";

export default function LinkedinPostPage() {
  const { data: session } = useSession();
  const [topic, setTopic] = useState("");
  const [result, setResult] = useState<LinkedinResult | null>(null);
  const [generating, setGenerating] = useState(false);
  const [copied, setCopied] = useState(false);

  const generate = async () => {
    const cleanTopic = topic.trim();
    if (!cleanTopic) {
      toast.error("Saisis un sujet ou une question");
      return;
    }
    if (!session?.access_token) return;

    setGenerating(true);
    setResult(null);
    setCopied(false);
    let streamedPost = "";
    try {
      await streamLinkedinPost(cleanTopic, session.access_token, {
        onStart: (sources) => {
          setResult({
            post: "",
            character_count: 0,
            sources,
            cost_usd: 0,
            duration_ms: 0,
          });
        },
        onDelta: (content) => {
          streamedPost += content;
          setResult((current) => ({
            post: streamedPost,
            character_count: streamedPost.length,
            sources: current?.sources ?? [],
            cost_usd: current?.cost_usd ?? 0,
            duration_ms: current?.duration_ms ?? 0,
          }));
        },
        onDone: (completedResult) => setResult(completedResult),
        onError: (message) => toast.error(message),
      });
    } catch (error) {
      toast.error(getLinkedinErrorMessage(error));
    } finally {
      setGenerating(false);
    }
  };

  const copyPost = async () => {
    if (!result) return;
    await navigator.clipboard.writeText(result.post);
    setCopied(true);
    toast.success("Post copié");
    window.setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6">
      <div>
        <div className="flex items-center gap-2">
          <LinkedInFilledIcon className="h-6 w-6" />
          <h1 className="text-2xl font-semibold tracking-tight">
            Générateur LinkedIn
          </h1>
        </div>
        <p className="text-muted-foreground mt-2 text-sm">
          Transforme une question RH en post LinkedIn vérifié à partir du corpus
          juridique commun d&apos;AORIA RH.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Sujet du post</CardTitle>
          <CardDescription>
            Pose ta question comme dans le chat. Aucun document privé d&apos;un
            client n&apos;est consulté pour cette génération publique.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="linkedin-topic">Question ou angle éditorial</Label>
            <Textarea
              id="linkedin-topic"
              value={topic}
              onChange={(event) => setTopic(event.target.value)}
              rows={5}
              maxLength={5000}
              placeholder="Ex. Un employeur peut-il refuser une demande de télétravail ?"
              disabled={generating}
            />
          </div>
          <div className="flex justify-end">
            <Button onClick={generate} disabled={generating || !topic.trim()}>
              {generating ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Sparkles className="mr-2 h-4 w-4" />
              )}
              {generating ? "Recherche et rédaction…" : "Générer le post"}
            </Button>
          </div>
        </CardContent>
      </Card>

      {generating && !result && (
        <Card>
          <CardContent className="text-muted-foreground flex items-center gap-3 text-sm">
            <Loader2 className="h-5 w-5 animate-spin" />
            Analyse de la question, sélection des sources et rédaction du post…
          </CardContent>
        </Card>
      )}

      {result && (
        <>
          <Card>
            <CardHeader className="border-b">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <CardTitle>
                    {generating ? "Rédaction en cours…" : "Post prêt à relire"}
                  </CardTitle>
                  <CardDescription className="mt-1">
                    {generating
                      ? "Le texte brut du modèle apparaît au fil de la génération."
                      : "Une validation humaine reste nécessaire avant publication."}
                  </CardDescription>
                </div>
                <Button
                  variant="outline"
                  onClick={copyPost}
                  disabled={generating || !result.post}
                >
                  {copied ? (
                    <Check className="mr-2 h-4 w-4" />
                  ) : (
                    <Copy className="mr-2 h-4 w-4" />
                  )}
                  {copied ? "Copié" : "Copier"}
                </Button>
              </div>
            </CardHeader>
            <CardContent className="space-y-3 pt-6">
              <div className="bg-muted/40 rounded-lg border p-5 text-[15px] leading-7 whitespace-pre-wrap">
                {result.post}
              </div>
              <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
                <span
                  className={cn(
                    "font-medium",
                    result.character_count > 3000
                      ? "text-destructive"
                      : "text-muted-foreground"
                  )}
                >
                  {result.character_count.toLocaleString("fr-FR")} / 3 000
                  caractères
                </span>
                <span className="text-muted-foreground">
                  {generating ? (
                    <span className="flex items-center gap-1.5">
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      Rédaction en cours…
                    </span>
                  ) : (
                    <>
                      Généré en {(result.duration_ms / 1000).toFixed(1)} s ·
                      coût {result.cost_usd.toFixed(4)} $
                    </>
                  )}
                </span>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Sources vérifiées</CardTitle>
              <CardDescription>
                Les références principales sont intégrées au post. Les extraits
                ci-dessous permettent de contrôler le contenu avant publication.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {result.sources.map((source) => (
                <div
                  key={
                    source.document_id +
                    "-" +
                    (source.article_nums?.join("-") ?? "source")
                  }
                  className="rounded-lg border p-4"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="font-medium">{source.document_name}</p>
                    <Badge variant="outline">{source.source_type_label}</Badge>
                    {source.article_nums?.map((article) => (
                      <Badge key={article} variant="secondary">
                        art. {article}
                      </Badge>
                    ))}
                    {source.numero_pourvoi && (
                      <Badge variant="secondary">
                        pourvoi {source.numero_pourvoi}
                      </Badge>
                    )}
                  </div>
                  <div className="prose prose-sm text-muted-foreground mt-2 max-h-24 max-w-none overflow-hidden text-sm leading-6 [&_h1]:my-0 [&_h1]:text-sm [&_h1]:leading-6 [&_h1]:font-semibold [&_h2]:my-0 [&_h2]:text-sm [&_h2]:leading-6 [&_h2]:font-semibold [&_h3]:my-0 [&_h3]:text-sm [&_h3]:leading-6 [&_h3]:font-semibold [&_li]:my-0 [&_li]:leading-6 [&_ol]:my-0 [&_ol]:pl-5 [&_p]:my-0 [&_p]:leading-6 [&_strong]:font-semibold [&_ul]:my-0 [&_ul]:pl-5">
                    <ReactMarkdown
                      remarkPlugins={[remarkGfm]}
                      rehypePlugins={[rehypeSanitize]}
                      skipHtml
                      components={{
                        a: ({ children }) => <span>{children}</span>,
                      }}
                    >
                      {source.excerpt}
                    </ReactMarkdown>
                  </div>
                </div>
              ))}
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}
