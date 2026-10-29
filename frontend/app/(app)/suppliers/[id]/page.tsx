"use client";

import { useParams } from "next/navigation";
import { useState, type FormEvent } from "react";
import { useApp, useLoad } from "@/components/AppContext";
import { Badge, Button, Card, ErrorBox, Field, Input, PageHeader, Select, Table } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { cnpj, dateBR, dateTimeBR, label } from "@/lib/format";
import type { ComplianceCheck, Supplier } from "@/lib/types";

interface Detail { supplier: Supplier; companies: { id: string; legal_name: string; cnpj: string }[]; latest_checks: ComplianceCheck[] }
interface Evidence { id: string; file_name: string }

const CHECK_TYPES = ["cadastro_cnpj", "cnd_federal", "crf_fgts", "cndt", "cnd_estadual", "cnd_municipal", "sintegra", "outro"];
const RESULTS = [["regular", "Regular"], ["irregular", "Irregular"], ["pending", "Pendente"], ["not_found", "Não localizado"], ["error", "Erro na consulta"]];
const EMPTY = { check_type: "cnd_federal", result: "regular", source: "", source_reference: "", issued_at: "", valid_until: "", notes: "" };

export default function SupplierDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { base, canWrite } = useApp();
  const detail = useLoad(() => api.get<Detail>(`${base}/suppliers/${id}`), [base, id]);
  const history = useLoad(() => api.get<ComplianceCheck[]>(`${base}/suppliers/${id}/checks`), [base, id]);
  const [form, setForm] = useState(EMPTY);
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      let evidence_document_id: string | null = null;
      if (file) {
        const fd = new FormData();
        fd.append("file", file);
        fd.append("kind", form.check_type);
        evidence_document_id = (await api.upload<Evidence>(`${base}/suppliers/${id}/evidence`, fd)).id;
      }
      await api.post(`${base}/suppliers/${id}/checks`, {
        ...form,
        source_reference: form.source_reference || null,
        issued_at: form.issued_at || null,
        valid_until: form.valid_until || null,
        notes: form.notes || null,
        evidence_document_id,
      });
      setForm(EMPTY);
      setFile(null);
      detail.reload();
      history.reload();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  const s = detail.data?.supplier;
  return (
    <>
      <PageHeader title={s?.legal_name ?? "Fornecedor"} subtitle={s ? `CNPJ ${cnpj(s.cnpj)}${s.uf ? ` · ${s.uf}` : ""}` : undefined}
        actions={s && <Badge value={s.compliance_status} />} />
      <div className="space-y-4">
        <ErrorBox error={error ?? detail.error} />
        <div className="grid gap-4 lg:grid-cols-2">
          <Card title="Situação atual por verificação">
            <Table head={["Verificação", "Resultado", "Válida até", "Fonte"]} empty={!detail.data?.latest_checks.length}>
              {detail.data?.latest_checks.map((c) => (
                <tr key={c.id}>
                  <td>{label(c.check_type)}</td>
                  <td><Badge value={c.valid_until && c.valid_until < new Date().toISOString().slice(0, 10) ? "expired" : c.result} /></td>
                  <td>{dateBR(c.valid_until)}</td>
                  <td className="text-xs">{c.source}</td>
                </tr>
              ))}
            </Table>
          </Card>
          <Card title="Empresas vinculadas">
            <ul className="space-y-1 text-sm">
              {detail.data?.companies.map((c) => <li key={c.id}>{c.legal_name} <span className="font-mono text-xs text-ink-muted">{cnpj(c.cnpj)}</span></li>)}
              {detail.data?.companies.length === 0 && <li className="text-ink-muted">Nenhum vínculo.</li>}
            </ul>
          </Card>
        </div>

        {canWrite && (
          <Card title="Registrar verificação">
            <form onSubmit={submit} className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <Field label="Tipo">
                <Select value={form.check_type} onChange={(e) => setForm({ ...form, check_type: e.target.value })}>
                  {CHECK_TYPES.map((t) => <option key={t} value={t}>{label(t)}</option>)}
                </Select>
              </Field>
              <Field label="Resultado">
                <Select value={form.result} onChange={(e) => setForm({ ...form, result: e.target.value })}>
                  {RESULTS.map(([v, t]) => <option key={v} value={v}>{t}</option>)}
                </Select>
              </Field>
              <Field label="Fonte consultada"><Input required minLength={2} placeholder="Ex.: Portal RFB/PGFN" value={form.source} onChange={(e) => setForm({ ...form, source: e.target.value })} /></Field>
              <Field label="Código de controle"><Input value={form.source_reference} onChange={(e) => setForm({ ...form, source_reference: e.target.value })} /></Field>
              <Field label="Emitida em"><Input type="date" value={form.issued_at} onChange={(e) => setForm({ ...form, issued_at: e.target.value })} /></Field>
              <Field label="Válida até"><Input type="date" value={form.valid_until} onChange={(e) => setForm({ ...form, valid_until: e.target.value })} /></Field>
              <Field label="Evidência (PDF/imagem)"><Input type="file" accept="application/pdf,image/png,image/jpeg" onChange={(e) => setFile(e.target.files?.[0] ?? null)} /></Field>
              <Field label="Observações"><Input value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} /></Field>
              <div className="sm:col-span-2 lg:col-span-4 flex items-center gap-3">
                <Button type="submit">Registrar</Button>
                <span className="text-xs text-ink-muted">Sem data de validade, aplica-se o prazo usual da certidão.</span>
              </div>
            </form>
          </Card>
        )}

        <Card title="Histórico de verificações">
          <Table head={["Data", "Verificação", "Resultado", "Válida até", "Fonte", "Código", "Evidência"]} empty={!history.data?.length}>
            {history.data?.map((c) => (
              <tr key={c.id}>
                <td className="whitespace-nowrap">{dateTimeBR(c.checked_at)}</td>
                <td>{label(c.check_type)}</td>
                <td><Badge value={c.result} /></td>
                <td>{dateBR(c.valid_until)}</td>
                <td className="text-xs">{c.source}</td>
                <td className="font-mono text-xs">{c.source_reference ?? "—"}</td>
                <td>
                  {c.evidence_document_id ? (
                    <button className="text-sm text-brand" onClick={() => api.download(`${base}/evidence/${c.evidence_document_id}/download`, "evidencia")}>
                      Baixar
                    </button>
                  ) : "—"}
                </td>
              </tr>
            ))}
          </Table>
        </Card>
      </div>
    </>
  );
}
