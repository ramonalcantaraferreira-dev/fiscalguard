export type Role = "admin" | "operator" | "viewer";

export interface Organization {
  id: string;
  name: string;
  cnpj: string | null;
  role: Role;
}

export interface Company {
  id: string;
  legal_name: string;
  trade_name: string | null;
  cnpj: string;
  uf: string | null;
  tax_regime: string;
  is_industrial: boolean;
  active: boolean;
}

export interface Supplier {
  id: string;
  cnpj: string;
  legal_name: string;
  trade_name: string | null;
  uf: string | null;
  tax_regime: string | null;
  email: string | null;
  compliance_status: "unknown" | "regular" | "pending" | "irregular" | "expired";
  compliance_updated_at: string | null;
}

export interface ComplianceCheck {
  id: string;
  check_type: string;
  result: string;
  source: string;
  source_reference: string | null;
  issued_at: string | null;
  valid_until: string | null;
  checked_at: string;
  evidence_document_id: string | null;
  notes: string | null;
}

export interface FiscalDocument {
  id: string;
  company_id: string;
  access_key: string;
  number: number | null;
  series: number | null;
  issue_date: string | null;
  direction: string;
  issuer_cnpj: string | null;
  issuer_name: string | null;
  recipient_name: string | null;
  total_amount: string;
  total_icms: string;
  total_ipi: string;
  status: "received" | "validated" | "invalid";
  validation_errors: { code: string; message: string; severity: string }[];
  analyzed_at: string | null;
}

export interface FiscalItem {
  id: string;
  item_number: number;
  description: string | null;
  ncm: string | null;
  cfop: string | null;
  total_value: string;
  icms_cst: string | null;
  icms_value: string | null;
  ipi_value: string | null;
  pis_cst: string | null;
  pis_value: string | null;
  cofins_value: string | null;
}

export interface CriteriaNode {
  group?: "all" | "any" | "not";
  children?: CriteriaNode[];
  fact?: string;
  op?: string;
  expected?: unknown;
  actual?: unknown;
  result: boolean;
}

export interface Assessment {
  id: string;
  company_id: string;
  document_id: string;
  item_id: string | null;
  rule_code: string;
  rule_version: number;
  tax: string;
  estimated_amount: string | null;
  inputs: Record<string, unknown>;
  criteria: CriteriaNode;
  justification: string;
  evidence: Record<string, unknown>[];
  review_status: "pending_review" | "approved" | "rejected" | "needs_info";
  review_notes: string | null;
  reviewed_at: string | null;
  access_key: string | null;
  issuer_name: string | null;
}

export interface TaxRule {
  id: string;
  organization_id: string | null;
  code: string;
  version: number;
  name: string;
  tax: string;
  legal_basis: string | null;
  scope: string;
  conditions: unknown;
  valid_from: string;
  valid_to: string | null;
  status: "draft" | "published" | "retired";
  content_hash: string;
  validated_by_specialist: string | null;
}

export interface Alert {
  id: string;
  supplier_id: string | null;
  kind: string;
  severity: "info" | "warning" | "critical";
  status: string;
  title: string;
  message: string | null;
  due_date: string | null;
  created_at: string;
}

export interface Job {
  id: string;
  kind: string;
  status: "queued" | "running" | "succeeded" | "failed" | "dead";
  result: { summary?: Record<string, number>; files?: ImportFileResult[] } & Record<string, unknown> | null;
  error: string | null;
  attempts: number;
  created_at: string;
  finished_at: string | null;
}

export interface ImportFileResult {
  file: string;
  status: string;
  access_key?: string;
  document_id?: string;
  errors?: { code: string; message: string }[];
  issues?: { code: string; message: string; severity: string }[];
}
