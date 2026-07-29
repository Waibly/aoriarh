// Lecture du consentement cookies posé par le bandeau du site vitrine
// (aoriarh.fr) sur le domaine parent .aoriarh.fr. L'app n'affiche pas de
// bandeau : sans consentement explicite, aucun script Google n'est chargé.

export interface ConsentState {
  analytics: boolean;
  ads: boolean;
}

const CONSENT_COOKIE = "aoria_consent";

export function getConsent(): ConsentState | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie.match(
    new RegExp("(?:^|; )" + CONSENT_COOKIE + "=([^;]*)"),
  );
  if (!match) return null;
  try {
    const parsed = JSON.parse(decodeURIComponent(match[1]));
    if (typeof parsed !== "object" || parsed === null) return null;
    return {
      analytics: parsed.analytics === true,
      ads: parsed.ads === true,
    };
  } catch {
    return null;
  }
}
