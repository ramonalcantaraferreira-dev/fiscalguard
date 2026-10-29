"use client";

import Link from "next/link";
import { useState } from "react";
import { useApp, useLoad } from "@/components/AppContext";
import { Badge, Button, Card, ErrorBox, Input, PageHeader, Select, Table } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { cnpj, dateTimeBR, label } from "@/lib/format";
import type { Supplier } from "@/lib/types";

interface ImportReport { total: number; created: number; updated: number; linked: number; rejected: number; errors: { line: number; errors: string[] }[] }

export default function SuppliersPage() {
  const { base, companyId, canWrite } = useApp();
  const [status, setStatus] = useState("");
  const [q, setQ] = useState("");
  const list = useLoad(() => api.get<Supplier[]>(`${base}/suppliers`, { company_id: companyId, status, q }), [base, companyId, status, q]);
  const [report, setReport] = useState<ImportReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function importCsv(file: File) {
    setBusy(true);
    setError(null);
    try {
      const form = new FormData();
      form.append("file", file);
      setReport(await api.upload<ImportReport>(`${base}/suppliers/import`, form));
      list.reload();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  async function scan() {
    try {
      await api.post(`${base}/compliance/scan`);
      list.reload();
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  return (
    <>
      <PageHeader
        title="Fornecedores"
        subtitle="Cadastro, vínculos com empresas e situação de compliance"
        actions={
          <>
            <Button variant="secondary" onClick={() => api.download(`${base}/compliance/report`, "compliance.csv", { format: "csv", company_id: companyId })}>
              Exportar relatório
            </Button>
            {canWrite && <Button variant="secondary" onClick={scan}>Recalcular situação</Button>}
            {canWrite && (
              <label className={`inline-flex min-h-9 cursor-pointer items-center rounded-md bg-brand px-3 text-sm font-medium text-white ${busy ? "opacity-50" : ""}`}>
                Importar CSV
                <input type="file" accept=".csv,text/csv" className="hidden" disabled={busy}
                  onChange={(e) => { const f = e.target.files?.[0]; if (f) importCsv(f); e.target.value = ""; }} />
              </label>
            )}
          </>
        }
      />
      <div className="space-y-4">
        <ErrorBox error={error ?? list.error} />
        {report && (
          <Card title="Resultado da importação" actions={<Button variant="ghost" onClick={() => setReport(null)}>Fechar</Button>}>
            <p className="text-sm">
              {report.total} linhas · {report.created} criados · {report.updated} atualizados · {report.linked} vínculos · {report.rejected} rejeitadas
            </p>
            {report.errors.length > 0 && (
              <ul className="mt-2 max-h-48 overflow-auto text-sm text-danger">
                {report.errors.map((e, i) => <li key={i}>Linha {e.line}: {e.errors.join("; ")}</li>)}
              </ul>
            )}
            <p className="mt-2 text-xs text-ink-muted">Colunas aceitas: cnpj; razao_social; nome_fantasia; uf; regime; email; telefone; empresas (CNPJs separados por |).</p>
          </Card>
        )}
        <Card title="Lista" actions={
          <div className="flex flex-wrap gap-2">
            <Input placeholder="Buscar nome ou CNPJ" value={q} onChange={(e) => setQ(e.target.value)} className="w-52" />
            <Select value={status} onChange={(e) => setStatus(e.target.value)} className="w-44">
              <option value="">Todas as situações</option>
              {["regular", "pending", "irregular", "expired", "unknown"].map((s) => <option key={s} value={s}>{label(s)}</option>)}
            </Select>
          </div>
        }>
          <Table head={["Fornecedor", "CNPJ", "UF", "Situação", "Atualizado em"]} empty={!list.loading && !list.data?.length}>
            {list.data?.map((s) => (
              <tr key={s.id}>
                <td><Link className="font-medium text-brand" href={`/suppliers/${s.id}`}>{s.legal_name}</Link></td>
                <td className="whitespace-nowrap font-mono text-xs">{cnpj(s.cnpj)}</td>
                <td>{s.uf ?? "—"}</td>
                <td><Badge value={s.compliance_status} /></td>
                <td>{dateTimeBR(s.compliance_updated_at)}</td>
              </tr>
            ))}
          </Table>
        </Card>
      </div>
    </>
  );
}
