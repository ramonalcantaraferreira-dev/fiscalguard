"use client";

import Link from "next/link";
import { useState } from "react";
import { useApp, useLoad } from "@/components/AppContext";
import { Criteria } from "@/components/Criteria";
import { Badge, Button, Card, ErrorBox, Notice, PageHeader, Select, Table } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { label, money } from "@/lib/format";
import type { Assessment } from "@/lib/types";

export default function OpportunitiesPage() {
  const { base, companyId, canWrite } = useApp();
  const [status, setStatus] = useState("pending_review");
  const [tax, setTax] = useState("");
  const list = useLoad(() => api.get<Assessment[]>(`${base}/assessments`, { company_id: companyId, review_status: status, tax }), [base, companyId, status, tax]);
  const [open, setOpen] = useState<Assessment | null>(null);
  const [notes, setNotes] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function review(decision: "approved" | "rejected" | "needs_info") {
    if (!open) return;
    try {
      await api.patch(`${base}/assessments/${open.id}/review`, { review_status: decision, review_notes: notes || null });
      setOpen(null);
      setNotes("");
      list.reload();
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  return (
    <>
      <PageHeader title="Oportunidades e riscos" subtitle="Resultados do motor de regras para revisão humana"
        actions={<Button variant="secondary" onClick={() => api.download(`${base}/assessments/export`, "oportunidades.csv", { company_id: companyId, review_status: status, tax })}>Exportar CSV</Button>} />
      <div className="space-y-4">
        <Notice>
          Cada resultado é uma <strong>oportunidade potencial</strong>. Antes de aproveitar qualquer crédito, confirme a
          destinação dos itens, a escrituração e a legislação aplicável. A decisão de revisão fica registrada na auditoria.
        </Notice>
        <ErrorBox error={error ?? list.error} />
        <Card title="Resultados" actions={
          <div className="flex gap-2">
            <Select className="w-44" value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">Todos os status</option>
              {["pending_review", "needs_info", "approved", "rejected"].map((s) => <option key={s} value={s}>{label(s)}</option>)}
            </Select>
            <Select className="w-36" value={tax} onChange={(e) => setTax(e.target.value)}>
              <option value="">Todos os tributos</option>
              {["ICMS", "PIS/COFINS", "IPI", "RISCO"].map((t) => <option key={t} value={t}>{t}</option>)}
            </Select>
          </div>
        }>
          <Table head={["Tributo", "Emitente", "Regra", "Estimativa", "Status", ""]} empty={!list.loading && !list.data?.length}>
            {list.data?.map((a) => (
              <tr key={a.id}>
                <td>{a.tax}</td>
                <td><Link className="text-brand" href={`/documents/${a.document_id}`}>{a.issuer_name ?? a.access_key}</Link></td>
                <td className="text-xs">{a.rule_code} v{a.rule_version}</td>
                <td className="tabular-nums">{a.tax === "RISCO" ? "—" : money(a.estimated_amount)}</td>
                <td><Badge value={a.review_status} /></td>
                <td><Button variant="secondary" onClick={() => { setOpen(a); setNotes(a.review_notes ?? ""); }}>Detalhes</Button></td>
              </tr>
            ))}
          </Table>
        </Card>
      </div>

      {open && (
        <div className="fixed inset-0 z-20 flex justify-end bg-black/40" onClick={() => setOpen(null)}>
          <aside className="h-full w-full max-w-xl overflow-y-auto bg-surface p-5" onClick={(e) => e.stopPropagation()}>
            <div className="mb-4 flex items-start justify-between gap-3">
              <div>
                <h2 className="text-lg font-semibold">{open.tax} · {money(open.estimated_amount)}</h2>
                <p className="text-xs text-ink-muted">{open.rule_code} versão {open.rule_version}</p>
              </div>
              <Button variant="ghost" onClick={() => setOpen(null)}>Fechar</Button>
            </div>
            <section className="space-y-4 text-sm">
              <div><h3 className="mb-1 font-medium">Justificativa</h3><p>{open.justification}</p></div>
              <div><h3 className="mb-1 font-medium">Critérios aplicados</h3><Criteria node={open.criteria} /></div>
              <div>
                <h3 className="mb-1 font-medium">Evidências</h3>
                {open.evidence.map((ev, i) => (
                  <dl key={i} className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
                    <dt className="text-ink-muted">Chave</dt><dd className="font-mono break-all">{String(ev.access_key)}</dd>
                    <dt className="text-ink-muted">Item</dt><dd>{String(ev.item_number ?? "documento")}</dd>
                    <dt className="text-ink-muted">Base legal</dt><dd>{String(ev.rule_legal_basis ?? "—")}</dd>
                    <dt className="text-ink-muted">Validação</dt>
                    <dd>{ev.rule_validated_by_specialist ? String(ev.rule_validated_by_specialist) : <span className="text-warn">Regra não validada por especialista</span>}</dd>
                  </dl>
                ))}
              </div>
              {canWrite && (
                <div className="space-y-2 border-t border-line pt-4">
                  <label className="block font-medium" htmlFor="notes">Notas da revisão</label>
                  <textarea id="notes" className="min-h-24 w-full rounded-md border border-line bg-surface p-2" value={notes} onChange={(e) => setNotes(e.target.value)} />
                  <div className="flex flex-wrap gap-2">
                    <Button onClick={() => review("approved")}>Aprovar</Button>
                    <Button variant="secondary" onClick={() => review("needs_info")}>Solicitar informação</Button>
                    <Button variant="danger" onClick={() => review("rejected")}>Rejeitar</Button>
                  </div>
                </div>
              )}
            </section>
          </aside>
        </div>
      )}
    </>
  );
}
