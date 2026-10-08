"use client";

import { useCallback, useEffect, useId, useState } from "react";
import Link from "next/link";
import { useRouter, usePathname } from "next/navigation";
import { useSession } from "next-auth/react";
import {
  ChevronDown,
  ChevronRight,
  FolderOpen,
  Plus,
  Ellipsis,
} from "lucide-react";
import { useOrg } from "@/lib/org-context";
import {
  dossierOperation,
  listRecentDossiers,
  type Dossier,
} from "@/lib/dossiers-api";
import { getConversation } from "@/lib/chat-api";
import { DeleteDossierDialog } from "./delete-dossier-dialog";
import { CreateDossierDialog } from "./create-dossier-dialog";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";
import { toast } from "sonner";

export function DossiersSidebar() {
  const { currentOrg } = useOrg();
  const organisationId = currentOrg?.id;
  const listId = useId();
  const { data: session } = useSession();
  const token = session?.access_token;
  const path = usePathname();
  const router = useRouter();
  const [deleteTarget, setDeleteTarget] = useState<Dossier | null>(null);
  const [rows, setRows] = useState<Dossier[]>([]);
  const [expanded, setExpanded] = useState(true);
  const [create, setCreate] = useState(false);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [error, setError] = useState(false);
  const [revision, setRevision] = useState(0);
  const reload = useCallback(() => setRevision((v) => v + 1), []);
  useEffect(() => {
    window.addEventListener("dossiers-updated", reload);
    window.addEventListener("conversation-updated", reload);
    return () => {
      window.removeEventListener("dossiers-updated", reload);
      window.removeEventListener("conversation-updated", reload);
    };
  }, [reload]);
  useEffect(() => {
    let cancelled = false;
    setRows([]);
    setActiveId(null);
    setError(false);
    if (!token || !organisationId) return;
    void (async () => {
      try {
        const list = await listRecentDossiers(organisationId, token);
        let id = path.startsWith("/dossiers/") ? path.split("/")[2] : null;
        if (path.startsWith("/chat/"))
          id =
            (await getConversation(path.split("/")[2], token)).dossier_id ??
            null;
        if (!cancelled) {
          setRows(list.items);
          setActiveId(id);
        }
      } catch {
        if (!cancelled) setError(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [organisationId, token, path, revision]);
  if (!token || !currentOrg) return null;
  return (
    <section
      aria-label="Dossiers récents"
      className="w-full space-y-1 px-3 pt-3 pb-4"
    >
      <div className="group/dossiers flex items-center justify-between px-1">
        <button
          type="button"
          aria-label={
            expanded ? "Replier les dossiers" : "Déplier les dossiers"
          }
          aria-expanded={expanded}
          aria-controls={listId}
          className="text-muted-foreground hover:text-foreground focus-visible:ring-ring inline-flex h-8 items-center gap-1 rounded px-1 text-xs font-medium focus-visible:ring-1 focus-visible:outline-none"
          onClick={() => setExpanded(!expanded)}
        >
          Dossiers
          {expanded ? (
            <ChevronDown aria-hidden="true" className="size-3" />
          ) : (
            <ChevronRight aria-hidden="true" className="size-3" />
          )}
        </button>
        <Button
          variant="ghost"
          size="icon"
          className="size-8 opacity-100 group-focus-within/dossiers:opacity-100 focus:opacity-100 [@media(hover:hover)]:opacity-0 [@media(hover:hover)]:group-hover/dossiers:opacity-100"
          title="Créer un dossier"
          aria-label="Créer un dossier"
          onClick={() => setCreate(true)}
        >
          <Plus className="size-4" />
        </Button>
      </div>
      {expanded && (
        <div id={listId} className="space-y-0.5">
          {error && (
            <button className="text-destructive px-2 text-xs" onClick={reload}>
              Chargement impossible · Réessayer
            </button>
          )}
          {rows.map((d) => (
            <div key={d.id}>
              <div
                className={cn(
                  "group flex items-center rounded-md text-sm",
                  activeId === d.id ? "bg-accent" : "hover:bg-accent/50"
                )}
              >
                <Link
                  href={`/dossiers/${d.id}`}
                  title={d.name}
                  className="flex min-w-0 flex-1 items-center gap-2 px-2 py-2"
                >
                  <FolderOpen
                    aria-hidden="true"
                    className="text-muted-foreground size-4 shrink-0"
                  />
                  <span className="truncate">{d.name}</span>
                </Link>
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="size-7"
                      aria-label={`Actions pour ${d.name}`}
                    >
                      <Ellipsis className="size-3.5" />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent>
                    <DropdownMenuItem asChild>
                      <Link href={`/dossiers/${d.id}?edit=1`}>Renommer</Link>
                    </DropdownMenuItem>
                    <DropdownMenuItem
                      onSelect={() =>
                        void dossierOperation(
                          d.id,
                          token,
                          "",
                          { expected_version: d.version, pinned: !d.pinned },
                          "PATCH"
                        ).catch((e) => toast.error(e.message))
                      }
                    >
                      {d.pinned ? "Désépingler" : "Épingler"}
                    </DropdownMenuItem>
                    <DropdownMenuItem
                      className="text-destructive"
                      onSelect={() => setDeleteTarget(d)}
                    >
                      Supprimer
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              </div>
            </div>
          ))}
          <Link
            href="/dossiers"
            className="text-muted-foreground block px-2 py-1.5 text-xs"
          >
            Voir tous les dossiers
          </Link>
        </div>
      )}
      <DeleteDossierDialog
        dossier={deleteTarget}
        token={token}
        onClose={() => setDeleteTarget(null)}
        onDeleted={() => {
          if (
            activeId === deleteTarget?.id ||
            path === `/dossiers/${deleteTarget?.id}`
          ) {
            setActiveId(null);
            router.push("/dossiers");
          }
        }}
      />
      <CreateDossierDialog
        open={create}
        onOpenChange={setCreate}
        organisationId={currentOrg.id}
        organisationName={currentOrg.name}
        token={token}
      />
    </section>
  );
}
