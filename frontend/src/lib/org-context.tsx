"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";
import { useSession } from "next-auth/react";
import type { Organisation } from "@/types/api";
import { apiFetch } from "@/lib/api";

interface OrgContextValue {
  organisations: Organisation[];
  currentOrg: Organisation | null;
  setCurrentOrgId: (id: string) => void;
  loading: boolean;
  refetchOrgs: () => Promise<void>;
  workspaceName: string | null;
  setWorkspaceName: (name: string) => void;
}

const OrgContext = createContext<OrgContextValue>({
  organisations: [],
  currentOrg: null,
  setCurrentOrgId: () => {},
  loading: true,
  refetchOrgs: async () => {},
  workspaceName: null,
  setWorkspaceName: () => {},
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
      // ignore
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
      }}
    >
      {children}
    </OrgContext.Provider>
  );
}

export function useOrg() {
  return useContext(OrgContext);
}
