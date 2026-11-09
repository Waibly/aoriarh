import { apiFetch } from "@/lib/api";
import { toast } from "@/lib/toast";

export function readSignupCookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  const value = document.cookie
    .split("; ")
    .find((part) => part.startsWith(`${name}=`));
  return value ? decodeURIComponent(value.slice(name.length + 1)) : null;
}

export function clearSignupCookie(name: string) {
  document.cookie = `${name}=; max-age=0; path=/; samesite=lax`;
}

export function safeAppCallback(value: string | null): string | null {
  return value?.startsWith("/") &&
    !value.startsWith("//") &&
    !value.includes("\\")
    ? value
    : null;
}

export function withSetupWarnings(path: string, warnings: string[]): string {
  if (!warnings.length) return path;
  const url = new URL(path, window.location.origin);
  url.searchParams.set("ccn_install_error", warnings.join(" • "));
  return `${url.pathname}${url.search}${url.hash}`;
}

/** Clear the recovery token only after the server confirms the outcome. */
export async function redeemPendingPlan(token: string): Promise<void> {
  const invitation = readSignupCookie("aoria_plan_invite_token");
  if (!invitation) return;
  const result = await apiFetch<{ status: string }>(
    `/plan-invitations/${invitation}/redeem`,
    {
      method: "POST",
      token,
    }
  );
  if (
    !["redeemed", "already_redeemed", "already_paid"].includes(result.status)
  ) {
    throw new Error("L'activation de votre invitation n'a pas été confirmée.");
  }
  clearSignupCookie("aoria_plan_invite_token");
  if (result.status === "already_paid") {
    toast.warning("Ce lien ne s'applique pas à votre abonnement payant.");
  }
  window.dispatchEvent(new Event("plan-updated"));
  window.dispatchEvent(new Event("quota-updated"));
}
