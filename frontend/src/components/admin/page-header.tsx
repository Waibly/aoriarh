import type { ReactNode } from "react";
import { AlertCircle, Inbox } from "lucide-react";
import { Button } from "@/components/ui/button";

export function AdminPageHeader({
  section,
  title,
  description,
  actions,
}: {
  section?: string;
  title: string;
  description: string;
  actions?: ReactNode;
}) {
  return (
    <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-start">
      <div className="max-w-2xl space-y-2">
        {section && (
          <p className="text-primary text-xs font-semibold tracking-widest uppercase">
            {section}
          </p>
        )}
        <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">
          {title}
        </h1>
        <p className="text-muted-foreground text-sm leading-relaxed">
          {description}
        </p>
      </div>
      {actions && (
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          {actions}
        </div>
      )}
    </div>
  );
}

export function AdminEmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center gap-3 px-6 py-12 text-center">
      <span className="bg-muted text-muted-foreground rounded-2xl p-3">
        <Inbox className="size-5" aria-hidden="true" />
      </span>
      <div className="space-y-1">
        <p className="font-medium">{title}</p>
        {description && (
          <p className="text-muted-foreground max-w-md text-sm">
            {description}
          </p>
        )}
      </div>
      {action}
    </div>
  );
}

export function AdminLoadError({
  message = "Impossible de charger les données.",
  onRetry,
}: {
  message?: string;
  onRetry: () => void;
}) {
  return (
    <div
      role="alert"
      className="border-destructive/25 bg-destructive/5 flex flex-wrap items-center gap-3 rounded-xl border p-4"
    >
      <AlertCircle
        className="text-destructive size-5 shrink-0"
        aria-hidden="true"
      />
      <p className="flex-1 text-sm">{message}</p>
      <Button variant="outline" size="sm" onClick={onRetry}>
        Réessayer
      </Button>
    </div>
  );
}
