"use client";

import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, SelectHTMLAttributes } from "react";
import { label } from "@/lib/format";

export function Button({ variant = "primary", className = "", ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "danger" | "ghost" }) {
  const styles = {
    primary: "bg-brand text-white hover:bg-brand-dark",
    secondary: "border border-line bg-surface text-ink hover:bg-subtle",
    danger: "bg-danger text-white hover:opacity-90",
    ghost: "text-ink-muted hover:bg-subtle",
  }[variant];
  return (
    <button
      className={`inline-flex min-h-9 items-center justify-center gap-2 rounded-md px-3 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-50 ${styles} ${className}`}
      {...props}
    />
  );
}

export function Input(props: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={`h-9 rounded-md border border-line bg-surface px-3 text-sm text-ink ${props.className ?? "w-full"}`} />;
}

export function Select(props: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select {...props} className={`h-9 rounded-md border border-line bg-surface px-2 text-sm text-ink ${props.className ?? "w-full"}`} />;
}

export function Field({ label: text, children }: { label: string; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1 text-sm">
      <span className="font-medium text-ink-muted">{text}</span>
      {children}
    </label>
  );
}

export function Card({ title, actions, children, className = "" }: { title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`rounded-lg border border-line bg-surface ${className}`}>
      {(title || actions) && (
        <header className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-4 py-3">
          <h2 className="text-sm font-semibold text-ink">{title}</h2>
          <div className="flex flex-wrap gap-2">{actions}</div>
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}

const TONES: Record<string, string> = {
  regular: "ok", validated: "ok", approved: "ok", succeeded: "ok", published: "ok", imported: "ok",
  pending: "warn", pending_review: "warn", needs_info: "warn", queued: "warn", running: "warn", warning: "warn", draft: "warn", expiring: "warn",
  irregular: "bad", expired: "bad", invalid: "bad", rejected: "bad", failed: "bad", dead: "bad", critical: "bad", imported_with_errors: "bad",
};

export function Badge({ value, text }: { value: string; text?: string }) {
  const tone = TONES[value] ?? "neutral";
  const cls = {
    ok: "bg-ok-soft text-ok",
    warn: "bg-warn-soft text-warn",
    bad: "bg-danger-soft text-danger",
    neutral: "bg-subtle text-ink-muted",
  }[tone];
  return <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap ${cls}`}>{text ?? label(value)}</span>;
}

export function Table({ head, children, empty }: { head: ReactNode[]; children: ReactNode; empty?: boolean }) {
  return (
    <div className="-mx-4 overflow-x-auto">
      <table className="w-full min-w-[480px] text-left text-sm">
        <thead className="text-xs uppercase tracking-wide text-ink-muted">
          <tr>{head.map((h, i) => <th key={i} className="border-b border-line px-4 py-2 font-medium">{h}</th>)}</tr>
        </thead>
        <tbody className="[&>tr]:border-b [&>tr]:border-line [&>tr:last-child]:border-0 [&_td]:px-4 [&_td]:py-2 [&_td]:align-top">
          {children}
        </tbody>
      </table>
      {empty && <p className="px-4 py-8 text-center text-sm text-ink-muted">Nenhum registro encontrado.</p>}
    </div>
  );
}

export function ErrorBox({ error }: { error: string | null }) {
  if (!error) return null;
  return <div role="alert" className="rounded-md border border-danger/40 bg-danger-soft px-3 py-2 text-sm text-danger">{error}</div>;
}

export function Notice({ children }: { children: ReactNode }) {
  return <div className="rounded-md border border-warn/40 bg-warn-soft px-3 py-2 text-sm text-warn">{children}</div>;
}

export function Stat({ label: text, value, hint }: { label: string; value: ReactNode; hint?: ReactNode }) {
  return (
    <div className="rounded-lg border border-line bg-surface p-4">
      <p className="text-xs font-medium uppercase tracking-wide text-ink-muted">{text}</p>
      <p className="mt-1 text-2xl font-semibold text-ink tabular-nums">{value}</p>
      {hint && <p className="mt-1 text-xs text-ink-muted">{hint}</p>}
    </div>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold text-ink">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-ink-muted">{subtitle}</p>}
      </div>
      <div className="flex flex-wrap gap-2">{actions}</div>
    </div>
  );
}
