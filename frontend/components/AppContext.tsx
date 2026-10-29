"use client";

import type { Session } from "@supabase/supabase-js";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api } from "@/lib/api";
import { supabase } from "@/lib/supabase";
import type { Company, Organization } from "@/lib/types";

interface AppState {
  session: Session | null;
  loading: boolean;
  orgs: Organization[];
  org: Organization | null;
  companies: Company[];
  companyId: string; // "" = todas as empresas
  setOrgId: (id: string) => void;
  setCompanyId: (id: string) => void;
  reload: () => Promise<void>;
  base: string; // prefixo da API da organização atual
  canWrite: boolean;
  isAdmin: boolean;
}

const Ctx = createContext<AppState | null>(null);
const ORG_KEY = "fg.org";
const COMPANY_KEY = "fg.company";

function stored(key: string): string {
  try {
    return localStorage.getItem(key) ?? "";
  } catch {
    return "";
  }
}

function store(key: string, value: string) {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* armazenamento indisponível: preferência apenas em memória */
  }
}

export function AppProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);
  const [orgs, setOrgs] = useState<Organization[]>([]);
  const [orgId, setOrgIdState] = useState("");
  const [companies, setCompanies] = useState<Company[]>([]);
  const [companyId, setCompanyIdState] = useState("");

  useEffect(() => {
    const sb = supabase();
    sb.auth.getSession().then(({ data }) => {
      setSession(data.session);
      if (!data.session) setLoading(false);
    });
    const { data } = sb.auth.onAuthStateChange((_e, s) => setSession(s));
    return () => data.subscription.unsubscribe();
  }, []);

  const reload = useCallback(async () => {
    const list = await api.get<Organization[]>("/api/v1/organizations");
    setOrgs(list);
    const preferred = stored(ORG_KEY);
    const current = list.find((o) => o.id === preferred) ?? list[0];
    setOrgIdState(current?.id ?? "");
    setLoading(false);
  }, []);

  useEffect(() => {
    if (session) reload().catch(() => setLoading(false));
  }, [session, reload]);

  useEffect(() => {
    if (!orgId) return;
    api.get<Company[]>(`/api/v1/organizations/${orgId}/companies`).then((list) => {
      setCompanies(list);
      const preferred = stored(COMPANY_KEY);
      setCompanyIdState(list.some((c) => c.id === preferred) ? preferred : "");
    });
  }, [orgId]);

  const org = orgs.find((o) => o.id === orgId) ?? null;
  const value = useMemo<AppState>(
    () => ({
      session,
      loading,
      orgs,
      org,
      companies,
      companyId,
      setOrgId: (id) => {
        store(ORG_KEY, id);
        setOrgIdState(id);
      },
      setCompanyId: (id) => {
        store(COMPANY_KEY, id);
        setCompanyIdState(id);
      },
      reload,
      base: org ? `/api/v1/organizations/${org.id}` : "",
      canWrite: org?.role === "admin" || org?.role === "operator",
      isAdmin: org?.role === "admin",
    }),
    [session, loading, orgs, org, companies, companyId, reload],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useApp(): AppState {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useApp fora do AppProvider");
  return ctx;
}

/** Carrega dados da API com estado de carregamento/erro e função de recarga. */
export function useLoad<T>(loader: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const run = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await loader());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao carregar");
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(() => {
    run();
  }, [run]);
  return { data, error, loading, reload: run, setData };
}
