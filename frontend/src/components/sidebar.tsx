"use client";

import { useState, useEffect, useCallback } from "react";
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
  Scale,
  MessageSquareQuote,
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
  RefreshCw,
  TrendingUp,
} from "lucide-react";
import { apiFetch } from "@/lib/api";
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
} from "@/lib/chat-api";
import type { Conversation } from "@/types/api";

const navigation = [
  { name: "Chat", href: "/chat", icon: MessageSquare },
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

  return (
    <>
      {conversations.length === 0 ? null : (
      <>
      <div className="px-4"><Separator /></div>
      <div className="space-y-0.5 px-2 py-2">
        <p className="text-muted-foreground px-2 pb-1 pt-2 text-xs font-medium">
          Historique de chat
        </p>
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
              {deleteTarget?.title || "Nouvelle conversation"}&nbsp;&raquo; ? Cette action est
              irréversible.
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

  const fetchPlan = useCallback(() => {
    if (!token) return;
    const params = currentOrg?.id ? `?organisation_id=${currentOrg.id}` : "";
    apiFetch<{ plan: string | null; plan_expires_at: string | null }>(`/users/me${params}`, { token })
      .then((data) => {
        setUserPlan({ plan: data.plan ?? "gratuit", plan_expires_at: data.plan_expires_at });
      })
      .catch(() => {});
  }, [token, currentOrg?.id]);

  useEffect(() => {
    fetchPlan();
  }, [fetchPlan]);

  useEffect(() => {
    const handler = () => fetchPlan();
    window.addEventListener("plan-updated", handler);
    return () => window.removeEventListener("plan-updated", handler);
  }, [fetchPlan]);

  const planDisplay = {
    gratuit: { label: "Gratuit", icon: UserCheck, textClass: "text-muted-foreground", iconBg: "bg-muted" },
    invite: { label: "Invité", icon: Gift, textClass: "text-[#9952b8]", iconBg: "bg-[#9952b8]/15" },
    vip: { label: "VIP", icon: Crown, textClass: "text-amber-700 dark:text-amber-300", iconBg: "bg-amber-400/20 dark:bg-amber-500/20" },
  } as const;

  const currentPlanConfig = planDisplay[(userPlan?.plan ?? "gratuit") as keyof typeof planDisplay] ?? planDisplay.gratuit;
  const PlanIcon = currentPlanConfig.icon;

  return (
    <>
      <aside className="flex w-64 flex-col bg-sidebar text-sidebar-foreground">
        <div className="p-4">
          <h1 className="text-xl font-semibold tracking-tight">AORIA RH</h1>
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
            return (
              <Button
                key={item.name}
                variant="ghost"
                className={cn(
                  "w-full justify-start font-normal",
                  isActive && "bg-accent text-accent-foreground font-medium",
                )}
                asChild
              >
                <Link href={item.href}>
                  <item.icon className="mr-2 h-5 w-5" />
                  {item.name}
                </Link>
              </Button>
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
                    pathname.startsWith("/admin/documents-communs") &&
                      "bg-accent text-accent-foreground font-medium",
                  )}
                  asChild
                >
                  <Link href="/admin/documents-communs">
                    <Library className="mr-2 h-5 w-5" />
                    Documents communs
                  </Link>
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  className={cn(
                    "w-full justify-start font-normal",
                    pathname.startsWith("/admin/ccn") &&
                      "bg-accent text-accent-foreground font-medium",
                  )}
                  asChild
                >
                  <Link href="/admin/ccn">
                    <Scale className="mr-2 h-5 w-5" />
                    Conventions collectives
                  </Link>
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  className={cn(
                    "w-full justify-start font-normal",
                    pathname.startsWith("/admin/jurisprudence") &&
                      "bg-accent text-accent-foreground font-medium",
                  )}
                  asChild
                >
                  <Link href="/admin/jurisprudence">
                    <Scale className="mr-2 h-5 w-5" />
                    Jurisprudence
                  </Link>
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  className={cn(
                    "w-full justify-start font-normal",
                    pathname.startsWith("/admin/feedbacks") &&
                      "bg-accent text-accent-foreground font-medium",
                  )}
                  asChild
                >
                  <Link href="/admin/feedbacks">
                    <MessageSquareQuote className="mr-2 h-5 w-5" />
                    Avis utilisateurs
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
                    pathname.startsWith("/admin/syncs") &&
                      "bg-accent text-accent-foreground font-medium",
                  )}
                  asChild
                >
                  <Link href="/admin/syncs">
                    <RefreshCw className="mr-2 h-5 w-5" />
                    Synchronisations
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
              <div className="flex items-center gap-2">
                <div className={cn(
                  "flex h-8 w-8 items-center justify-center rounded-md",
                  currentPlanConfig.iconBg,
                )}>
                  <PlanIcon className={cn("h-4 w-4", currentPlanConfig.textClass)} />
                </div>
                <div className="flex-1 min-w-0">
                  <p className={cn("text-xs font-semibold", currentPlanConfig.textClass)}>
                    Plan {currentPlanConfig.label}
                  </p>
                  {userPlan.plan === "invite" && userPlan.plan_expires_at && (
                    <p className="text-[10px] text-muted-foreground truncate">
                      Expire le {new Date(userPlan.plan_expires_at).toLocaleDateString("fr-FR")}
                    </p>
                  )}
                  {userPlan.plan === "vip" && (
                    <p className="text-[11px] text-foreground">Accès illimité</p>
                  )}
                </div>
              </div>
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
