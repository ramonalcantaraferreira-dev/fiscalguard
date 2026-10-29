"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { supabase } from "@/lib/supabase";
import { label } from "@/lib/format";
import { useApp } from "./AppContext";
import { Select } from "./ui";

const NAV = [
  { href: "/dashboard", text: "Painel" },
  { href: "/companies", text: "Empresas" },
  { href: "/suppliers", text: "Fornecedores" },
  { href: "/documents", text: "Documentos fiscais" },
  { href: "/opportunities", text: "Oportunidades" },
  { href: "/alerts", text: "Alertas" },
  { href: "/rules", text: "Regras tributárias" },
  { href: "/jobs", text: "Importações e tarefas" },
  { href: "/audit", text: "Auditoria", admin: true },
];

export function Shell({ children }: { children: ReactNode }) {
  const { session, loading, orgs, org, setOrgId, companies, companyId, setCompanyId, isAdmin } = useApp();
  const router = useRouter();
  const pathname = usePathname();
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (loading) return;
    if (!session) router.replace("/login");
    else if (orgs.length === 0 && pathname !== "/onboarding") router.replace("/onboarding");
  }, [loading, session, orgs.length, pathname, router]);

  useEffect(() => setOpen(false), [pathname]);

  if (loading || !session) {
    return <div className="grid min-h-screen place-items-center text-sm text-ink-muted">Carregando…</div>;
  }
  if (!org) {
    if (pathname === "/onboarding") return <main className="mx-auto max-w-xl p-4 md:p-8">{children}</main>;
    return <div className="grid min-h-screen place-items-center text-sm text-ink-muted">Carregando…</div>;
  }

  return (
    <div className="min-h-screen md:grid md:grid-cols-[240px_1fr]">
      <aside className={`${open ? "block" : "hidden"} border-b border-line bg-surface md:block md:min-h-screen md:border-r md:border-b-0`}>
        <div className="hidden px-4 py-5 md:block">
          <p className="text-base font-semibold text-ink">FiscalGuard</p>
          <p className="text-xs text-ink-muted">Compliance e inteligência fiscal</p>
        </div>
        <nav className="flex flex-col gap-0.5 p-2">
          {NAV.filter((n) => !n.admin || isAdmin).map((n) => {
            const active = pathname === n.href || pathname.startsWith(`${n.href}/`);
            return (
              <Link key={n.href} href={n.href}
                className={`rounded-md px-3 py-2 text-sm ${active ? "bg-brand-soft font-medium text-brand" : "text-ink hover:bg-subtle"}`}>
                {n.text}
              </Link>
            );
          })}
        </nav>
      </aside>

      <div className="min-w-0">
        <header className="sticky top-0 z-10 flex flex-wrap items-center gap-2 border-b border-line bg-surface/95 px-4 py-2 backdrop-blur">
          <button className="rounded-md border border-line px-2 py-1 text-sm md:hidden" onClick={() => setOpen(!open)} aria-label="Menu">☰</button>
          <span className="font-semibold md:hidden">FiscalGuard</span>
          <div className="ml-auto flex w-full flex-wrap items-center gap-2 sm:w-auto">
            {orgs.length > 1 && (
              <Select aria-label="Escritório" value={org.id} onChange={(e) => setOrgId(e.target.value)} className="w-full sm:w-52">
                {orgs.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
              </Select>
            )}
            <Select aria-label="Empresa" value={companyId} onChange={(e) => setCompanyId(e.target.value)} className="w-full sm:w-60">
              <option value="">Todas as empresas</option>
              {companies.map((c) => <option key={c.id} value={c.id}>{c.trade_name || c.legal_name}</option>)}
            </Select>
            <span className="hidden text-xs text-ink-muted lg:inline">{session.user.email} · {label(org.role)}</span>
            <button className="text-sm text-ink-muted hover:text-ink" onClick={() => supabase().auth.signOut()}>Sair</button>
          </div>
        </header>
        <main className="mx-auto max-w-7xl p-4 md:p-6">{children}</main>
      </div>
    </div>
  );
}
