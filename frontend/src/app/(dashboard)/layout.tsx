"use client";

import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import Image from "next/image";
import { Menu } from "lucide-react";
import { Sidebar } from "@/components/sidebar";
import { TrialBanner } from "@/components/trial-banner";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const pathname = usePathname();

  useEffect(() => {
    setOpen(false);
  }, [pathname]);

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <div className="flex h-screen">
        <Sidebar />
        <SheetContent
          side="left"
          showCloseButton={false}
          className="w-72 max-w-[85vw] border-r-0 p-0 sm:max-w-xs lg:hidden"
        >
          <SheetTitle className="sr-only">Navigation</SheetTitle>
          <Sidebar variant="mobile" />
        </SheetContent>
        <div className="flex min-w-0 min-h-0 flex-1 flex-col overflow-y-auto">
          <header className="lg:hidden flex items-center gap-3 border-b bg-background px-4 py-3 shrink-0">
            <SheetTrigger asChild>
              <Button variant="ghost" size="icon" aria-label="Ouvrir le menu">
                <Menu className="h-5 w-5" />
              </Button>
            </SheetTrigger>
            <Image
              src="/logo-aoria.png"
              alt="AORIA RH"
              width={120}
              height={32}
              priority
            />
          </header>
          <TrialBanner />
          <main className="flex min-h-0 flex-1 flex-col p-4 sm:p-6 md:p-8 lg:px-10 lg:py-8">
            {children}
          </main>
        </div>
      </div>
    </Sheet>
  );
}
