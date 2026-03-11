import { Sidebar } from "@/components/sidebar";

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="flex h-screen">
      <Sidebar />
      <main className="flex min-h-0 flex-1 flex-col overflow-y-auto p-6">
        {children}
      </main>
    </div>
  );
}
