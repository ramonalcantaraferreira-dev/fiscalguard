"use client";

import { useState, type FormEvent } from "react";
import { useApp, useLoad } from "@/components/AppContext";
import { Badge, Button, Card, ErrorBox, Field, Input, PageHeader, Select, Table } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { cnpj, label } from "@/lib/format";
import type { Company } from "@/lib/types";

interface Member { user_id: string; email: string; role: string }

const EMPTY = { legal_name: "", trade_name: "", cnpj: "", uf: "", tax_regime: "lucro_real", is_industrial: false };

export default function CompaniesPage() {
  const { base, isAdmin, reload: reloadApp } = useApp();
  const companies = useLoad(() => api.get<Company[]>(`${base}/companies`, { include_inactive: true }), [base]);
  const members = useLoad(() => api.get<Member[]>(`${base}/members`), [base]);
  const [form, setForm] = useState(EMPTY);
  const [invite, setInvite] = useState({ email: "", role: "operator" });
  const [access, setAccess] = useState({ company: "", user: "" });
  const [error, setError] = useState<string | null>(null);

  async function act(fn: () => Promise<unknown>) {
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  const createCompany = (e: FormEvent) => {
    e.preventDefault();
    act(async () => {
      await api.post(`${base}/companies`, { ...form, uf: form.uf || null, trade_name: form.trade_name || null });
      setForm(EMPTY);
      companies.reload();
      reloadApp();
    });
  };

  return (
    <>
      <PageHeader title="Empresas e equipe" subtitle="Empresas atendidas pelo escritório e acesso dos usuários" />
      <div className="space-y-4">
        <ErrorBox error={error ?? companies.error} />
        <Card title="Empresas">
          <Table head={["Empresa", "CNPJ", "UF", "Regime", "Industrial", "Situação"]} empty={!companies.data?.length}>
            {companies.data?.map((c) => (
              <tr key={c.id}>
                <td><p className="font-medium">{c.legal_name}</p>{c.trade_name && <p className="text-xs text-ink-muted">{c.trade_name}</p>}</td>
                <td className="whitespace-nowrap font-mono text-xs">{cnpj(c.cnpj)}</td>
                <td>{c.uf ?? "—"}</td>
                <td>{label(c.tax_regime)}</td>
                <td>{c.is_industrial ? "Sim" : "Não"}</td>
                <td><Badge value={c.active ? "regular" : "unknown"} text={c.active ? "Ativa" : "Inativa"} /></td>
              </tr>
            ))}
          </Table>
        </Card>

        {isAdmin && (
          <Card title="Nova empresa">
            <form onSubmit={createCompany} className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              <Field label="Razão social"><Input required minLength={2} value={form.legal_name} onChange={(e) => setForm({ ...form, legal_name: e.target.value })} /></Field>
              <Field label="Nome fantasia"><Input value={form.trade_name} onChange={(e) => setForm({ ...form, trade_name: e.target.value })} /></Field>
              <Field label="CNPJ"><Input required value={form.cnpj} onChange={(e) => setForm({ ...form, cnpj: e.target.value })} /></Field>
              <Field label="UF"><Input maxLength={2} value={form.uf} onChange={(e) => setForm({ ...form, uf: e.target.value.toUpperCase() })} /></Field>
              <Field label="Regime tributário">
                <Select value={form.tax_regime} onChange={(e) => setForm({ ...form, tax_regime: e.target.value })}>
                  {["lucro_real", "lucro_presumido", "simples_nacional", "mei", "outro"].map((r) => <option key={r} value={r}>{label(r)}</option>)}
                </Select>
              </Field>
              <label className="flex items-center gap-2 self-end pb-2 text-sm">
                <input type="checkbox" checked={form.is_industrial} onChange={(e) => setForm({ ...form, is_industrial: e.target.checked })} />
                Estabelecimento industrial
              </label>
              <div className="sm:col-span-2 lg:col-span-3"><Button type="submit">Cadastrar empresa</Button></div>
            </form>
          </Card>
        )}

        <Card title="Equipe do escritório">
          <Table head={["E-mail", "Perfil"]} empty={!members.data?.length}>
            {members.data?.map((m) => (
              <tr key={m.user_id}>
                <td>{m.email}</td>
                <td>
                  {isAdmin ? (
                    <Select value={m.role} className="w-full max-w-44"
                      onChange={(e) => act(async () => { await api.patch(`${base}/members/${m.user_id}`, { role: e.target.value }); members.reload(); })}>
                      {["admin", "operator", "viewer"].map((r) => <option key={r} value={r}>{label(r)}</option>)}
                    </Select>
                  ) : label(m.role)}
                </td>
              </tr>
            ))}
          </Table>
          {isAdmin && (
            <div className="mt-4 grid gap-4 lg:grid-cols-2">
              <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => {
                e.preventDefault();
                act(async () => { await api.post(`${base}/members`, invite); setInvite({ ...invite, email: "" }); members.reload(); });
              }}>
                <Field label="Adicionar usuário (já cadastrado)"><Input type="email" required value={invite.email} onChange={(e) => setInvite({ ...invite, email: e.target.value })} /></Field>
                <Select className="w-40" value={invite.role} onChange={(e) => setInvite({ ...invite, role: e.target.value })}>
                  {["operator", "viewer", "admin"].map((r) => <option key={r} value={r}>{label(r)}</option>)}
                </Select>
                <Button type="submit">Adicionar</Button>
              </form>
              <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => {
                e.preventDefault();
                act(() => api.post(`${base}/companies/${access.company}/members`, { user_id: access.user }));
              }}>
                <Field label="Liberar empresa para usuário">
                  <Select required value={access.user} onChange={(e) => setAccess({ ...access, user: e.target.value })}>
                    <option value="">Usuário…</option>
                    {members.data?.filter((m) => m.role !== "admin").map((m) => <option key={m.user_id} value={m.user_id}>{m.email}</option>)}
                  </Select>
                </Field>
                <Select required className="w-48" value={access.company} onChange={(e) => setAccess({ ...access, company: e.target.value })}>
                  <option value="">Empresa…</option>
                  {companies.data?.map((c) => <option key={c.id} value={c.id}>{c.legal_name}</option>)}
                </Select>
                <Button type="submit">Liberar</Button>
              </form>
              <p className="text-xs text-ink-muted lg:col-span-2">
                Administradores acessam todas as empresas. Operadores e visualizadores acessam apenas as empresas liberadas.
              </p>
            </div>
          )}
        </Card>
      </div>
    </>
  );
}
