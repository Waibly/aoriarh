"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";

export function AdminSectionNav({
  items,
  label,
}: {
  items: { href: string; label: string }[];
  label: string;
}) {
  const pathname = usePathname();
  return (
    <nav aria-label={label} className="flex gap-5 overflow-x-auto border-b">
      {items.map((item) => (
        <Link
          key={item.href}
          href={item.href}
          aria-current={pathname === item.href ? "page" : undefined}
          className={cn(
            "hover:text-foreground shrink-0 border-b-2 border-transparent px-1 pt-2 pb-3 text-sm font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-[-2px]",
            pathname === item.href
              ? "border-primary text-primary"
              : "text-muted-foreground"
          )}
        >
          {item.label}
        </Link>
      ))}
    </nav>
  );
}

export function ServiceNav() {
  return (
    <AdminSectionNav
      label="État du service"
      items={[
        { href: "/admin/home", label: "Vue d’ensemble" },
        { href: "/admin/incidents", label: "Journal des incidents" },
      ]}
    />
  );
}
