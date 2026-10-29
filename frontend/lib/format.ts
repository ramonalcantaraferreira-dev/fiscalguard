const brl = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });

export const money = (v: string | number | null | undefined) =>
  v === null || v === undefined || v === "" ? "—" : brl.format(Number(v));

export const dateBR = (v: string | null | undefined) =>
  v ? new Date(v.length === 10 ? `${v}T12:00:00` : v).toLocaleDateString("pt-BR") : "—";

export const dateTimeBR = (v: string | null | undefined) => (v ? new Date(v).toLocaleString("pt-BR") : "—");

export function cnpj(v: string | null | undefined): string {
  if (!v || v.length !== 14) return v ?? "—";
  return `${v.slice(0, 2)}.${v.slice(2, 5)}.${v.slice(5, 8)}/${v.slice(8, 12)}-${v.slice(12)}`;
}

export const LABELS: Record<string, string> = {
  unknown: "Não verificado",
  regular: "Regular",
  pending: "Pendente",
  irregular: "Irregular",
  expired: "Vencido",
  validated: "Validado",
  invalid: "Com erros",
  received: "Recebido",
  pending_review: "Aguardando revisão",
  approved: "Aprovado",
  rejected: "Rejeitado",
  needs_info: "Requer informação",
  draft: "Rascunho",
  published: "Publicada",
  retired: "Aposentada",
  queued: "Na fila",
  running: "Executando",
  succeeded: "Concluída",
  failed: "Falhou",
  dead: "Falha definitiva",
  inbound: "Entrada",
  outbound: "Saída",
  simples_nacional: "Simples Nacional",
  mei: "MEI",
  lucro_presumido: "Lucro Presumido",
  lucro_real: "Lucro Real",
  outro: "Outro",
  admin: "Administrador",
  operator: "Operador",
  viewer: "Visualizador",
  cadastro_cnpj: "Situação cadastral CNPJ",
  cnd_federal: "CND Federal",
  crf_fgts: "CRF FGTS",
  cndt: "CNDT",
  cnd_estadual: "CND Estadual",
  cnd_municipal: "CND Municipal",
  sintegra: "Sintegra",
  imported: "Importado",
  imported_with_errors: "Importado com erros",
  duplicate: "Duplicado",
  info: "Informativo",
  warning: "Atenção",
  critical: "Crítico",
  nfe_import: "Importação de NF-e",
  reanalyze_company: "Reprocessamento de análises",
  compliance_scan: "Varredura de compliance",
};

export const label = (v: string | null | undefined) => (v ? LABELS[v] ?? v : "—");
