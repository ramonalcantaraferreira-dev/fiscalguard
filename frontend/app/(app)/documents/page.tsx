"use client";

import Link from "next/link";
import { useState } from "react";
import { useApp, useLoad } from "@/components/AppContext";
import { Badge, Button, Card, ErrorBox, Input, Notice, PageHeader, Select, Table } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { cnpj, dateBR, label, money } from "@/lib/format";
import type { FiscalDocument, Job } from "@/lib/types";

export default function DocumentsPage() {
  const { base, companyId, companies, canWrite } = useApp();
  const [filters, setFilters] = useState({ status: "", direction: "", q: "" });
  const list = useLoad(() => api.get<FiscalDocument[]>(`${base}/fiscal-documents`, { company_id: companyId, ...filters }), [base, companyId, filters]);
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function upload(files: FileList) {
    if (!companyId) return;
    setBusy(true);
    setError(null);
    try {
      const form = new FormData();
      Array.from(files).forEach((f) => form.append("files", f));
      setJob(await api.upload<Job>(`${base}/companies/${companyId}/fiscal-documents/import`, form));
      list.reload();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  const companyName = (id: string) => companies.find((c) => c.id === id)?.legal_name ?? "";

  return (
    <>
      <PageHeader title="Documentos fiscais" subtitle="NF-e importadas, validações e análises"
        actions={canWrite && (
          <label className={`inline-flex min-h-9 items-center rounded-md bg-brand px-3 text-sm font-medium text-white ${!companyId || busy ? "cursor-not-allowed opacity-50" : "cursor-pointer"}`}>
            {busy ? "Importando…" : "Importar XML de NF-e"}
            <input type="file" multiple accept=".xml,application/xml,text/xml" className="hidden" disabled={!companyId || busy}
              onChange={(e) => { if (e.target.files?.length) upload(e.target.files); e.target.value = ""; }} />
          </label>
        )} />
      <div className="space-y-4">
        {canWrite && !companyId && <Notice>Selecione uma empresa no topo da página para importar XMLs.</Notice>}
        <ErrorBox error={error ?? list.error} />
        {job && (
          <Card title="Resultado da importação" actions={<Button variant="ghost" onClick={() => setJob(null)}>Fechar</Button>}>
            {job.status === "queued" ? (
              <p className="text-sm">Lote enfileirado para processamento. Acompanhe em <Link className="text-brand" href="/jobs">Importações e tarefas</Link>.</p>
            ) : (
              <>
                <p className="mb-2 text-sm">{Object.entries(job.result?.summary ?? {}).map(([k, v]) => `${v} ${label(k).toLowerCase()}`).join(" · ")}</p>
                <ul className="max-h-48 space-y-1 overflow-auto text-sm">
                  {job.result?.files?.filter((f) => f.status !== "imported").map((f, i) => (
                    <li key={i}><Badge value={f.status} /> {f.file}: {(f.errors ?? f.issues ?? []).map((e) => e.message).join("; ") || "já importado"}</li>
                  ))}
                </ul>
              </>
            )}
          </Card>
        )}
        <Card title="Documentos" actions={
          <div className="flex flex-wrap gap-2">
            <Input placeholder="Chave, CNPJ ou emitente" className="w-52" value={filters.q} onChange={(e) => setFilters({ ...filters, q: e.target.value })} />
            <Select className="w-36" value={filters.direction} onChange={(e) => setFilters({ ...filters, direction: e.target.value })}>
              <option value="">Entrada e saída</option><option value="inbound">Entrada</option><option value="outbound">Saída</option>
            </Select>
            <Select className="w-36" value={filters.status} onChange={(e) => setFilters({ ...filters, status: e.target.value })}>
              <option value="">Todos</option><option value="validated">Validados</option><option value="invalid">Com erros</option>
            </Select>
          </div>
        }>
          <Table head={["Emissão", "Número", "Emitente", "Empresa", "Tipo", "Valor", "Status"]} empty={!list.loading && !list.data?.length}>
            {list.data?.map((d) => (
              <tr key={d.id}>
                <td className="whitespace-nowrap">{dateBR(d.issue_date)}</td>
                <td><Link className="text-brand" href={`/documents/${d.id}`}>{d.number}/{d.series}</Link></td>
                <td><p>{d.issuer_name}</p><p className="font-mono text-xs text-ink-muted">{cnpj(d.issuer_cnpj)}</p></td>
                <td className="text-xs">{companyName(d.company_id)}</td>
                <td>{label(d.direction)}</td>
                <td className="tabular-nums whitespace-nowrap">{money(d.total_amount)}</td>
                <td><Badge value={d.status} /></td>
              </tr>
            ))}
          </Table>
        </Card>
      </div>
    </>
  );
}
