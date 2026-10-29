"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";
import { useApp } from "@/components/AppContext";
import { Button, ErrorBox, Field, Input } from "@/components/ui";
import { supabase } from "@/lib/supabase";

export default function LoginPage() {
  const { session } = useApp();
  const router = useRouter();
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (session) router.replace("/dashboard");
  }, [session, router]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setInfo(null);
    const auth = supabase().auth;
    const { error: err } =
      mode === "login"
        ? await auth.signInWithPassword({ email, password })
        : await auth.signUp({ email, password });
    setBusy(false);
    if (err) setError(err.message);
    else if (mode === "signup") setInfo("Conta criada. Verifique seu e-mail para confirmar o cadastro.");
  }

  return (
    <main className="grid min-h-screen place-items-center p-4">
      <form onSubmit={submit} className="w-full max-w-sm space-y-4 rounded-lg border border-line bg-surface p-6">
        <div>
          <h1 className="text-lg font-semibold">FiscalGuard</h1>
          <p className="text-sm text-ink-muted">{mode === "login" ? "Acesse sua conta" : "Crie sua conta"}</p>
        </div>
        <Field label="E-mail">
          <Input type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </Field>
        <Field label="Senha">
          <Input type="password" autoComplete={mode === "login" ? "current-password" : "new-password"} required minLength={8}
            value={password} onChange={(e) => setPassword(e.target.value)} />
        </Field>
        <ErrorBox error={error} />
        {info && <p className="text-sm text-ok">{info}</p>}
        <Button type="submit" disabled={busy} className="w-full">{mode === "login" ? "Entrar" : "Cadastrar"}</Button>
        <button type="button" className="w-full text-center text-sm text-brand"
          onClick={() => setMode(mode === "login" ? "signup" : "login")}>
          {mode === "login" ? "Não tem conta? Cadastre-se" : "Já tenho conta"}
        </button>
      </form>
    </main>
  );
}
