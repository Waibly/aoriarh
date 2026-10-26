import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { TechnicalCosts } from "@/components/admin/technical-costs";
import { Button } from "@/components/ui/button";

export default function CostDetailsPage() {
  return (
    <div className="space-y-6">
      <Button variant="ghost" size="sm" asChild>
        <Link href="/admin/costs">
          <ArrowLeft className="size-4" />
          Retour à la rentabilité
        </Link>
      </Button>
      <TechnicalCosts />
    </div>
  );
}
