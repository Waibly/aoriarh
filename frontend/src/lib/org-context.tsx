"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";
import { useSession } from "next-auth/react";
import type { Organisation, CcnReference } from "@/types/api";
import { apiFetch } from "@/lib/api";

export interface CreateOrgData {
  name: string;
  forme_juridique?: string | null;
  taille?: string | null;
  convention_collective?: string | null;
  secteur_activite?: string | null;
  not_subject_to_ccn?: boolean;
  profil_metier?: string | null;
  selectedCcn?: CcnReference[];
}

interface OrgContextValue {
  organisations: Organisation[];
  currentOrg: Organisation | null;
  setCurrentOrgId: (id: string) => void;
  loading: boolean;
  refetchOrgs: () => Promise<void>;
  workspaceName: string | null;
  setWorkspaceName: (name: string) => void;
  createOrganisation: (data: CreateOrgData) => Promise<Organisation>;
}

const OrgContext = createContext<OrgContextValue>({
  organisations: [],
  currentOrg: null,
  setCurrentOrgId: () => {},
  loading: true,
  refetchOrgs: async () => {},
  workspaceName: null,
  setWorkspaceName: () => {},
  createOrganisation: async () => {
    throw new Error("OrgContext not initialised");
  },
});

const STORAGE_KEY = "aoriarh_current_org_id";

export function OrgProvider({ children }: { children: React.ReactNode }) {
  const { data: session } = useSession();
  const [organisations, setOrganisations] = useState<Organisation[]>([]);
  const [currentOrgId, setCurrentOrgIdState] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [workspaceName, setWorkspaceNameState] = useState<string | null>(null);

  const token = session?.access_token;

  const fetchUserContext = useCallback(async (orgId: string | null) => {
    if (!token) return;
    try {
      const params = orgId ? `?organisation_id=${orgId}` : "";
      const data = await apiFetch<{ workspace_name: string | null }>(`/users/me${params}`, { token });
      setWorkspaceNameState(data.workspace_name);
    } catch {
      // Non-blocking: workspace name is optional, continue without it
    }
  }, [token]);

  const fetchOrgs = useCallback(async () => {
    if (!token) {
      return;
    }
    setLoading(true);
    try {
      const orgs = await apiFetch<Organisation[]>("/organisations/", { token });
      setOrganisations(orgs);

      const savedId = localStorage.getItem(STORAGE_KEY);
      const savedOrg = orgs.find((o) => o.id === savedId);
      if (savedOrg) {
        setCurrentOrgIdState(savedOrg.id);
      } else if (orgs.length > 0) {
        setCurrentOrgIdState(orgs[0].id);
        localStorage.setItem(STORAGE_KEY, orgs[0].id);
      } else {
        setCurrentOrgIdState(null);
        localStorage.removeItem(STORAGE_KEY);
      }
    } catch {
      // Network error or 401 (handled by apiFetch) — show empty state
      setOrganisations([]);
      setCurrentOrgIdState(null);
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    fetchOrgs();
  }, [fetchOrgs]);

  // Refresh workspace/plan when current org changes
  useEffect(() => {
    fetchUserContext(currentOrgId);
  }, [currentOrgId, fetchUserContext]);

  const setCurrentOrgId = (id: string) => {
    setCurrentOrgIdState(id);
    localStorage.setItem(STORAGE_KEY, id);
  };

  const createOrganisation = useCallback(
    async (data: CreateOrgData): Promise<Organisation> => {
      const { profil_metier, selectedCcn, not_subject_to_ccn, ...orgData } = data;
      // not_subject_to_ccn n'est pas encore persisté côté backend (commit 2)
      // mais on l'utilise déjà côté front pour décider d'installer ou pas une CCN
      const org = await apiFetch<Organisation>("/organisations/", {
        method: "POST",
        token,
        body: JSON.stringify(orgData),
      });
      if (profil_metier) {
        await apiFetch("/users/me", {
          method: "PATCH",
          token,
          body: JSON.stringify({ profil_metier }),
        });
      }
      if (!not_subject_to_ccn && selectedCcn && selectedCcn.length > 0) {
        for (const ccn of selectedCcn) {
          apiFetch(`/conventions/organisations/${org.id}`, {
            method: "POST",
            token,
            body: JSON.stringify({ idcc: ccn.idcc }),
          }).catch(() => {});
        }
      }
      if (typeof window !== "undefined") {
        window.dispatchEvent(new Event("quota-updated"));
      }
      await fetchOrgs();
      setCurrentOrgIdState(org.id);
      localStorage.setItem(STORAGE_KEY, org.id);
      return org;
    },
    [token, fetchOrgs],
  );

  const currentOrg =
    organisations.find((o) => o.id === currentOrgId) ?? null;

  return (
    <OrgContext.Provider
      value={{
        organisations,
        currentOrg,
        setCurrentOrgId,
        loading,
        refetchOrgs: fetchOrgs,
        workspaceName,
        setWorkspaceName: setWorkspaceNameState,
        createOrganisation,
      }}
    >
      {children}
    </OrgContext.Provider>
  );
}

export function useOrg() {
  return useContext(OrgContext);
}
