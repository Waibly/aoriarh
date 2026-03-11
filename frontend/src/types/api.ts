export interface User {
  id: string;
  email: string;
  full_name: string;
  role: "admin" | "manager" | "user";
  is_active: boolean;
  created_at: string;
}

export interface Organisation {
  id: string;
  name: string;
  forme_juridique: string | null;
  taille: string | null;
  created_at: string;
}

export interface Document {
  id: string;
  organisation_id: string | null;
  name: string;
  source_type: string;
  norme_niveau: number | null;
  norme_poids: number | null;
  indexation_status: string;
  indexation_duration_ms: number | null;
  chunk_count: number | null;
  indexation_progress: number | null;
  indexation_error: string | null;
  uploaded_by: string;
  file_size: number | null;
  file_format: string | null;
  created_at: string;
  // Jurisprudence metadata
  juridiction: string | null;
  chambre: string | null;
  formation: string | null;
  numero_pourvoi: string | null;
  date_decision: string | null;
  solution: string | null;
  publication: string | null;
}

export interface Conversation {
  id: string;
  organisation_id: string;
  user_id: string;
  title: string | null;
  created_at: string;
  updated_at: string;
}

export interface MessageSource {
  document_name: string;
  source_type: string;
  source_type_label: string;
  norme_niveau: number;
  excerpt: string;
  full_text?: string;
  // Jurisprudence metadata
  juridiction?: string | null;
  chambre?: string | null;
  formation?: string | null;
  numero_pourvoi?: string | null;
  date_decision?: string | null;
  solution?: string | null;
  publication?: string | null;
}

export interface Message {
  id: string;
  conversation_id: string;
  role: "user" | "assistant";
  content: string;
  sources: MessageSource[] | null;
  feedback: string | null;
  created_at: string;
}

export interface ConversationWithMessages extends Conversation {
  messages: Message[];
}

export interface ChatApiResponse {
  message: Message;
  answer: Message;
}

export interface Invitation {
  id: string;
  email: string;
  organisation_id: string;
  invited_by: string;
  role_in_org: "manager" | "user";
  token: string;
  status: "pending" | "accepted" | "cancelled" | "expired";
  expires_at: string;
  created_at: string;
}

export interface InvitationValidateResponse {
  valid: boolean;
  email: string | null;
  organisation_name: string | null;
  status: string | null;
}

export interface Membership {
  id: string;
  user_id: string;
  organisation_id: string;
  role_in_org: "manager" | "user";
  created_at: string;
  user_email: string | null;
  user_full_name: string | null;
}

export const FORME_JURIDIQUE_OPTIONS = [
  "SAS",
  "SARL",
  "SA",
  "SASU",
  "EURL",
  "SCI",
  "SNC",
  "Association loi 1901",
  "Auto-entrepreneur/Micro-entreprise",
  "SCOP",
  "GIE",
] as const;

export const TAILLE_OPTIONS = [
  "1-10",
  "11-50",
  "51-250",
  "251-500",
  "501-1000",
  "1000+",
] as const;

export type FormeJuridique = (typeof FORME_JURIDIQUE_OPTIONS)[number];
export type Taille = (typeof TAILLE_OPTIONS)[number];

export const SOURCE_TYPE_OPTIONS: {
  value: string;
  label: string;
  niveau: number;
}[] = [
  // Niveau 1 — Constitution
  { value: "constitution", label: "Constitution", niveau: 1 },
  { value: "bloc_constitutionnalite", label: "Bloc de constitutionnalité", niveau: 1 },
  // Niveau 2 — Normes internationales
  { value: "traite_international", label: "Traité international", niveau: 2 },
  { value: "convention_oit", label: "Convention OIT", niveau: 2 },
  { value: "directive_europeenne", label: "Directive européenne", niveau: 2 },
  { value: "reglement_europeen", label: "Règlement européen", niveau: 2 },
  { value: "charte_droits_fondamentaux", label: "Charte des droits fondamentaux", niveau: 2 },
  // Niveau 3 — Lois & Ordonnances
  { value: "code_travail", label: "Code du travail", niveau: 3 },
  { value: "loi", label: "Loi", niveau: 3 },
  { value: "ordonnance", label: "Ordonnance", niveau: 3 },
  { value: "code_securite_sociale", label: "Code de la sécurité sociale", niveau: 3 },
  { value: "code_penal", label: "Code pénal", niveau: 3 },
  { value: "code_civil", label: "Code civil", niveau: 3 },
  // Niveau 4 — Jurisprudence
  { value: "arret_cour_cassation", label: "Arrêt Cour de cassation", niveau: 4 },
  { value: "arret_conseil_etat", label: "Arrêt Conseil d'État", niveau: 4 },
  { value: "decision_conseil_constitutionnel", label: "Décision Conseil constitutionnel", niveau: 4 },
  // Niveau 5 — Réglementaire
  { value: "decret", label: "Décret", niveau: 5 },
  { value: "arrete", label: "Arrêté", niveau: 5 },
  { value: "circulaire", label: "Circulaire", niveau: 5 },
  { value: "code_travail_reglementaire", label: "Code du travail (partie réglementaire)", niveau: 5 },
  // Niveau 6 — Conventions collectives
  { value: "accord_national_interprofessionnel", label: "Accord national interprofessionnel (ANI)", niveau: 6 },
  { value: "accord_branche", label: "Accord de branche", niveau: 6 },
  { value: "convention_collective_nationale", label: "Convention collective nationale (CCN)", niveau: 6 },
  { value: "convention_collective_branche", label: "Convention collective de branche", niveau: 6 },
  { value: "accord_entreprise", label: "Accord d'entreprise", niveau: 6 },
  { value: "accord_performance_collective", label: "Accord de performance collective (APC)", niveau: 6 },
  // Niveau 7 — Usages & Engagements
  { value: "usage_entreprise", label: "Usage d'entreprise", niveau: 7 },
  { value: "engagement_unilateral", label: "Engagement unilatéral", niveau: 7 },
  // Niveau 8 — Règlement intérieur
  { value: "reglement_interieur", label: "Règlement intérieur", niveau: 8 },
  // Niveau 9 — Contrat de travail
  { value: "contrat_travail", label: "Contrat de travail", niveau: 9 },
];

export const NORME_POIDS: Record<number, number> = {
  1: 1.0, 2: 0.95, 3: 0.90, 4: 0.85, 5: 0.80,
  6: 0.75, 7: 0.65, 8: 0.55, 9: 0.50,
};

export interface ChatResponse {
  answer: string;
  sources: Record<string, unknown>[] | null;
}

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}
