"""Modelos de entrada/saída da API (Pydantic)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.domain.documents import is_valid_cnpj, normalize_cnpj

Role = Literal["admin", "operator", "viewer"]
TaxRegime = Literal["simples_nacional", "mei", "lucro_presumido", "lucro_real", "outro"]
CheckType = Literal["cadastro_cnpj", "cnd_federal", "crf_fgts", "cndt", "cnd_estadual", "cnd_municipal", "sintegra", "outro"]
CheckResult = Literal["regular", "irregular", "pending", "not_found", "error"]
ReviewStatus = Literal["pending_review", "approved", "rejected", "needs_info"]
UF = Field(default=None, pattern=r"^[A-Z]{2}$")


def _cnpj(value: str | None, required: bool = True) -> str | None:
    if value is None and not required:
        return None
    cnpj = normalize_cnpj(value)
    if not is_valid_cnpj(cnpj):
        raise ValueError("CNPJ inválido")
    return cnpj


class Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --------------------------------------------------------------- organizações

class OrganizationIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    cnpj: str | None = None

    @field_validator("cnpj")
    @classmethod
    def _v(cls, v: str | None) -> str | None:
        return _cnpj(v, required=False)


class OrganizationOut(Out):
    id: UUID
    name: str
    cnpj: str | None
    role: Role | None = None
    created_at: datetime


class MemberIn(BaseModel):
    email: EmailStr
    role: Role = "viewer"


class MemberUpdate(BaseModel):
    role: Role


class MemberOut(Out):
    user_id: UUID
    email: str
    full_name: str | None
    role: Role
    created_at: datetime


class CompanyIn(BaseModel):
    legal_name: str = Field(min_length=2, max_length=300)
    trade_name: str | None = None
    cnpj: str
    state_registration: str | None = None
    uf: str | None = UF
    tax_regime: TaxRegime = "outro"
    is_industrial: bool = False

    @field_validator("cnpj")
    @classmethod
    def _v(cls, v: str) -> str:
        return _cnpj(v)


class CompanyUpdate(BaseModel):
    legal_name: str | None = Field(default=None, min_length=2, max_length=300)
    trade_name: str | None = None
    state_registration: str | None = None
    uf: str | None = UF
    tax_regime: TaxRegime | None = None
    is_industrial: bool | None = None
    active: bool | None = None


class CompanyOut(Out):
    id: UUID
    organization_id: UUID
    legal_name: str
    trade_name: str | None
    cnpj: str
    state_registration: str | None
    uf: str | None
    tax_regime: TaxRegime
    is_industrial: bool
    active: bool
    created_at: datetime


class CompanyMemberIn(BaseModel):
    user_id: UUID


# --------------------------------------------------------------- fornecedores

class SupplierIn(BaseModel):
    cnpj: str
    legal_name: str = Field(min_length=2, max_length=300)
    trade_name: str | None = None
    uf: str | None = UF
    tax_regime: TaxRegime | None = None
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=40)
    company_ids: list[UUID] = Field(default_factory=list)

    @field_validator("cnpj")
    @classmethod
    def _v(cls, v: str) -> str:
        return _cnpj(v)


class SupplierUpdate(BaseModel):
    legal_name: str | None = Field(default=None, min_length=2, max_length=300)
    trade_name: str | None = None
    uf: str | None = UF
    tax_regime: TaxRegime | None = None
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=40)


class SupplierOut(Out):
    id: UUID
    cnpj: str
    legal_name: str
    trade_name: str | None
    uf: str | None
    tax_regime: TaxRegime | None
    email: str | None
    phone: str | None
    compliance_status: str
    compliance_updated_at: datetime | None
    created_at: datetime


class ComplianceCheckIn(BaseModel):
    check_type: CheckType
    result: CheckResult
    source: str = Field(min_length=2, max_length=300, description="Fonte consultada (ex.: site RFB/PGFN)")
    source_reference: str | None = Field(default=None, max_length=300, description="Código de controle/protocolo")
    issued_at: date | None = None
    valid_until: date | None = None
    checked_at: datetime | None = None
    evidence_document_id: UUID | None = None
    notes: str | None = Field(default=None, max_length=2000)


class ComplianceCheckOut(Out):
    id: UUID
    supplier_id: UUID
    check_type: str
    result: str
    source: str
    source_reference: str | None
    issued_at: date | None
    valid_until: date | None
    checked_at: datetime
    checked_by: UUID | None
    evidence_document_id: UUID | None
    notes: str | None


class EvidenceOut(Out):
    id: UUID
    supplier_id: UUID | None
    company_id: UUID | None
    kind: str
    file_name: str
    content_type: str
    size_bytes: int
    sha256: str
    created_at: datetime


# --------------------------------------------------------------- fiscal

class FiscalDocumentOut(Out):
    id: UUID
    company_id: UUID
    supplier_id: UUID | None
    access_key: str
    number: int | None
    series: int | None
    issue_date: datetime | None
    direction: str
    issuer_cnpj: str | None
    issuer_name: str | None
    recipient_cnpj: str | None
    recipient_name: str | None
    total_amount: Decimal
    total_icms: Decimal
    total_ipi: Decimal
    total_pis: Decimal
    total_cofins: Decimal
    status: str
    validation_errors: list[dict[str, Any]]
    analyzed_at: datetime | None
    created_at: datetime


class FiscalItemOut(Out):
    id: UUID
    item_number: int
    product_code: str | None
    description: str | None
    ncm: str | None
    cfop: str | None
    quantity: Decimal
    total_value: Decimal
    icms_cst: str | None
    icms_value: Decimal | None
    ipi_value: Decimal | None
    pis_cst: str | None
    pis_value: Decimal | None
    cofins_cst: str | None
    cofins_value: Decimal | None


class FiscalDocumentDetail(FiscalDocumentOut):
    items: list[FiscalItemOut]


class JobOut(Out):
    id: UUID
    company_id: UUID | None
    kind: str
    status: str
    result: dict[str, Any] | None
    error: str | None
    attempts: int
    max_attempts: int
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


# --------------------------------------------------------------- regras

class TaxRuleOut(Out):
    id: UUID
    organization_id: UUID | None
    code: str
    version: int
    name: str
    description: str | None
    tax: str
    legal_basis: str | None
    scope: str
    conditions: dict[str, Any]
    estimate: dict[str, Any] | None
    justification_template: str
    valid_from: date
    valid_to: date | None
    status: str
    content_hash: str
    supersedes_id: UUID | None
    validated_by_specialist: str | None
    published_at: datetime | None
    created_at: datetime


class PublishIn(BaseModel):
    validated_by_specialist: str = Field(
        min_length=3, max_length=200,
        description="Nome e registro profissional do especialista que validou a regra",
    )


class RetireIn(BaseModel):
    valid_to: date | None = None


class RuleTestIn(BaseModel):
    facts: dict[str, dict[str, Any]]


# --------------------------------------------------------------- avaliações

class AssessmentOut(Out):
    id: UUID
    company_id: UUID
    document_id: UUID
    item_id: UUID | None
    rule_id: UUID
    rule_code: str
    rule_version: int
    tax: str
    estimated_amount: Decimal | None
    inputs: dict[str, Any]
    criteria: dict[str, Any]
    justification: str
    evidence: list[dict[str, Any]]
    review_status: ReviewStatus
    reviewed_by: UUID | None
    reviewed_at: datetime | None
    review_notes: str | None
    created_at: datetime
    access_key: str | None = None
    issuer_name: str | None = None


class ReviewIn(BaseModel):
    review_status: Literal["approved", "rejected", "needs_info"]
    review_notes: str | None = Field(default=None, max_length=4000)


# --------------------------------------------------------------- operação

class AlertOut(Out):
    id: UUID
    company_id: UUID | None
    supplier_id: UUID | None
    kind: str
    severity: str
    status: str
    title: str
    message: str | None
    due_date: date | None
    created_at: datetime
    resolved_at: datetime | None


class AlertUpdate(BaseModel):
    status: Literal["acknowledged", "resolved"]


class AuditEventOut(Out):
    id: int
    actor_id: UUID | None
    action: str
    entity_type: str
    entity_id: UUID | None
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    metadata: dict[str, Any]
    created_at: datetime


class Page(BaseModel):
    items: list[Any]
    total: int
    limit: int
    offset: int
