"use client";

import { useParams } from "next/navigation";
import { useApp, useLoad } from "@/components/AppContext";
import { Badge, Button, Card, ErrorBox, PageHeader, Table } from "@/components/ui";
import { api } from "@/lib/api";
import { cnpj, dateBR, dateTimeBR, label, money } from "@/lib/format";
import type { Assessment, FiscalDocument, FiscalItem } from "@/lib/types";

export default function DocumentDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { base, canWrite } = useApp();
  const doc = useLoad(() => api.get<FiscalDocument & { items: FiscalItem[] }>(`${base}/fiscal-documents/${id}`), [base, id]);
  const found = useLoad(() => api.get<Assessment[]>(`${base}/assessments`, { document_id: id }), [base, id]);
  const d = doc.data;

  async function reanalyze() {
    await api.post(`${base}/fiscal-documents/${id}/analyze`);
    doc.reload();
    found.reload();
  }

  return (
    <>
      <PageHeader
        title={d ? `NF-e ${d.number}/${d.series}` : "Documento"}
        subtitle={d ? `Chave ${d.access_key}` : undefined}
        actions={
          <>
            <Button variant="secondary" onClick={() => api.download(`${base}/fiscal-documents/${id}/xml`, `${d?.access_key}.xml`)}>Baixar XML</Button>
            {canWrite && <Button onClick={reanalyze}>Reprocessar análise</Button>}
          </>
        }
      />
      <div className="space-y-4">
        <ErrorBox error={doc.error} />
        {d && (
          <div className="grid gap-4 lg:grid-cols-3">
            <Card title="Dados gerais">
              <dl className="grid grid-cols-2 gap-2 text-sm">
                <dt className="text-ink-muted">Emissão</dt><dd>{dateBR(d.issue_date)}</dd>
                <dt className="text-ink-muted">Tipo</dt><dd>{label(d.direction)}</dd>
                <dt className="text-ink-muted">Status</dt><dd><Badge value={d.status} /></dd>
                <dt className="text-ink-muted">Analisado em</dt><dd>{dateTimeBR(d.analyzed_at)}</dd>
              </dl>
            </Card>
            <Card title="Participantes">
              <p className="text-sm font-medium">{d.issuer_name}</p>
              <p className="font-mono text-xs text-ink-muted">Emitente {cnpj(d.issuer_cnpj)}</p>
              <p className="mt-2 text-sm font-medium">{d.recipient_name}</p>
            </Card>
            <Card title="Totais">
              <dl className="grid grid-cols-2 gap-2 text-sm tabular-nums">
                <dt className="text-ink-muted">Total</dt><dd>{money(d.total_amount)}</dd>
                <dt className="text-ink-muted">ICMS</dt><dd>{money(d.total_icms)}</dd>
                <dt className="text-ink-muted">IPI</dt><dd>{money(d.total_ipi)}</dd>
              </dl>
            </Card>
          </div>
        )}
        {d && d.validation_errors.length > 0 && (
          <Card title="Validações">
            <ul className="space-y-1 text-sm">
              {d.validation_errors.map((e, i) => <li key={i}><Badge value={e.severity === "error" ? "invalid" : "pending"} text={e.severity === "error" ? "Erro" : "Aviso"} /> {e.message}</li>)}
            </ul>
          </Card>
        )}
        <Card title="Itens">
          <Table head={["#", "Descrição", "NCM", "CFOP", "Valor", "CST ICMS", "ICMS", "IPI", "CST PIS"]} empty={!d?.items.length}>
            {d?.items.map((it) => (
              <tr key={it.id}>
                <td>{it.item_number}</td><td>{it.description}</td><td className="font-mono text-xs">{it.ncm}</td>
                <td>{it.cfop}</td><td className="tabular-nums">{money(it.total_value)}</td><td>{it.icms_cst ?? "—"}</td>
                <td className="tabular-nums">{money(it.icms_value)}</td><td className="tabular-nums">{money(it.ipi_value)}</td><td>{it.pis_cst ?? "—"}</td>
              </tr>
            ))}
          </Table>
        </Card>
        <Card title="Oportunidades e riscos identificados">
          <Table head={["Regra", "Tributo", "Estimativa", "Revisão", "Justificativa"]} empty={!found.data?.length}>
            {found.data?.map((a) => (
              <tr key={a.id}>
                <td className="text-xs">{a.rule_code} v{a.rule_version}</td>
                <td>{a.tax}</td>
                <td className="tabular-nums">{money(a.estimated_amount)}</td>
                <td><Badge value={a.review_status} /></td>
                <td className="text-xs">{a.justification}</td>
              </tr>
            ))}
          </Table>
        </Card>
      </div>
    </>
  );
}
