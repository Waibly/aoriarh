"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import { useSession } from "next-auth/react";
import type { Organisation, User } from "@/types/api";
import { apiFetch } from "@/lib/api";
import {
  setupOrganisation,
  type CreateOrgData,
} from "@/lib/organisation-setup";
import { toast } from "@/lib/toast";
export type { CreateOrgData } from "@/lib/organisation-setup";

interface OrgContextValue {
  organisations: Organisation[];
  currentOrg: Organisation | null;
  setCurrentOrgId: (id: string) => void;
  loading: boolean;
  refetchOrgs: () => Promise<void>;
  workspaceName: string | null;
  setWorkspaceName: (name: string) => void;
  /** The user owns the displayed workspace and may rename it. */
  isWorkspaceOwner: boolean;
  canCreateOrganisation: boolean;
  /** The workspace only means something once it groups several organisations. */
  showWorkspace: boolean;
  profilMetier: string | null;
  setProfilMetier: (profile: string | null) => void;
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
  isWorkspaceOwner: false,
  canCreateOrganisation: false,
  showWorkspace: false,
  profilMetier: null,
  setProfilMetier: () => {},
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
  const [isWorkspaceOwner, setIsWorkspaceOwner] = useState(false);
  const [workspaceId, setWorkspaceId] = useState<string | null>(null);
  const [canCreateOrganisation, setCanCreateOrganisation] = useState(false);
  const contextRequest = useRef(0);
  const [profilMetier, setProfilMetier] = useState<string | null>(null);

  const token = session?.access_token;

  const fetchUserContext = useCallback(
    async (orgId: string | null) => {
      if (!token) return;
      const request = ++contextRequest.current;
      try {
        const params = orgId ? `?organisation_id=${orgId}` : "";
        const data = await apiFetch<User>(`/users/me${params}`, { token });
        if (request !== contextRequest.current) return;
        setWorkspaceNameState(data.workspace_name);
        setWorkspaceId(data.workspace_id);
        setIsWorkspaceOwner(Boolean(data.is_workspace_owner));
        setCanCreateOrganisation(data.can_create_organisation === true);
        setProfilMetier(data.profil_metier);
      } catch {
        // Non-blocking: workspace name is optional, continue without it
      }
    },
    [token]
  );

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
      if (!token) throw new Error("Connectez-vous pour créer une organisation");
      const { organisation: org, warnings } = await setupOrganisation(
        { ...data, account_id: data.account_id ?? workspaceId },
        token
      );
      if (data.profil_metier) setProfilMetier(data.profil_metier);
      setOrganisations((previous) => [
        ...previous.filter((item) => item.id !== org.id),
        org,
      ]);
      setCurrentOrgIdState(org.id);
      try {
        localStorage.setItem(STORAGE_KEY, org.id);
      } catch {
        /* Optional preference. */
      }
      if (warnings.length) {
        toast.warning(
          "Organisation créée, mais certaines conventions n'ont pas pu être installées",
          {
            description: `${warnings.join(" • ")} — Réessayez depuis Documents.`,
            duration: 10000,
          }
        );
      }
      if (typeof window !== "undefined") {
        window.dispatchEvent(new Event("quota-updated"));
      }
      return org;
    },
    [token, workspaceId]
  );

  const currentOrg = organisations.find((o) => o.id === currentOrgId) ?? null;

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
        isWorkspaceOwner,
        canCreateOrganisation,
        showWorkspace: Boolean(workspaceName) && organisations.length > 1,
        profilMetier,
        setProfilMetier,
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
