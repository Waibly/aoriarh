import { Sidebar } from "@/components/sidebar";
import { TrialBanner } from "@/components/trial-banner";

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="flex h-screen">
      <Sidebar />
      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
        <TrialBanner />
        <main className="flex min-h-0 flex-1 flex-col p-6 md:p-8 lg:px-10 lg:py-8">
          {children}
        </main>
      </div>
    </div>
  );
}
