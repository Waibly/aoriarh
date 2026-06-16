"use client";

import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useSession, signOut } from "next-auth/react";
import {
  TrendingUp,
  Users,
  CreditCard,
  DollarSign,
  Mail,
  Gift,
  Gauge,
  Library,
  Database,
  Search,
  ArrowLeft,
  ChevronsUpDown,
  User,
  LogOut,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";

type NavItem = { name: string; href: string; icon: React.ElementType };
type NavGroup = { key: string; label: string; items: NavItem[] };

const GROUPS: NavGroup[] = [
  {
    key: "pilotage",
    label: "Pilotage",
    items: [
      { name: "Tableau de bord", href: "/admin/pilotage", icon: TrendingUp },
      { name: "Clients", href: "/admin/clients", icon: Users },
      { name: "Facturation", href: "/admin/billing", icon: CreditCard },
      { name: "Coûts & marge", href: "/admin/costs", icon: DollarSign },
    ],
  },
  {
    key: "acquisition",
    label: "Acquisition",
    items: [
      { name: "Campagnes", href: "/admin/emailing/campaigns", icon: Mail },
      { name: "Liens promo", href: "/admin/plan-invitations", icon: Gift },
      { name: "Séquences", href: "/admin/emailing/sequences", icon: Mail },
      { name: "Templates", href: "/admin/emailing/templates", icon: Mail },
      { name: "Listes Brevo", href: "/admin/emailing/lists", icon: Mail },
    ],
  },
  {
    key: "exploitation",
    label: "Exploitation",
    items: [
      { name: "Santé technique", href: "/admin/home", icon: Gauge },
      { name: "Qualité & conversations", href: "/admin/quality", icon: Gauge },
      { name: "Corpus juridique", href: "/admin/corpus", icon: Library },
      { name: "Index Qdrant", href: "/admin/qdrant", icon: Database },
      { name: "Recherche documentaire", href: "/recherche", icon: Search },
    ],
  },
];

function getInitials(name: string) {
  return name
    .split(" ")
    .map((n) => n[0])
    .join("")
    .toUpperCase()
    .slice(0, 2);
}

function isItemActive(pathname: string, href: string) {
  if (href === "/admin/home") return pathname === "/admin/home";
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function AdminSidebar({
  variant = "desktop",
  onNavigate,
}: {
  variant?: "desktop" | "mobile";
  onNavigate?: () => void;
} = {}) {
  const { data: session } = useSession();
  const pathname = usePathname();
  const fullName = session?.user?.full_name ?? "Utilisateur";
  const staffRole = session?.user?.staff_role ?? null;

  // Tech staff lead with Exploitation; everyone else leads with Pilotage.
  const orderedGroups =
    staffRole === "tech"
      ? [...GROUPS].sort((a, b) =>
          a.key === "exploitation" ? -1 : b.key === "exploitation" ? 1 : 0
        )
      : GROUPS;

  return (
    <aside
      className={cn(
        "bg-sidebar text-sidebar-foreground flex flex-col",
        variant === "desktop" && "hidden w-64 shrink-0 lg:flex",
        variant === "mobile" && "h-full w-full overflow-y-auto"
      )}
      onClick={(e) => {
        if (variant !== "mobile" || !onNavigate) return;
        const target = e.target as HTMLElement | null;
        if (target?.closest("a[href]")) onNavigate();
      }}
    >
      <div className="p-4">
        <Image
          src="/logo-aoria.svg"
          alt="AORIA RH"
          width={140}
          height={30}
          priority
          className="dark:hidden"
        />
        <Image
          src="/logo-aoria-white.svg"
          alt="AORIA RH"
          width={140}
          height={30}
          priority
          className="hidden dark:block"
        />
        <p className="text-muted-foreground mt-1 text-xs font-medium">
          Administration
        </p>
      </div>

      <div className="px-2 pb-2">
        <Button
          variant="ghost"
          size="sm"
          className="w-full justify-start font-normal"
          asChild
        >
          <Link href="/chat">
            <ArrowLeft className="mr-2 h-4 w-4" />
            Retour à l&apos;application
          </Link>
        </Button>
      </div>

      <div className="px-4">
        <Separator />
      </div>

      <nav className="flex-1 space-y-4 overflow-y-auto px-2 py-3">
        {orderedGroups.map((group) => (
          <div key={group.key} className="space-y-1">
            <p className="text-muted-foreground px-2 text-xs font-semibold tracking-wide uppercase">
              {group.label}
            </p>
            {group.items.map((item) => {
              const active = isItemActive(pathname, item.href);
              return (
                <Button
                  key={item.href}
                  variant="ghost"
                  size="sm"
                  className={cn(
                    "w-full justify-start font-normal",
                    active && "bg-accent text-accent-foreground font-medium"
                  )}
                  asChild
                >
                  <Link href={item.href}>
                    <item.icon className="mr-2 h-4 w-4" />
                    {item.name}
                  </Link>
                </Button>
              );
            })}
          </div>
        ))}
      </nav>

      <div className="px-4">
        <Separator />
      </div>

      <div className="p-2">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" className="w-full justify-start gap-2 px-2">
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
  );
}
