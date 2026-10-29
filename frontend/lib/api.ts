import { supabase } from "./supabase";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details?: unknown,
  ) {
    super(message);
  }
}

type Query = Record<string, string | number | boolean | null | undefined>;

function buildUrl(path: string, query?: Query): string {
  const url = new URL(path, API_URL);
  for (const [k, v] of Object.entries(query ?? {})) {
    if (v !== undefined && v !== null && v !== "") url.searchParams.set(k, String(v));
  }
  return url.toString();
}

async function authHeader(): Promise<Record<string, string>> {
  const { data } = await supabase().auth.getSession();
  const token = data.session?.access_token;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function request<T>(method: string, path: string, opts: { query?: Query; json?: unknown; form?: FormData } = {}): Promise<T> {
  const headers: Record<string, string> = await authHeader();
  let body: BodyInit | undefined;
  if (opts.json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.json);
  } else if (opts.form) {
    body = opts.form;
  }
  const res = await fetch(buildUrl(path, opts.query), { method, headers, body });
  if (res.status === 204) return undefined as T;
  const isJson = res.headers.get("content-type")?.includes("application/json");
  if (!res.ok) {
    const payload = isJson ? await res.json() : null;
    const err = payload?.error ?? {};
    throw new ApiError(res.status, err.code ?? "http_error", err.message ?? res.statusText, err.details);
  }
  return (isJson ? res.json() : res.blob()) as Promise<T>;
}

export const api = {
  get: <T>(path: string, query?: Query) => request<T>("GET", path, { query }),
  post: <T>(path: string, json?: unknown, query?: Query) => request<T>("POST", path, { json: json ?? {}, query }),
  patch: <T>(path: string, json: unknown) => request<T>("PATCH", path, { json }),
  del: (path: string) => request<void>("DELETE", path),
  upload: <T>(path: string, form: FormData, query?: Query) => request<T>("POST", path, { form, query }),

  /** Baixa um arquivo autenticado (CSV, XML, evidência) sem expor URLs públicas. */
  async download(path: string, filename: string, query?: Query): Promise<void> {
    const blob = await request<Blob | { url: string }>("GET", path, { query });
    if (!(blob instanceof Blob)) {
      window.open(blob.url, "_blank", "noopener");
      return;
    }
    const href = URL.createObjectURL(blob);
    const a = Object.assign(document.createElement("a"), { href, download: filename });
    a.click();
    URL.revokeObjectURL(href);
  },
};

export function errorMessage(e: unknown): string {
  if (e instanceof ApiError) {
    if (Array.isArray(e.details)) {
      const first = e.details[0] as { msg?: string } | undefined;
      if (first?.msg) return `${e.message}: ${first.msg}`;
    }
    return typeof e.details === "string" ? `${e.message}: ${e.details}` : e.message;
  }
  return e instanceof Error ? e.message : "Erro inesperado";
}
