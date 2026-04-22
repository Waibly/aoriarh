"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Loader2 } from "lucide-react";

export default function CgvPage() {
  const [content, setContent] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    fetch("/legal/cgv.md")
      .then((r) => (r.ok ? r.text() : Promise.reject(r.statusText)))
      .then(setContent)
      .catch((e) => setErr(String(e)));
  }, []);

  return (
    <div className="min-h-svh bg-background">
      <header className="border-b">
        <div className="max-w-3xl mx-auto px-6 py-4 flex items-center justify-between">
          <Link href="/" className="font-semibold">
            AORIA RH
          </Link>
          <nav className="text-sm text-muted-foreground flex gap-4">
            <Link href="/pricing" className="hover:text-foreground">Tarifs</Link>
            <Link href="/login" className="hover:text-foreground">Connexion</Link>
          </nav>
        </div>
      </header>
      <main className="max-w-3xl mx-auto px-6 py-10">
        {err ? (
          <p className="text-sm text-destructive">Impossible de charger le document.</p>
        ) : content === null ? (
          <div className="flex items-center gap-2 text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" /> Chargement&hellip;
          </div>
        ) : (
          <article className="prose prose-sm md:prose-base dark:prose-invert max-w-none">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
          </article>
        )}
      </main>
    </div>
  );
}
