"use client";

import Link from "next/link";
import { useState } from "react";
import { useApp, useLoad } from "@/components/AppContext";
import { Badge, Button, Card, ErrorBox, PageHeader, Select, Table } from "@/components/ui";
import { api } from "@/lib/api";
import { dateBR, dateTimeBR, label } from "@/lib/format";
import type { Alert } from "@/lib/types";

export default function AlertsPage() {
  const { base, canWrite } = useApp();
  const [status, setStatus] = useState("open");
  const list = useLoad(() => api.get<Alert[]>(`${base}/alerts`, { status }), [base, status]);

  async function update(id: string, next: "acknowledged" | "resolved") {
    await api.patch(`${base}/alerts/${id}`, { status: next });
    list.reload();
  }

  return (
    <>
      <PageHeader title="Alertas" subtitle="Vencimentos, irregularidades e pendências de compliance" />
      <ErrorBox error={list.error} />
      <Card title="Alertas" actions={
        <Select className="w-40" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="open">Abertos</option><option value="acknowledged">Cientes</option>
          <option value="resolved">Resolvidos</option><option value="all">Todos</option>
        </Select>
      }>
        <Table head={["Severidade", "Alerta", "Vencimento", "Criado em", ""]} empty={!list.loading && !list.data?.length}>
          {list.data?.map((a) => (
            <tr key={a.id}>
              <td><Badge value={a.severity} /></td>
              <td>
                {a.supplier_id ? <Link className="text-brand" href={`/suppliers/${a.supplier_id}`}>{a.title}</Link> : a.title}
                {a.message && <p className="text-xs text-ink-muted">{a.message}</p>}
              </td>
              <td>{dateBR(a.due_date)}</td>
              <td className="whitespace-nowrap">{dateTimeBR(a.created_at)}</td>
              <td className="whitespace-nowrap">
                {canWrite && a.status === "open" && <Button variant="ghost" onClick={() => update(a.id, "acknowledged")}>Ciente</Button>}
                {canWrite && a.status !== "resolved" && <Button variant="ghost" onClick={() => update(a.id, "resolved")}>Resolver</Button>}
                {a.status === "resolved" && <span className="text-xs text-ink-muted">{label("regular")}</span>}
              </td>
            </tr>
          ))}
        </Table>
      </Card>
    </>
  );
}
