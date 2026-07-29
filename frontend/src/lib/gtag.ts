import type { ConsentState } from "@/lib/consent";

// gtag.js (GA4 + Google Ads), chargé uniquement si les IDs sont configurés ET
// que le consentement (bandeau du site vitrine, cookie .aoriarh.fr) l'autorise.
// Les IDs restent en placeholders tant que le compte Google n'est pas finalisé :
// sans variable d'environnement, aucun script n'est chargé, aucun événement émis.

export const GA4_ID = process.env.NEXT_PUBLIC_GA4_ID || "";
export const ADS_ID = process.env.NEXT_PUBLIC_ADS_ID || "";
// Labels des actions de conversion Google Ads (format "xxXXxxXXxxX", fournis
// par la console Ads une fois l'action créée). Optionnels : sans label, seuls
// les événements GA4 partent (importables ensuite comme conversions Ads).
const ADS_LABEL_ESSAI = process.env.NEXT_PUBLIC_ADS_LABEL_ESSAI || "";
const ADS_LABEL_DEMO = process.env.NEXT_PUBLIC_ADS_LABEL_DEMO || "";

declare global {
  interface Window {
    dataLayer?: unknown[];
    gtag?: (...args: unknown[]) => void;
  }
}

let loaded = false;

/**
 * Initialise Consent Mode v2 + gtag.js. À n'appeler qu'après lecture d'un
 * consentement positif : le défaut « denied » est posé avant le chargement du
 * script, puis mis à jour selon le choix réel.
 */
export function initGtag(consent: ConsentState): void {
  if (loaded || typeof window === "undefined") return;
  const primaryId = GA4_ID || ADS_ID;
  if (!primaryId) return;
  loaded = true;

  window.dataLayer = window.dataLayer || [];
  function gtag(...args: unknown[]) {
    window.dataLayer!.push(args);
  }
  window.gtag = gtag;

  gtag("consent", "default", {
    ad_storage: "denied",
    ad_user_data: "denied",
    ad_personalization: "denied",
    analytics_storage: "denied",
  });
  gtag("consent", "update", {
    ad_storage: consent.ads ? "granted" : "denied",
    ad_user_data: consent.ads ? "granted" : "denied",
    ad_personalization: consent.ads ? "granted" : "denied",
    analytics_storage: consent.analytics ? "granted" : "denied",
  });

  gtag("js", new Date());
  // Suivi inter-domaines site vitrine <-> app : le linker décore/accepte le
  // paramètre _gl pour conserver la session GA entre aoriarh.fr et app.aoriarh.fr.
  gtag("set", "linker", {
    domains: ["aoriarh.fr", "app.aoriarh.fr"],
    accept_incoming: true,
  });
  if (GA4_ID) gtag("config", GA4_ID);
  if (ADS_ID) gtag("config", ADS_ID);

  const script = document.createElement("script");
  script.async = true;
  script.src = `https://www.googletagmanager.com/gtag/js?id=${encodeURIComponent(primaryId)}`;
  document.head.appendChild(script);
}

function trackEvent(name: string, adsLabel: string): void {
  if (typeof window === "undefined" || !window.gtag) return;
  window.gtag("event", name);
  if (ADS_ID && adsLabel) {
    window.gtag("event", "conversion", { send_to: `${ADS_ID}/${adsLabel}` });
  }
}

/** Conversion principale : création de compte d'essai réussie. */
export function trackEssaiDemarre(): void {
  trackEvent("essai_demarre", ADS_LABEL_ESSAI);
}

/** Conversion secondaire : la démo publique a rendu une réponse. */
export function trackDemoUtilisee(): void {
  trackEvent("demo_utilisee", ADS_LABEL_DEMO);
}
