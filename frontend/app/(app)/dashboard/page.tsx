"use client";

import Link from "next/link";
import { useApp, useLoad } from "@/components/AppContext";
import { Badge, Card, ErrorBox, Notice, PageHeader, Stat, Table } from "@/components/ui";
import { api } from "@/lib/api";
import { dateTimeBR, label, money } from "@/lib/format";

interface Dashboard {
  companies: { total: number; active: number };
  suppliers_by_status: { status: string; count: number }[];
  documents: { total: number; invalid: number; not_analyzed: number };
  opportunities: { tax: string; review_status: string; count: number; estimated_amount: number }[];
  open_alerts: { severity: string; count: number }[];
  recent_jobs: { id: string; kind: string; status: string; created_at: string }[];
}

export default function DashboardPage() {
  const { base, companyId } = useApp();
  const { data, error } = useLoad(() => api.get<Dashboard>(`${base}/dashboard`, { company_id: companyId }), [base, companyId]);

  const suppliers = Object.fromEntries((data?.suppliers_by_status ?? []).map((s) => [s.status, s.count]));
  const totalSuppliers = Object.values(suppliers).reduce((a, b) => a + b, 0);
  const pending = (data?.opportunities ?? []).filter((o) => o.review_status === "pending_review" && o.tax !== "RISCO");
  const approved = (data?.opportunities ?? []).filter((o) => o.review_status === "approved" && o.tax !== "RISCO");
  const sum = (rows: { estimated_amount: number }[]) => rows.reduce((a, r) => a + Number(r.estimated_amount), 0);
  const alerts = Object.fromEntries((data?.open_alerts ?? []).map((a) => [a.severity, a.count]));

  return (
    <>
      <PageHeader title="Painel" subtitle={companyId ? "Empresa selecionada" : "Visão consolidada do escritório"} />
      <ErrorBox error={error} />
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Fornecedores" value={totalSuppliers}
          hint={`${suppliers.regular ?? 0} regular(es) · ${(suppliers.irregular ?? 0) + (suppliers.expired ?? 0)} com pendência crítica`} />
        <Stat label="Documentos fiscais" value={data?.documents.total ?? "—"}
          hint={`${data?.documents.invalid ?? 0} com erros de validação`} />
        <Stat label="Oportunidades em revisão" value={money(sum(pending))} hint={`${pending.reduce((a, r) => a + r.count, 0)} itens aguardando revisão`} />
        <Stat label="Alertas abertos" value={(alerts.critical ?? 0) + (alerts.warning ?? 0) + (alerts.info ?? 0)}
          hint={`${alerts.critical ?? 0} crítico(s)`} />
      </div>

      <div className="mt-4">
        <Notice>
          Valores são <strong>estimativas de oportunidades potenciais</strong>, calculadas por regras determinísticas.
          Nenhum resultado representa crédito aproveitável sem revisão e validação por especialista.
        </Notice>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Card title="Oportunidades por tributo" actions={<Link className="text-sm text-brand" href="/opportunities">Revisar</Link>}>
          <Table head={["Tributo", "Status", "Itens", "Estimativa"]} empty={!data?.opportunities.length}>
            {data?.opportunities.map((o) => (
              <tr key={`${o.tax}-${o.review_status}`}>
                <td>{o.tax}</td>
                <td><Badge value={o.review_status} /></td>
                <td className="tabular-nums">{o.count}</td>
                <td className="tabular-nums">{o.tax === "RISCO" ? "—" : money(o.estimated_amount)}</td>
              </tr>
            ))}
          </Table>
          {approved.length > 0 && <p className="mt-3 text-sm text-ink-muted">Aprovado em revisão: {money(sum(approved))}</p>}
        </Card>
        <Card title="Importações recentes" actions={<Link className="text-sm text-brand" href="/jobs">Ver todas</Link>}>
          <Table head={["Tipo", "Status", "Criada em"]} empty={!data?.recent_jobs.length}>
            {data?.recent_jobs.map((j) => (
              <tr key={j.id}>
                <td>{label(j.kind)}</td>
                <td><Badge value={j.status} /></td>
                <td>{dateTimeBR(j.created_at)}</td>
              </tr>
            ))}
          </Table>
        </Card>
      </div>
    </>
  );
}
