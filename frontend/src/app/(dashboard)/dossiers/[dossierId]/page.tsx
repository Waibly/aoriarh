"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useSession } from "next-auth/react";
import { Ellipsis, MessageSquare } from "lucide-react";
import { useOrg } from "@/lib/org-context";
import { apiFetch } from "@/lib/api";
import { createConversation, deleteConversation } from "@/lib/chat-api";
import {
  dossierChanged,
  dossierOperation,
  getDossier,
  uploadDossierDocument,
  type DossierDetail,
} from "@/lib/dossiers-api";
import { DeleteDossierDialog } from "@/components/dossiers/delete-dossier-dialog";
import { DossierContent } from "@/components/dossiers/dossier-content";
import {
  ChatWelcomeLayout,
  ChatWelcomeHeading,
} from "@/components/chat/chat-welcome-layout";
import { ChatInput } from "@/components/chat/chat-input";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import type { Conversation } from "@/types/api";

export default function DossierPage() {
  const { dossierId } = useParams<{ dossierId: string }>();
  const { currentOrg } = useOrg();
  return (
    <DossierWorkspace
      key={`${currentOrg?.id}:${dossierId}`}
      dossierId={dossierId}
    />
  );
}

function DossierWorkspace({ dossierId }: { dossierId: string }) {
  const router = useRouter();
  const params = useSearchParams();
  const { currentOrg } = useOrg();
  const organisationId = currentOrg?.id;
  const editRequested = params.get("edit") === "1";
  const { data: session } = useSession();
  const token = session?.access_token;
  const [d, setD] = useState<DossierDetail | null>(null);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const [tab, setTab] = useState<
    "conversations" | "informations" | "documents"
  >("conversations");
  const [busy, setBusy] = useState(false);
  const starting = useRef(false);
  const [edit, setEdit] = useState(false);
  const [deleteDossier, setDeleteDossier] = useState(false);
  const [name, setName] = useState("");
  const [query, setQuery] = useState("");
  const [target, setTarget] = useState<Conversation | null>(null);
  const [rename, setRename] = useState<Conversation | null>(null);
  const [title, setTitle] = useState("");
  const [offset, setOffset] = useState(0);
  useEffect(() => {
    let cancelled = false;
    setError("");
    if (!token || !organisationId) return;
    const timer = setTimeout(
      () => {
        void getDossier(dossierId, token, 0, query)
          .then((data) => {
            if (cancelled) return;
            if (data.organisation_id !== organisationId) {
              router.replace("/dossiers");
              return;
            }
            setD(data);
            setName(data.name);
            setOffset(0);
          })
          .catch((e) => {
            if (!cancelled) setError(e.message);
          });
      },
      query ? 250 : 0
    );
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [dossierId, token, organisationId, revision, query, router]);
  useEffect(() => {
    if (editRequested) setEdit(true);
  }, [editRequested]);
  async function update(values: object) {
    if (!d || !token) return;
    setBusy(true);
    setError("");
    try {
      const next = await dossierOperation(
        d.id,
        token,
        "",
        { expected_version: d.version, ...values },
        "PATCH"
      );
      setD(next);
      return true;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Enregistrement impossible");
      return false;
    } finally {
      setBusy(false);
    }
  }
  async function send(content: string) {
    if (!d || !token || starting.current) return false;
    starting.current = true;
    setBusy(true);
    setError("");
    try {
      const c = await createConversation(
        d.organisation_id,
        token,
        undefined,
        d.id
      );
      sessionStorage.setItem(`chat-initial:${c.id}`, content);
      dossierChanged();
      router.push(`/chat/${c.id}`);
      return true;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Conversation impossible");
      starting.current = false;
      setBusy(false);
      return false;
    }
  }
  if (!d || !token)
    return (
      <div role={error ? "alert" : "status"} className="bg-card rounded-xl p-6">
        {error || "Chargement du dossier…"}
        {error && (
          <Button
            className="ml-3"
            variant="outline"
            onClick={() => setRevision((v) => v + 1)}
          >
            Réessayer
          </Button>
        )}
      </div>
    );
  return (
    <ChatWelcomeLayout
      verticallyCentered={false}
      header={
        <>
          <Link
            href="/dossiers"
            className="text-muted-foreground hover:text-foreground text-sm"
          >
            ← Dossiers
          </Link>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                size="icon"
                variant="outline"
                aria-label="Actions du dossier"
              >
                <Ellipsis className="size-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent>
              {!d.archived_at && (
                <>
                  <DropdownMenuItem
                    onSelect={() => {
                      setName(d.name);
                      setEdit(true);
                    }}
                  >
                    Renommer
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    onSelect={() => void update({ pinned: !d.pinned })}
                  >
                    {d.pinned ? "Désépingler" : "Épingler"}
                  </DropdownMenuItem>
                </>
              )}
              <DropdownMenuItem
                className="text-destructive"
                onSelect={() => setDeleteDossier(true)}
              >
                Supprimer
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </>
      }
    >
      <ChatWelcomeHeading
        title={d.name}
        badge={`Dossier personnel · ${currentOrg?.name ?? ""}`}
        description={
          d.description ||
          "Retrouvez le contexte de votre dossier et poursuivez vos échanges avec AORIA RH."
        }
      />

      {error && (
        <p role="alert" className="text-destructive mb-4 text-sm">
          {error}
        </p>
      )}
      {d.archived_at ? (
        <div className="bg-muted mb-6 rounded-lg p-4 text-sm">
          Ce dossier est archivé.{" "}
        </div>
      ) : (
        <div className="mx-auto mb-8 w-full max-w-3xl">
          <ChatInput
            variant="welcome"
            draftKey={`dossier:${d.id}`}
            placeholder="Poser une question dans ce dossier…"
            onSend={send}
            disabled={busy}
            attachmentScope="dossier"
            onAttach={async (file) => {
              setBusy(true);
              setError("");
              try {
                setD(await uploadDossierDocument(d.id, token, file));
                setTab("documents");
              } catch (e) {
                setError(e instanceof Error ? e.message : "Import impossible");
                try {
                  setD(await getDossier(d.id, token));
                  setTab("documents");
                } catch {
                  /* Keep the import error visible. */
                }
              } finally {
                setBusy(false);
              }
            }}
          />
        </div>
      )}
      <div
        className="mb-5 grid w-full grid-cols-3 gap-2 border-b"
        role="tablist"
        aria-label="Contenu du dossier"
      >
        {(["conversations", "informations", "documents"] as const).map((t) => (
          <Button
            key={t}
            role="tab"
            className={`w-full min-w-0 rounded-none border-b-2 px-1 text-xs sm:text-sm ${tab === t ? "border-primary text-primary hover:bg-primary/5" : "text-muted-foreground hover:bg-muted/50 border-transparent"}`}
            aria-selected={tab === t}
            variant="ghost"
            onClick={() => setTab(t)}
          >
            {
              {
                conversations: "Conversations",
                informations: "Informations",
                documents: "Documents",
              }[t]
            }
          </Button>
        ))}
      </div>
      {tab === "conversations" ? (
        <div className="space-y-4">
          {(d.conversation_count > 0 || query) && (
            <Input
              aria-label="Rechercher une conversation"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Rechercher une conversation"
            />
          )}
          {!d.conversations.length && (
            <p className="text-muted-foreground py-6 text-center text-sm">
              {query
                ? "Aucune conversation ne correspond à votre recherche."
                : "Aucune conversation pour le moment. Posez votre première question ci-dessus."}
            </p>
          )}
          {d.conversations.map((c) => (
            <div key={c.id} className="flex items-center rounded-lg border p-3">
              <Link
                className="flex min-w-0 flex-1 items-center gap-3"
                href={`/chat/${c.id}`}
              >
                <MessageSquare className="text-muted-foreground size-4 shrink-0" />
                <span className="min-w-0">
                  <span className="block truncate text-sm font-medium">
                    {c.title || "Nouvelle conversation"}
                  </span>
                  <span className="text-muted-foreground text-xs">
                    {new Date(c.updated_at).toLocaleDateString("fr-FR")}
                  </span>
                </span>
              </Link>
              {!d.archived_at && (
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button
                      size="icon"
                      variant="ghost"
                      aria-label={`Actions pour ${c.title || "la conversation"}`}
                    >
                      <Ellipsis className="size-4" />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent>
                    <DropdownMenuItem
                      onSelect={() => {
                        setRename(c);
                        setTitle(c.title || "");
                      }}
                    >
                      Renommer
                    </DropdownMenuItem>
                    <DropdownMenuItem onSelect={() => setTarget(c)}>
                      Supprimer
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              )}
            </div>
          ))}
          {d.has_more && (
            <Button
              variant="outline"
              disabled={busy}
              onClick={async () => {
                setBusy(true);
                try {
                  const next = await getDossier(
                    d.id,
                    token,
                    offset + 50,
                    query
                  );
                  setD({
                    ...next,
                    conversations: [...d.conversations, ...next.conversations],
                  });
                  setOffset((v) => v + 50);
                } catch (e) {
                  setError((e as Error).message);
                } finally {
                  setBusy(false);
                }
              }}
            >
              Afficher plus de conversations
            </Button>
          )}
        </div>
      ) : (
        <DossierContent
          key={d.id}
          dossier={d}
          token={token}
          tab={tab}
          onChange={setD}
        />
      )}
      <Dialog
        open={edit}
        onOpenChange={(v) => {
          if (!busy) setEdit(v);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Renommer le dossier</DialogTitle>
            <DialogDescription>
              Choisissez un nom pour retrouver ce sujet RH.
            </DialogDescription>
          </DialogHeader>
          <form
            className="space-y-4"
            onSubmit={(e) => {
              e.preventDefault();
              void update({ name }).then((ok) => {
                if (ok) setEdit(false);
              });
            }}
          >
            <Input
              aria-label="Nom du dossier"
              value={name}
              onChange={(e) => setName(e.target.value)}
              maxLength={200}
            />
            <Button disabled={busy || !name.trim()}>Enregistrer</Button>
            {error && <p role="alert">{error}</p>}
          </form>
        </DialogContent>
      </Dialog>
      <Dialog
        open={!!rename}
        onOpenChange={(v) => {
          if (!v && !busy) setRename(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Renommer la conversation</DialogTitle>
            <DialogDescription>
              Le titre change dans les historiques de conversation.
            </DialogDescription>
          </DialogHeader>
          <Input
            aria-label="Titre de la conversation"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
          <Button
            disabled={busy || !title.trim()}
            onClick={async () => {
              setBusy(true);
              try {
                await apiFetch(`/conversations/${rename!.id}`, {
                  token,
                  method: "PATCH",
                  body: JSON.stringify({ title }),
                });
                setRename(null);
                dossierChanged();
                setRevision((v) => v + 1);
              } catch (e) {
                setError((e as Error).message);
              } finally {
                setBusy(false);
              }
            }}
          >
            Enregistrer
          </Button>
          {error && <p role="alert">{error}</p>}
        </DialogContent>
      </Dialog>
      <Dialog
        open={!!target}
        onOpenChange={(v) => {
          if (!v && !busy) setTarget(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Supprimer la conversation</DialogTitle>
            <DialogDescription>
              « {target?.title || "Nouvelle conversation"} » disparaîtra de
              votre historique. Les informations et documents déjà ajoutés au
              dossier resteront conservés. Les traces suivent la politique de
              conservation existante.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setTarget(null)}
              disabled={busy}
            >
              Annuler
            </Button>
            <Button
              variant="destructive"
              disabled={busy}
              onClick={async () => {
                setBusy(true);
                try {
                  await deleteConversation(target!.id, token);
                  setTarget(null);
                  dossierChanged();
                  setRevision((v) => v + 1);
                } catch (e) {
                  setError((e as Error).message);
                } finally {
                  setBusy(false);
                }
              }}
            >
              Supprimer
            </Button>
          </DialogFooter>
          {error && <p role="alert">{error}</p>}
        </DialogContent>
      </Dialog>
      <DeleteDossierDialog
        dossier={deleteDossier ? d : null}
        token={token!}
        onClose={() => setDeleteDossier(false)}
        onDeleted={() => router.push("/dossiers")}
      />
    </ChatWelcomeLayout>
  );
}
