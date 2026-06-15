import { apiFetch, authFetch } from "@/lib/api";

export interface Fiche {
  id: string;
  title: string;
  created_at: string;
  message_id: string | null;
}

export async function listFiches(
  organisationId: string,
  token: string,
): Promise<Fiche[]> {
  return apiFetch<Fiche[]>(
    `/fiches/?organisation_id=${organisationId}`,
    { token },
  );
}

export async function deleteFiche(
  ficheId: string,
  token: string,
): Promise<void> {
  await apiFetch<void>(`/fiches/${ficheId}`, {
    method: "DELETE",
    token,
  });
}

/**
 * Régénère le PDF d'une fiche et l'ouvre dans un nouvel onglet (aperçu).
 * L'onglet est ouvert de façon synchrone pour éviter le blocage des popups.
 */
export async function viewFicheById(
  ficheId: string,
  token: string,
): Promise<void> {
  const win = window.open("", "_blank");
  try {
    const response = await authFetch(`/fiches/${ficheId}/pdf`, {
      method: "GET",
      token,
    });
    if (!response.ok) {
      throw new Error("L'aperçu de la fiche a échoué. Veuillez réessayer.");
    }
    const blob = await response.blob();
    const url = window.URL.createObjectURL(blob);
    if (win) {
      win.location.href = url;
    } else {
      window.open(url, "_blank");
    }
    setTimeout(() => window.URL.revokeObjectURL(url), 60_000);
  } catch (err) {
    win?.close();
    throw err;
  }
}

/**
 * Régénère le PDF d'une fiche enregistrée et déclenche son téléchargement.
 * Le PDF est régénéré côté serveur avec la date du jour (pas de version figée).
 */
export async function downloadFicheById(
  ficheId: string,
  token: string,
): Promise<void> {
  const response = await authFetch(`/fiches/${ficheId}/pdf`, {
    method: "GET",
    token,
  });

  if (!response.ok) {
    throw new Error("Le téléchargement de la fiche a échoué. Veuillez réessayer.");
  }

  const blob = await response.blob();
  const disposition = response.headers.get("Content-Disposition") || "";
  const match = disposition.match(/filename="?([^"]+)"?/);
  const filename = match?.[1] || "fiche-pratique.pdf";

  const url = window.URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.URL.revokeObjectURL(url);
}
