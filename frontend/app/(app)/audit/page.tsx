"use client";

import { useApp, useLoad } from "@/components/AppContext";
import { Card, ErrorBox, PageHeader, Table } from "@/components/ui";
import { api } from "@/lib/api";
import { dateTimeBR } from "@/lib/format";

interface AuditEvent {
  id: number;
  actor_id: string | null;
  action: string;
  entity_type: string;
  entity_id: string | null;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  metadata: Record<string, unknown>;
  created_at: string;
}

function changes(e: AuditEvent): string {
  if (e.action !== "update" || !e.before || !e.after) {
    return Object.keys(e.metadata).length ? JSON.stringify(e.metadata) : "";
  }
  return Object.keys(e.after)
    .filter((k) => k !== "updated_at" && JSON.stringify(e.before![k]) !== JSON.stringify(e.after![k]))
    .map((k) => `${k}: ${JSON.stringify(e.before![k])} → ${JSON.stringify(e.after![k])}`)
    .join("; ");
}

export default function AuditPage() {
  const { base } = useApp();
  const list = useLoad(() => api.get<AuditEvent[]>(`${base}/audit-events`, { limit: 200 }), [base]);
  return (
    <>
      <PageHeader title="Auditoria" subtitle="Trilha imutável de alterações e eventos relevantes" />
      <ErrorBox error={list.error} />
      <Card title="Eventos recentes">
        <Table head={["Data", "Ação", "Entidade", "Usuário", "Alterações"]} empty={!list.loading && !list.data?.length}>
          {list.data?.map((e) => (
            <tr key={e.id}>
              <td className="whitespace-nowrap">{dateTimeBR(e.created_at)}</td>
              <td>{e.action}</td>
              <td className="text-xs">{e.entity_type}</td>
              <td className="font-mono text-xs">{e.actor_id?.slice(0, 8) ?? "sistema"}</td>
              <td className="max-w-md break-words text-xs">{changes(e)}</td>
            </tr>
          ))}
        </Table>
      </Card>
    </>
  );
}
