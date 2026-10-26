export const ACCOUNT_STATUS_LABELS: Record<string, string> = {
  active: "Actif",
  trialing: "En essai",
  past_due: "Paiement en retard",
  suspended: "Suspendu",
  canceled: "Résilié",
  unpaid: "Impayé",
  incomplete: "À finaliser",
  incomplete_expired: "Non finalisé",
};

export const formatAdminEur = (value: number) =>
  new Intl.NumberFormat("fr-FR", {
    style: "currency",
    currency: "EUR",
    maximumFractionDigits: 2,
  }).format(value);

export type AdminClient = {
  account_id: string;
  account_name: string | null;
  owner_email: string | null;
  registered_at: string;
  plan: string;
  status: string;
  mrr_eur: number;
  questions_30d: number;
  infra_cost_eur_30d: number;
  margin_eur: number;
  last_activity_at: string | null;
};

export type AdminClientsResponse = {
  rows: AdminClient[];
  total: number;
  page: number;
  page_size: number;
};
