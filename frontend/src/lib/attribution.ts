import { API_BASE_URL } from "@/lib/api";

// Attribution marketing du premier contact (utm_*, gclid, msclkid).
// Le site vitrine (aoriarh.fr) capture ces paramètres à la première visite et
// pose un cookie premier-parti sur .aoriarh.fr ; l'app le relit ici, et
// re-capture si l'utilisateur atterrit directement sur app.aoriarh.fr avec
// des paramètres dans l'URL (query propagée par le site, ou URL finale Ads).
// Premier contact conservé : une attribution déjà stockée n'est jamais écrasée.

export interface SignupAttribution {
  utm_source?: string;
  utm_medium?: string;
  utm_campaign?: string;
  utm_term?: string;
  utm_content?: string;
  gclid?: string;
  msclkid?: string;
  referrer?: string;
  landing_page?: string;
  attributed_at?: string;
}

const COOKIE_NAME = "aoria_attribution";
const STORAGE_KEY = "aoria_attribution";
const MAX_AGE_SECONDS = 90 * 24 * 60 * 60;

const PARAM_KEYS = [
  "utm_source",
  "utm_medium",
  "utm_campaign",
  "utm_term",
  "utm_content",
  "gclid",
  "msclkid",
] as const;

function cookieDomainSuffix(): string {
  if (typeof window === "undefined") return "";
  return window.location.hostname.endsWith("aoriarh.fr")
    ? "; domain=.aoriarh.fr"
    : "";
}

function readAttributionCookie(): SignupAttribution | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie.match(
    new RegExp("(?:^|; )" + COOKIE_NAME + "=([^;]*)"),
  );
  if (!match) return null;
  try {
    const parsed = JSON.parse(decodeURIComponent(match[1]));
    return typeof parsed === "object" && parsed !== null ? parsed : null;
  } catch {
    return null;
  }
}

function readAttributionStorage(): SignupAttribution | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    return typeof parsed === "object" && parsed !== null ? parsed : null;
  } catch {
    return null;
  }
}

function persist(attribution: SignupAttribution) {
  const encoded = encodeURIComponent(JSON.stringify(attribution));
  document.cookie = `${COOKIE_NAME}=${encoded}; max-age=${MAX_AGE_SECONDS}; path=/${cookieDomainSuffix()}; samesite=lax`;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(attribution));
  } catch {
    // Stockage local indisponible (navigation privée) : le cookie suffit.
  }
}

/** Attribution stockée (cookie .aoriarh.fr prioritaire, localStorage en secours). */
export function getAttribution(): SignupAttribution | null {
  return readAttributionCookie() ?? readAttributionStorage();
}

/**
 * À appeler une fois au chargement de l'app : relit l'attribution posée par le
 * site vitrine, ou la capture depuis l'URL courante si c'est le premier contact.
 */
export function captureAttribution(): void {
  if (typeof window === "undefined") return;

  const existing = getAttribution();
  if (existing) {
    // Premier contact conservé — on resynchronise juste cookie + localStorage.
    persist(existing);
    return;
  }

  const params = new URLSearchParams(window.location.search);
  const captured: SignupAttribution = {};
  let hasParam = false;
  for (const key of PARAM_KEYS) {
    const value = params.get(key);
    if (value) {
      captured[key] = value.slice(0, 255);
      hasParam = true;
    }
  }
  if (!hasParam) return;

  if (document.referrer) captured.referrer = document.referrer.slice(0, 1024);
  captured.landing_page = window.location.href.slice(0, 1024);
  captured.attributed_at = new Date().toISOString();
  persist(captured);
}

/**
 * Rattache l'attribution à un compte déjà créé (parcours OAuth Google, où la
 * création se fait côté serveur sans accès aux cookies du navigateur).
 * Non bloquant : le backend conserve le premier contact et ignore les doublons.
 */
export async function sendAttribution(accessToken: string): Promise<void> {
  const attribution = getAttribution();
  if (!attribution) return;
  try {
    await fetch(`${API_BASE_URL}/users/me/attribution`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${accessToken}`,
      },
      body: JSON.stringify(attribution),
    });
  } catch {
    // Non bloquant : l'attribution ne doit jamais gêner le parcours.
  }
}
