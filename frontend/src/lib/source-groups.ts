import type { MessageSource } from "@/types/api";

export type SourceGroupKey =
  | "legal"
  | "jurisprudence"
  | "conventional"
  | "internal";

export interface SourceGroup {
  key: SourceGroupKey;
  label: string;
  sources: MessageSource[];
}

const LEGAL_TYPES = new Set([
  "constitution",
  "bloc_constitutionnalite",
  "traite_international",
  "convention_oit",
  "directive_europeenne",
  "reglement_europeen",
  "charte_droits_fondamentaux",
  "code_travail",
  "code_travail_reglementaire",
  "loi",
  "ordonnance",
  "code_securite_sociale",
  "code_securite_sociale_reglementaire",
  "code_penal",
  "code_civil",
  "code_civil_reglementaire",
  "code_action_sociale",
  "code_action_sociale_reglementaire",
  "code_sante_publique",
  "code_sante_publique_reglementaire",
  "code_commerce",
  "code_commerce_reglementaire",
  "code_monetaire_financier",
  "code_monetaire_financier_reglementaire",
  "code_general_impots",
  "code_general_impots_reglementaire",
  "decret",
  "arrete",
  "circulaire",
]);

const JURISPRUDENCE_TYPES = new Set([
  "arret_cour_cassation",
  "arret_cour_appel",
  "arret_conseil_etat",
  "decision_conseil_constitutionnel",
]);

const CONVENTIONAL_TYPES = new Set([
  "accord_national_interprofessionnel",
  "accord_branche",
  "convention_collective_nationale",
  "accord_entreprise",
  "accord_performance_collective",
]);

const INTERNAL_TYPES = new Set([
  "usage_entreprise",
  "engagement_unilateral",
  "reglement_interieur",
  "contrat_travail",
  "divers",
]);

export function getSourceGroup(sourceType: string): SourceGroupKey {
  if (LEGAL_TYPES.has(sourceType)) return "legal";
  if (JURISPRUDENCE_TYPES.has(sourceType)) return "jurisprudence";
  if (CONVENTIONAL_TYPES.has(sourceType)) return "conventional";
  if (INTERNAL_TYPES.has(sourceType)) return "internal";
  return "internal";
}

const GROUP_LABELS: Record<SourceGroupKey, string> = {
  legal: "Textes légaux et réglementaires",
  jurisprudence: "Jurisprudence",
  conventional: "Conventions collectives et accords",
  internal: "Sources internes",
};

const GROUP_ORDER: SourceGroupKey[] = [
  "legal",
  "jurisprudence",
  "conventional",
  "internal",
];

function compareJurisprudenceByDateDesc(
  a: MessageSource,
  b: MessageSource,
): number {
  const da = a.date_decision ?? "";
  const db = b.date_decision ?? "";
  if (!da && !db) return 0;
  if (!da) return 1;
  if (!db) return -1;
  return db.localeCompare(da);
}

export function groupSources(sources: MessageSource[]): SourceGroup[] {
  const buckets: Record<SourceGroupKey, MessageSource[]> = {
    legal: [],
    jurisprudence: [],
    conventional: [],
    internal: [],
  };

  for (const source of sources) {
    buckets[getSourceGroup(source.source_type)].push(source);
  }

  buckets.jurisprudence.sort(compareJurisprudenceByDateDesc);

  return GROUP_ORDER.filter((key) => buckets[key].length > 0).map((key) => ({
    key,
    label: GROUP_LABELS[key],
    sources: buckets[key],
  }));
}
