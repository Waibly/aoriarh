"use client";

import { useEffect } from "react";
import { captureAttribution } from "@/lib/attribution";
import { getConsent } from "@/lib/consent";
import { initGtag } from "@/lib/gtag";

// Monté une fois dans le layout racine :
// 1. capture/relit l'attribution marketing (premier-parti, sans consentement
//    requis : aucune donnée n'est transmise à un tiers) ;
// 2. charge gtag.js uniquement si les IDs Google sont configurés ET que le
//    consentement donné sur le site vitrine (cookie .aoriarh.fr) l'autorise.
export function Analytics() {
  useEffect(() => {
    captureAttribution();
    const consent = getConsent();
    if (consent && (consent.analytics || consent.ads)) {
      initGtag(consent);
    }
  }, []);

  return null;
}
