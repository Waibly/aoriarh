import { AdminPageHeader } from "@/components/admin/page-header";
import { AdminSectionNav } from "@/components/admin/section-nav";

export default function EmailingLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-6">
      <AdminPageHeader
        section="Acquisition"
        title="Emailing"
        description="Préparez vos campagnes et suivez leurs résultats depuis un seul espace."
      />
      <AdminSectionNav
        label="Emailing"
        items={[
          { href: "/admin/emailing", label: "Préparer les campagnes" },
          { href: "/admin/emailing/stats", label: "Statistiques" },
        ]}
      />
      {children}
    </div>
  );
}
