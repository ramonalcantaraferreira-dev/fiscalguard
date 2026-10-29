"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { useApp } from "@/components/AppContext";
import { Button, Card, ErrorBox, Field, Input } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import type { Organization } from "@/lib/types";

export default function OnboardingPage() {
  const { reload, setOrgId } = useApp();
  const router = useRouter();
  const [name, setName] = useState("");
  const [cnpj, setCnpj] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    try {
      const org = await api.post<Organization>("/api/v1/organizations", { name, cnpj: cnpj || null });
      setOrgId(org.id);
      await reload();
      router.replace("/companies");
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <Card title="Cadastre seu escritório contábil">
      <form onSubmit={submit} className="space-y-4">
        <p className="text-sm text-ink-muted">
          Você será o administrador. Depois, convide sua equipe e cadastre as empresas atendidas.
          Se você foi convidado para um escritório existente, peça ao administrador para adicioná-lo.
        </p>
        <Field label="Nome do escritório"><Input required minLength={2} value={name} onChange={(e) => setName(e.target.value)} /></Field>
        <Field label="CNPJ (opcional)"><Input value={cnpj} onChange={(e) => setCnpj(e.target.value)} /></Field>
        <ErrorBox error={error} />
        <Button type="submit">Criar escritório</Button>
      </form>
    </Card>
  );
}
