"use client";

import { useState, useEffect, useCallback } from "react";
import Image from "next/image";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useSession, signOut } from "next-auth/react";
import {
  MessageSquare,
  FileText,
  Files,
  Building2,
  ShieldCheck,
  Library,
  Database,
  Users,
  UsersRound,
  ChevronRight,
  ChevronsUpDown,
  Settings,
  User,
  LogOut,
  Trash2,
  Crown,
  Gift,
  UserCheck,
  DollarSign,
  TrendingUp,
  Gauge,
  CreditCard,
  Plus,
} from "lucide-react";
import { apiFetch } from "@/lib/api";
import { fetchQuota, type QuotaInfo } from "@/lib/billing-api";
import { PLANS, getPlanLabel, type AnyPlanCode } from "@/lib/plans";
import { Button } from "@/components/ui/button";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { Separator } from "@/components/ui/separator";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { cn } from "@/lib/utils";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { OrgSelector } from "./org-selector";
import { SettingsDialog } from "./settings-dialog";
import { useOrg } from "@/lib/org-context";
import {
  listConversations,
  deleteConversation,
  hideAllConversations,
} from "@/lib/chat-api";
import type { Conversation } from "@/types/api";

const navigation = [
  { name: "Nouvelle recherche", href: "/chat", icon: MessageSquare },
  { name: "Documents", href: "/documents", icon: FileText },
  { name: "Organisation", href: "/organisation", icon: Building2 },
  { name: "Équipe", href: "/team", icon: UsersRound, managerOnly: true },
];

function getInitials(name: string) {
  return name
    .split(" ")
    .map((n) => n[0])
    .join("")
    .toUpperCase()
    .slice(0, 2);
}



function ConversationItem({
  conv,
  isActive,
  onDelete,
}: {
  conv: Conversation;
  isActive: boolean;
  onDelete: (conv: Conversation) => void;
}) {
  const title = conv.title || "Nouvelle conversation";
  return (
    <Tooltip delayDuration={400}>
      <TooltipTrigger asChild>
        <div
          className={cn(
            "group/conv relative flex items-center rounded-md transition-colors",
            isActive ? "bg-accent text-accent-foreground" : "hover:bg-accent/50",
          )}
        >
          <Link
            href={`/chat/${conv.id}`}
            className="flex min-w-0 flex-1 items-center gap-2 px-2 py-1.5"
          >
            <MessageSquare className="size-4 shrink-0 opacity-50" />
            <span className="flex-1 truncate text-left text-sm">
              {title}
            </span>
          </Link>
          <button
            onClick={(e) => {
              e.preventDefault();
              e.stopPropagation();
              onDelete(conv);
            }}
            className="hidden shrink-0 cursor-pointer pr-2 group-hover/conv:block"
            aria-label={`Supprimer ${title}`}
          >
            <Trash2 className="size-4 text-destructive" />
          </button>
        </div>
      </TooltipTrigger>
      <TooltipContent side="right" className="max-w-xs">
        {title}
      </TooltipContent>
    </Tooltip>
  );
}

function ConversationHistory() {
  const pathname = usePathname();
  const router = useRouter();
  const { data: session } = useSession();
  const { currentOrg } = useOrg();
  const token = session?.access_token;

  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [deleteTarget, setDeleteTarget] = useState<Conversation | null>(null);
  const [clearAllOpen, setClearAllOpen] = useState(false);
  const [clearingAll, setClearingAll] = useState(false);

  const fetchConversations = useCallback(async () => {
    if (!token || !currentOrg) return;
    try {
      const data = await listConversations(currentOrg.id, token);
      setConversations(data);
    } catch {
      setConversations([]);
    }
  }, [token, currentOrg]);

  useEffect(() => {
    fetchConversations();
  }, [fetchConversations, pathname]);

  // Refresh when a streaming chat completes (title updated)
  useEffect(() => {
    const handler = () => fetchConversations();
    window.addEventListener("conversation-updated", handler);
    return () => window.removeEventListener("conversation-updated", handler);
  }, [fetchConversations]);

  const visible = conversations.slice(0, 5);
  const overflow = conversations.slice(5);

  const handleConfirmDelete = async () => {
    if (!deleteTarget || !token) return;
    try {
      await deleteConversation(deleteTarget.id, token);
      setConversations((prev) => prev.filter((c) => c.id !== deleteTarget.id));
      if (pathname === `/chat/${deleteTarget.id}`) {
        router.push("/chat");
      }
    } catch {
      // silently fail
    }
    setDeleteTarget(null);
  };

  const handleConfirmClearAll = async () => {
    if (!token || !currentOrg) return;
    setClearingAll(true);
    try {
      await hideAllConversations(currentOrg.id, token);
      setConversations([]);
      if (pathname.startsWith("/chat/")) {
        router.push("/chat");
      }
    } catch {
      // silently fail
    } finally {
      setClearingAll(false);
      setClearAllOpen(false);
    }
  };

  return (
    <>
      {conversations.length === 0 ? null : (
      <>
      <div className="px-4"><Separator /></div>
      <div className="space-y-0.5 px-2 py-2">
        <div className="flex items-center justify-between px-2 pb-1 pt-2">
          <p className="text-muted-foreground text-xs font-medium">
            Historique de chat
          </p>
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                type="button"
                onClick={() => setClearAllOpen(true)}
                className="text-muted-foreground hover:text-destructive p-1 -m-1 rounded hover:bg-muted/60 transition-colors"
                aria-label="Effacer tout l'historique"
              >
                <Trash2 className="size-3.5" />
              </button>
            </TooltipTrigger>
            <TooltipContent side="right">
              Effacer tout l&apos;historique
            </TooltipContent>
          </Tooltip>
        </div>
        {visible.map((conv) => (
          <ConversationItem
            key={conv.id}
            conv={conv}
            isActive={pathname === `/chat/${conv.id}`}
            onDelete={setDeleteTarget}
          />
        ))}
        {overflow.length > 0 && (
          <Collapsible>
            <CollapsibleTrigger asChild>
              <Button
                variant="ghost"
                size="sm"
                className="text-muted-foreground h-auto w-full justify-start gap-2 px-2 py-1.5 text-xs"
              >
                <ChevronRight className="size-4 shrink-0 transition-transform duration-200 [[data-state=open]>&]:rotate-90" />
                <span>
                  {overflow.length} conversation
                  {overflow.length > 1 ? "s" : ""} de plus
                </span>
              </Button>
            </CollapsibleTrigger>
            <CollapsibleContent className="space-y-0.5">
              {overflow.map((conv) => (
                <ConversationItem
                  key={conv.id}
                  conv={conv}
                  isActive={pathname === `/chat/${conv.id}`}
                  onDelete={setDeleteTarget}
                />
              ))}
            </CollapsibleContent>
          </Collapsible>
        )}
      </div>
      </>
      )}

      <Dialog
        open={deleteTarget !== null}
        onOpenChange={(open) => {
          if (!open) setDeleteTarget(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Supprimer la conversation</DialogTitle>
            <DialogDescription>
              Voulez-vous vraiment supprimer &laquo;&nbsp;
              {deleteTarget?.title || "Nouvelle conversation"}&nbsp;&raquo; ? Cette
              conversation disparaîtra de votre historique.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteTarget(null)}>
              Annuler
            </Button>
            <Button variant="destructive" onClick={handleConfirmDelete}>
              Supprimer
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={clearAllOpen}
        onOpenChange={(open) => {
          if (!clearingAll) setClearAllOpen(open);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Effacer tout l&apos;historique de chat</DialogTitle>
            <DialogDescription>
              Toutes vos conversations vont disparaître de votre historique.
              Cette action concerne uniquement votre vue : les questions
              restent enregistrées pour le suivi qualité et la facturation.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setClearAllOpen(false)}
              disabled={clearingAll}
            >
              Annuler
            </Button>
            <Button
              variant="destructive"
              onClick={handleConfirmClearAll}
              disabled={clearingAll}
            >
              {clearingAll ? "Effacement…" : "Tout effacer"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

export function Sidebar() {
  const { data: session } = useSession();
  const pathname = usePathname();
  const [settingsOpen, setSettingsOpen] = useState(false);

  const fullName = session?.user?.full_name ?? "Utilisateur";
  const token = session?.access_token;
  const { workspaceName, currentOrg } = useOrg();

  const [userPlan, setUserPlan] = useState<{ plan: string; plan_expires_at: string | null } | null>(null);
  const [quota, setQuota] = useState<QuotaInfo | null>(null);

  const fetchPlan = useCallback(() => {
    if (!token) return;
    const params = currentOrg?.id ? `?organisation_id=${currentOrg.id}` : "";
    apiFetch<{ plan: string | null; plan_expires_at: string | null }>(`/users/me${params}`, { token })
      .then((data) => {
        setUserPlan({ plan: data.plan ?? "gratuit", plan_expires_at: data.plan_expires_at });
      })
      .catch(() => {});
    fetchQuota(token).then(setQuota).catch(() => {});
  }, [token, currentOrg?.id]);

  useEffect(() => {
    fetchPlan();
  }, [fetchPlan]);

  useEffect(() => {
    const handler = () => fetchPlan();
    window.addEventListener("plan-updated", handler);
    return () => window.removeEventListener("plan-updated", handler);
  }, [fetchPlan]);

  // Refresh the quota counter after every successful chat answer.
  useEffect(() => {
    if (!token) return;
    const refreshQuota = () => {
      fetchQuota(token).then(setQuota).catch(() => {});
    };
    window.addEventListener("quota-updated", refreshQuota);
    return () => window.removeEventListener("quota-updated", refreshQuota);
  }, [token]);

  // Couleur du texte du plan dans la sidebar — juste un bonus visuel spécifique
  // à cet emplacement, le label / features viennent de PLANS (@/lib/plans).
  const PLAN_TEXT_CLASS: Record<string, string> = {
    gratuit: "text-muted-foreground",
    invite: "text-[#652bb0]",
    vip: "text-amber-700 dark:text-amber-300",
    solo: "text-sky-700 dark:text-sky-300",
    equipe: "text-primary",
    groupe: "text-emerald-700 dark:text-emerald-300",
  };
  const currentPlanCode = (userPlan?.plan ?? "gratuit") as AnyPlanCode;
  const currentPlanLabel =
    currentPlanCode in PLANS
      ? PLANS[currentPlanCode].label
      : getPlanLabel(currentPlanCode);
  const currentPlanTextClass =
    PLAN_TEXT_CLASS[currentPlanCode] ?? "text-muted-foreground";

  return (
    <>
      <aside className="flex w-64 flex-col bg-sidebar text-sidebar-foreground">
        <div className="p-4">
          <Image src="/logo-aoria.png" alt="AORIA RH" width={140} height={40} priority />
        </div>

        <div className="px-4 pb-4">
          <OrgSelector />
        </div>

        <div className="px-4"><Separator /></div>

        {/* Navigation principale */}
        <nav className="space-y-1 px-2 py-2">
          {navigation
            .filter((item) => !item.managerOnly || session?.user?.role === "manager" || session?.user?.role === "admin")
            .map((item) => {
            const isActive =
              item.href === "/chat"
                ? pathname === "/chat"
                : pathname.startsWith(item.href);
            const isChat = item.href === "/chat";
            return (
              <div key={item.name} className="flex items-center gap-1">
                <Button
                  variant="ghost"
                  className={cn(
                    "flex-1 justify-start font-normal",
                    isActive && "bg-accent text-accent-foreground font-medium",
                  )}
                  asChild
                >
                  <Link href={item.href}>
                    <item.icon className="mr-2 h-5 w-5" />
                    {item.name}
                  </Link>
                </Button>
                {isChat && (
                  <Button
                    size="icon-sm"
                    className="bg-primary text-primary-foreground hover:bg-primary/90 shrink-0"
                    title="Nouvelle conversation"
                    asChild
                  >
                    <Link href="/chat">
                      <Plus className="h-4 w-4" />
                    </Link>
                  </Button>
                )}
              </div>
            );
          })}
        </nav>

        {/* Administration (sous Organisation) */}
        {session?.user?.role === "admin" && (
          <>
          <div className="px-4"><Separator /></div>
          <div className="px-2 py-2">
            <Collapsible defaultOpen={pathname.startsWith("/admin")}>
              <CollapsibleTrigger asChild>
                <Button variant="ghost" className="w-full justify-start font-normal">
                  <ShieldCheck className="mr-2 h-5 w-5" />
                  <span className="flex-1 text-left">Administration</span>
                  <ChevronRight className="h-5 w-5 transition-transform duration-200 [[data-state=open]>&]:rotate-90" />
                </Button>
              </CollapsibleTrigger>
              <CollapsibleContent className="space-y-1 pl-4 pt-1">
                <Button
                  variant="ghost"
                  size="sm"
                  className={cn(
                    "w-full justify-start font-normal",
                    pathname === "/admin/home" &&
                      "bg-accent text-accent-foreground font-medium",
                  )}
                  asChild
                >
                  <Link href="/admin/home">
                    <TrendingUp className="mr-2 h-5 w-5" />
                    Tableau de bord
                  </Link>
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  className={cn(
                    "w-full justify-start font-normal",
                    pathname.startsWith("/admin/users") &&
                      "bg-accent text-accent-foreground font-medium",
                  )}
                  asChild
                >
                  <Link href="/admin/users">
                    <Users className="mr-2 h-5 w-5" />
                    Clients
                  </Link>
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  className={cn(
                    "w-full justify-start font-normal",
                    pathname.startsWith("/admin/corpus") &&
                      "bg-accent text-accent-foreground font-medium",
                  )}
                  asChild
                >
                  <Link href="/admin/corpus">
                    <Library className="mr-2 h-5 w-5" />
                    Corpus juridique
                  </Link>
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  className={cn(
                    "w-full justify-start font-normal",
                    pathname.startsWith("/admin/quality") &&
                      "bg-accent text-accent-foreground font-medium",
                  )}
                  asChild
                >
                  <Link href="/admin/quality">
                    <Gauge className="mr-2 h-5 w-5" />
                    Qualité & conversations
                  </Link>
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  className={cn(
                    "w-full justify-start font-normal",
                    pathname.startsWith("/admin/qdrant") &&
                      "bg-accent text-accent-foreground font-medium",
                  )}
                  asChild
                >
                  <Link href="/admin/qdrant">
                    <Database className="mr-2 h-5 w-5" />
                    Index Qdrant
                  </Link>
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  className={cn(
                    "w-full justify-start font-normal",
                    pathname.startsWith("/admin/costs") &&
                      "bg-accent text-accent-foreground font-medium",
                  )}
                  asChild
                >
                  <Link href="/admin/costs">
                    <DollarSign className="mr-2 h-5 w-5" />
                    Suivi des coûts
                  </Link>
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  className={cn(
                    "w-full justify-start font-normal",
                    pathname.startsWith("/admin/billing") &&
                      "bg-accent text-accent-foreground font-medium",
                  )}
                  asChild
                >
                  <Link href="/admin/billing">
                    <CreditCard className="mr-2 h-5 w-5" />
                    Facturation
                  </Link>
                </Button>
              </CollapsibleContent>
            </Collapsible>
          </div>
          </>
        )}

        {/* Historique des conversations */}
        <ConversationHistory />

        {/* Spacer */}
        <div className="flex-1" />

        {/* Espace de travail + Plan */}
        {userPlan && (
          <div className="px-3 pb-2">
            <div className="rounded-lg border p-3 space-y-2">
              {workspaceName && (
                <p className="text-xs font-semibold truncate">{workspaceName}</p>
              )}
              <Link
                href="/billing"
                className="block -mx-1 px-1 rounded hover:bg-muted/60 transition-colors"
                title="Voir mon abonnement"
              >
                <p className={cn("text-xs font-semibold", currentPlanTextClass)}>
                  Plan {currentPlanLabel}
                </p>
                {userPlan.plan === "gratuit" && userPlan.plan_expires_at && (
                  <p className="text-[10px] text-muted-foreground truncate">
                    Essai jusqu&apos;au {new Date(userPlan.plan_expires_at).toLocaleDateString("fr-FR")}
                  </p>
                )}
                {userPlan.plan === "invite" && userPlan.plan_expires_at && (
                  <p className="text-[10px] text-muted-foreground truncate">
                    Expire le {new Date(userPlan.plan_expires_at).toLocaleDateString("fr-FR")}
                  </p>
                )}
                {userPlan.plan === "vip" && (
                  <p className="text-[11px] text-foreground">Accès illimité</p>
                )}
              </Link>

              {/* Quota de questions — masqué pour le plan vip (illimité) */}
              {quota && userPlan.plan !== "vip" && (
                <div className="space-y-1">
                  <div className="flex items-center justify-between text-[10px] tabular-nums">
                    <span className="text-muted-foreground">Questions ce mois</span>
                    <span className={cn(
                      "font-medium",
                      quota.quota_status === "hard_warning" && "text-destructive",
                      quota.quota_status === "soft_warning" && "text-orange-600 dark:text-orange-400",
                    )}>
                      {quota.used} / {quota.quota}
                      {quota.booster_remaining > 0 && (
                        <span className="text-muted-foreground"> +{quota.booster_remaining}</span>
                      )}
                    </span>
                  </div>
                  <div className="h-1 w-full rounded-full bg-muted overflow-hidden">
                    <div
                      className={cn(
                        "h-full transition-all",
                        quota.quota_status === "hard_warning" ? "bg-destructive"
                          : quota.quota_status === "soft_warning" ? "bg-orange-500"
                          : "bg-primary",
                      )}
                      style={{ width: `${Math.min(100, quota.quota > 0 ? (quota.used / quota.quota) * 100 : 0)}%` }}
                    />
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Utilisateur */}
        <div className="px-4"><Separator /></div>

        <div className="p-2">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant="ghost"
                className="w-full justify-start gap-2 px-2"
              >
                <Avatar className="h-7 w-7">
                  <AvatarFallback className="text-xs">
                    {getInitials(fullName)}
                  </AvatarFallback>
                </Avatar>
                <span className="flex-1 truncate text-left text-sm font-medium">
                  {fullName}
                </span>
                <ChevronsUpDown className="h-5 w-5 shrink-0 opacity-50" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent side="top" align="start" className="w-56">
              <DropdownMenuItem asChild>
                <Link href="/account">
                  <User className="mr-2 h-5 w-5" />
                  Mon compte
                </Link>
              </DropdownMenuItem>
              <DropdownMenuItem asChild>
                <Link href="/billing">
                  <CreditCard className="mr-2 h-5 w-5" />
                  Abonnement
                </Link>
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={() => setSettingsOpen(true)}>
                <Settings className="mr-2 h-5 w-5" />
                Paramètres
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                onSelect={() => signOut({ callbackUrl: "/login" })}
              >
                <LogOut className="mr-2 h-5 w-5" />
                Déconnexion
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </aside>

      <SettingsDialog open={settingsOpen} onOpenChange={setSettingsOpen} />
    </>
  );
}
