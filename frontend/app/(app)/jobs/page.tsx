"use client";

import { Fragment, useState } from "react";
import { useApp, useLoad } from "@/components/AppContext";
import { Badge, Button, Card, ErrorBox, PageHeader, Table } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { dateTimeBR, label } from "@/lib/format";
import type { Job } from "@/lib/types";

export default function JobsPage() {
  const { base, canWrite } = useApp();
  const list = useLoad(() => api.get<Job[]>(`${base}/jobs`), [base]);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function retry(id: string) {
    try {
      await api.post(`${base}/jobs/${id}/retry`);
      list.reload();
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  return (
    <>
      <PageHeader title="Importações e tarefas" subtitle="Histórico de processamentos, erros e reprocessamentos"
        actions={<Button variant="secondary" onClick={list.reload}>Atualizar</Button>} />
      <ErrorBox error={error ?? list.error} />
      <Card title="Tarefas">
        <Table head={["Criada em", "Tipo", "Status", "Resumo", "Tentativas", ""]} empty={!list.loading && !list.data?.length}>
          {list.data?.map((j) => (
            <Fragment key={j.id}>
              <tr>
                <td className="whitespace-nowrap">{dateTimeBR(j.created_at)}</td>
                <td>{label(j.kind)}</td>
                <td><Badge value={j.status} /></td>
                <td className="text-xs">{Object.entries(j.result?.summary ?? {}).map(([k, v]) => `${v} ${label(k).toLowerCase()}`).join(" · ") || "—"}</td>
                <td>{j.attempts}</td>
                <td className="whitespace-nowrap">
                  <Button variant="ghost" onClick={() => setExpanded(expanded === j.id ? null : j.id)}>Detalhes</Button>
                  {canWrite && ["failed", "dead"].includes(j.status) && <Button variant="secondary" onClick={() => retry(j.id)}>Reprocessar</Button>}
                </td>
              </tr>
              {expanded === j.id && (
                <tr>
                  <td colSpan={6}>
                    {j.error && <pre className="mb-2 max-h-40 overflow-auto rounded bg-danger-soft p-2 text-xs text-danger">{j.error}</pre>}
                    <ul className="space-y-1 text-xs">
                      {j.result?.files?.map((f, i) => (
                        <li key={i}><Badge value={f.status} /> {f.file} {f.access_key && <span className="font-mono text-ink-muted">{f.access_key}</span>}
                          {(f.errors ?? []).map((e) => ` — ${e.message}`)}</li>
                      ))}
                    </ul>
                  </td>
                </tr>
              )}
            </Fragment>
          ))}
        </Table>
      </Card>
    </>
  );
}
