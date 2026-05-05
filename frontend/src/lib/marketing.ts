const MARKETING_URL = (
  process.env.NEXT_PUBLIC_MARKETING_URL ?? "http://localhost:4321"
).replace(/\/$/, "");

export const marketingLinks = {
  mentionsLegales: `${MARKETING_URL}/mentions-legales`,
  confidentialite: `${MARKETING_URL}/confidentialite`,
  accessibilite: `${MARKETING_URL}/accessibilite`,
  cgv: `${MARKETING_URL}/cgv`,
} as const;
