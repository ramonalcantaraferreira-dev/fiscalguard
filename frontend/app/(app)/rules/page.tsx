"use client";

import { useState } from "react";
import { useApp, useLoad } from "@/components/AppContext";
import { Badge, Button, Card, ErrorBox, Field, Input, Notice, PageHeader, Table } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { dateBR } from "@/lib/format";
import type { TaxRule } from "@/lib/types";

export default function RulesPage() {
  const { base, isAdmin } = useApp();
  const list = useLoad(() => api.get<TaxRule[]>(`${base}/tax-rules`), [base]);
  const [selected, setSelected] = useState<TaxRule | null>(null);
  const [draft, setDraft] = useState("");
  const [specialist, setSpecialist] = useState("");
  const [error, setError] = useState<string | null>(null);

  function select(rule: TaxRule) {
    setSelected(rule);
    setDraft(JSON.stringify(rule.conditions, null, 2));
    setError(null);
  }

  async function run(fn: () => Promise<unknown>) {
    setError(null);
    try {
      await fn();
      list.reload();
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  const newVersion = () => run(async () => {
    const created = await api.post<TaxRule>(`${base}/tax-rules/${selected!.id}/versions`, { conditions: JSON.parse(draft) });
    select(created);
  });
  const saveDraft = () => run(async () => select(await api.patch<TaxRule>(`${base}/tax-rules/${selected!.id}`, { conditions: JSON.parse(draft) })));
  const publish = () => run(async () => select(await api.post<TaxRule>(`${base}/tax-rules/${selected!.id}/publish`, { validated_by_specialist: specialist })));
  const retire = () => run(async () => select(await api.post<TaxRule>(`${base}/tax-rules/${selected!.id}/retire`, {})));

  return (
    <>
      <PageHeader title="Regras tributárias" subtitle="Regras determinísticas, versionadas e imutáveis após publicação" />
      <div className="space-y-4">
        <Notice>
          Regras marcadas como <strong>[EXEMPLO]</strong> demonstram o funcionamento do motor e não foram validadas por especialista.
          Publique versões próprias somente após validação técnica, registrando o responsável.
        </Notice>
        <ErrorBox error={error ?? list.error} />
        <div className="grid gap-4 xl:grid-cols-[1fr_1fr]">
          <Card title="Regras">
            <Table head={["Código", "Versão", "Tributo", "Vigência", "Status", "Origem"]} empty={!list.data?.length}>
              {list.data?.map((r) => (
                <tr key={r.id} className={`cursor-pointer ${selected?.id === r.id ? "bg-brand-soft" : "hover:bg-subtle"}`} onClick={() => select(r)}>
                  <td><p className="text-xs font-medium">{r.code}</p><p className="text-xs text-ink-muted">{r.name}</p></td>
                  <td>v{r.version}</td>
                  <td>{r.tax}</td>
                  <td className="whitespace-nowrap text-xs">{dateBR(r.valid_from)} — {r.valid_to ? dateBR(r.valid_to) : "atual"}</td>
                  <td><Badge value={r.status} /></td>
                  <td className="text-xs">{r.organization_id ? "Escritório" : "Global"}</td>
                </tr>
              ))}
            </Table>
          </Card>
          {selected && (
            <Card title={`${selected.code} v${selected.version}`}>
              <div className="space-y-3 text-sm">
                <p><span className="text-ink-muted">Base legal:</span> {selected.legal_basis ?? "—"}</p>
                <p><span className="text-ink-muted">Validada por:</span> {selected.validated_by_specialist ?? "não validada"}</p>
                <p className="break-all font-mono text-xs text-ink-muted">hash {selected.content_hash}</p>
                <Field label="Condições (JSON)">
                  <textarea className="min-h-72 w-full rounded-md border border-line bg-surface p-2 font-mono text-xs"
                    readOnly={!isAdmin} value={draft} onChange={(e) => setDraft(e.target.value)} />
                </Field>
                {isAdmin && (
                  <div className="flex flex-wrap items-end gap-2">
                    {selected.status === "draft" && selected.organization_id ? (
                      <>
                        <Button variant="secondary" onClick={saveDraft}>Salvar rascunho</Button>
                        <Field label="Especialista responsável (nome e registro)">
                          <Input value={specialist} onChange={(e) => setSpecialist(e.target.value)} placeholder="Ex.: Nome — CRC UF-000000" />
                        </Field>
                        <Button disabled={specialist.length < 3} onClick={publish}>Publicar</Button>
                      </>
                    ) : (
                      <Button onClick={newVersion}>Criar nova versão com estas condições</Button>
                    )}
                    {selected.status === "published" && selected.organization_id && <Button variant="danger" onClick={retire}>Aposentar</Button>}
                  </div>
                )}
              </div>
            </Card>
          )}
        </div>
      </div>
    </>
  );
}
