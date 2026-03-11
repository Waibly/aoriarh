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
}

const OrgContext = createContext<OrgContextValue>({
  organisations: [],
  currentOrg: null,
  setCurrentOrgId: () => {},
  loading: true,
  refetchOrgs: async () => {},
});

const STORAGE_KEY = "aoriarh_current_org_id";

export function OrgProvider({ children }: { children: React.ReactNode }) {
  const { data: session } = useSession();
  const [organisations, setOrganisations] = useState<Organisation[]>([]);
  const [currentOrgId, setCurrentOrgIdState] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const token = session?.access_token;

  const fetchOrgs = useCallback(async () => {
    if (!token) {
      // Session pas encore chargée — on reste en loading
      // pour ne pas déclencher la modale "créer org" à tort.
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
      }}
    >
      {children}
    </OrgContext.Provider>
  );
}

export function useOrg() {
  return useContext(OrgContext);
}
