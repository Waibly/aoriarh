import { apiFetch } from "@/lib/api";
import type { CcnReference, Organisation } from "@/types/api";

export interface CreateOrgData {
  name: string;
  account_id?: string | null;
  forme_juridique?: string | null;
  taille?: string | null;
  convention_collective?: string | null;
  secteur_activite?: string | null;
  not_subject_to_ccn?: boolean;
  territoire?: string;
  profil_metier?: string | null;
  selectedCcn?: CcnReference[];
}

export interface OrganisationSetupProgress {
  organisation?: Organisation;
  profileSaved?: string;
  installedCcnIds?: Set<string>;
}

/** Keep completed writes across user-requested retries of the signup form. */
export async function setupOrganisation(
  data: CreateOrgData,
  token: string,
  progress: OrganisationSetupProgress = {}
): Promise<{ organisation: Organisation; warnings: string[] }> {
  const { profil_metier, selectedCcn, ...orgData } = data;
  // Save the profile first: a rejected profile must never leave an organisation
  // that a second click would create again.
  if (profil_metier && progress.profileSaved !== profil_metier) {
    await apiFetch("/users/me", {
      method: "PATCH",
      token,
      body: JSON.stringify({ profil_metier }),
    });
    progress.profileSaved = profil_metier;
  }
  if (!progress.organisation) {
    progress.organisation = await apiFetch<Organisation>("/organisations/", {
      method: "POST",
      token,
      body: JSON.stringify(orgData),
    });
  }
  const organisation = progress.organisation;
  const warnings: string[] = [];
  progress.installedCcnIds ??= new Set();
  if (!data.not_subject_to_ccn) {
    for (const ccn of selectedCcn ?? []) {
      if (progress.installedCcnIds.has(ccn.idcc)) continue;
      try {
        await apiFetch(`/conventions/organisations/${organisation.id}`, {
          method: "POST",
          token,
          body: JSON.stringify({ idcc: ccn.idcc }),
        });
        progress.installedCcnIds.add(ccn.idcc);
      } catch (error) {
        warnings.push(
          `IDCC ${ccn.idcc} : ${error instanceof Error ? error.message : "erreur réseau"}`
        );
      }
    }
  }
  return { organisation, warnings };
}
