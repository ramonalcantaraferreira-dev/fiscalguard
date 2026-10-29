from __future__ import annotations

import hashlib
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy import text

from app.config import Settings, get_settings
from app.db import fetch_all, fetch_one, fetch_value
from app.deps import OrgContext, get_org
from app.errors import Invalid, NotFound
from app.schemas import (
    ComplianceCheckIn, ComplianceCheckOut, EvidenceOut, SupplierIn, SupplierOut, SupplierUpdate,
)
from app.services.audit import log_event
from app.services.compliance import default_valid_until, scan_compliance
from app.services.export import csv_response
from app.services.storage import content_path, get_storage, safe_filename
from app.services.supplier_import import import_suppliers_csv

router = APIRouter(prefix="/api/v1/organizations/{org_id}", tags=["fornecedores e compliance"])

ALLOWED_EVIDENCE_TYPES = {"application/pdf", "image/png", "image/jpeg", "application/xml", "text/xml"}


def _supplier(ctx: OrgContext, supplier_id: UUID) -> dict:
    row = fetch_one(ctx.conn, "select * from suppliers where id = :id and organization_id = :org",
                    {"id": supplier_id, "org": ctx.org_id})
    if row is None:
        raise NotFound("Fornecedor")
    return row


async def _read_limited(upload: UploadFile, limit: int) -> bytes:
    content = await upload.read(limit + 1)
    if len(content) > limit:
        raise Invalid(f"Arquivo {upload.filename} excede {limit // (1024 * 1024)} MB")
    return content


# ------------------------------------------------------------------ cadastro

@router.get("/suppliers", response_model=list[SupplierOut])
def list_suppliers(
    ctx: OrgContext = Depends(get_org),
    company_id: UUID | None = None,
    status: str | None = Query(None, pattern="^(unknown|regular|pending|irregular|expired)$"),
    q: str | None = Query(None, max_length=100),
    limit: int = Query(100, le=500),
    offset: int = 0,
):
    return fetch_all(
        ctx.conn,
        """
        select s.* from suppliers s
         where s.organization_id = :org
           and (cast(:company as uuid) is null or exists (
                 select 1 from supplier_company_links l where l.supplier_id = s.id and l.company_id = cast(:company as uuid)))
           and (cast(:status as text) is null or s.compliance_status::text = :status)
           and (cast(:q as text) is null or s.legal_name ilike '%' || :q || '%' or s.cnpj like :q || '%')
         order by s.legal_name limit :limit offset :offset
        """,
        {"org": ctx.org_id, "company": company_id, "status": status, "q": q, "limit": limit, "offset": offset},
    )


@router.post("/suppliers", response_model=SupplierOut, status_code=201)
def create_supplier(body: SupplierIn, ctx: OrgContext = Depends(get_org)):
    ctx.require_write()
    data = body.model_dump(exclude={"company_ids"})
    supplier = fetch_one(
        ctx.conn,
        """insert into suppliers (organization_id, cnpj, legal_name, trade_name, uf, tax_regime, email, phone)
           values (:org, :cnpj, :legal_name, :trade_name, :uf, cast(:tax_regime as tax_regime), :email, :phone)
           returning *""",
        {"org": ctx.org_id, **data},
    )
    for company_id in body.company_ids:
        ctx.require_company(company_id, write=True)
        ctx.conn.execute(
            text("""insert into supplier_company_links (organization_id, supplier_id, company_id)
                    values (:org, :s, :c) on conflict do nothing"""),
            {"org": ctx.org_id, "s": supplier["id"], "c": company_id},
        )
    return supplier


@router.get("/suppliers/{supplier_id}")
def get_supplier(supplier_id: UUID, ctx: OrgContext = Depends(get_org)):
    supplier = _supplier(ctx, supplier_id)
    companies = fetch_all(
        ctx.conn,
        """select c.id, c.legal_name, c.cnpj from supplier_company_links l
             join client_companies c on c.id = l.company_id where l.supplier_id = :s order by c.legal_name""",
        {"s": supplier_id},
    )
    latest = fetch_all(
        ctx.conn,
        """select distinct on (check_type) * from compliance_checks where supplier_id = :s
            order by check_type, checked_at desc, created_at desc""",
        {"s": supplier_id},
    )
    return {
        "supplier": SupplierOut.model_validate(supplier),
        "companies": companies,
        "latest_checks": [ComplianceCheckOut.model_validate(c) for c in latest],
    }


@router.patch("/suppliers/{supplier_id}", response_model=SupplierOut)
def update_supplier(supplier_id: UUID, body: SupplierUpdate, ctx: OrgContext = Depends(get_org)):
    ctx.require_write()
    _supplier(ctx, supplier_id)
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        return _supplier(ctx, supplier_id)
    casts = {"tax_regime": "cast(:tax_regime as tax_regime)"}
    sets = ", ".join(f"{k} = {casts.get(k, ':' + k)}" for k in changes)
    return fetch_one(ctx.conn, f"update suppliers set {sets} where id = :id returning *",
                     {"id": supplier_id, **changes})


@router.post("/suppliers/{supplier_id}/companies/{company_id}", status_code=201)
def link_supplier(supplier_id: UUID, company_id: UUID, ctx: OrgContext = Depends(get_org)):
    _supplier(ctx, supplier_id)
    ctx.require_company(company_id, write=True)
    ctx.conn.execute(
        text("""insert into supplier_company_links (organization_id, supplier_id, company_id)
                values (:org, :s, :c) on conflict do nothing"""),
        {"org": ctx.org_id, "s": supplier_id, "c": company_id},
    )
    return {"supplier_id": supplier_id, "company_id": company_id}


@router.delete("/suppliers/{supplier_id}/companies/{company_id}", status_code=204)
def unlink_supplier(supplier_id: UUID, company_id: UUID, ctx: OrgContext = Depends(get_org)):
    ctx.require_company(company_id, write=True)
    ctx.conn.execute(text("delete from supplier_company_links where supplier_id = :s and company_id = :c"),
                     {"s": supplier_id, "c": company_id})


@router.post("/suppliers/import")
async def import_suppliers(
    file: UploadFile = File(..., description="CSV com colunas cnpj, razao_social, nome_fantasia, uf, regime, email, telefone, empresas"),
    ctx: OrgContext = Depends(get_org),
    settings: Settings = Depends(get_settings),
):
    ctx.require_write()
    content = await _read_limited(file, settings.max_upload_bytes)
    try:
        report = import_suppliers_csv(ctx.conn, str(ctx.org_id), content, settings.max_csv_rows)
    except ValueError as exc:
        raise Invalid(str(exc)) from exc
    result = report.as_dict()
    log_event(ctx.conn, ctx.org_id, "import", "suppliers_csv", metadata={
        "file": file.filename, "sha256": hashlib.sha256(content).hexdigest(),
        **{k: v for k, v in result.items() if k != "errors"},
    })
    return result


# ------------------------------------------------------------------ compliance

@router.get("/suppliers/{supplier_id}/checks", response_model=list[ComplianceCheckOut])
def list_checks(supplier_id: UUID, ctx: OrgContext = Depends(get_org), check_type: str | None = None):
    _supplier(ctx, supplier_id)
    return fetch_all(
        ctx.conn,
        """select * from compliance_checks where supplier_id = :s
              and (cast(:t as text) is null or check_type::text = :t)
            order by checked_at desc, created_at desc""",
        {"s": supplier_id, "t": check_type},
    )


@router.post("/suppliers/{supplier_id}/checks", response_model=ComplianceCheckOut, status_code=201)
def add_check(supplier_id: UUID, body: ComplianceCheckIn, ctx: OrgContext = Depends(get_org),
              settings: Settings = Depends(get_settings)):
    ctx.require_write()
    _supplier(ctx, supplier_id)
    valid_until = body.valid_until or default_valid_until(body.check_type, body.issued_at, body.result)
    check = fetch_one(
        ctx.conn,
        """insert into compliance_checks (organization_id, supplier_id, check_type, result, source,
                 source_reference, issued_at, valid_until, checked_at, checked_by, evidence_document_id, notes)
           values (:org, :s, cast(:check_type as check_type), cast(:result as check_result), :source,
                   :source_reference, :issued_at, :valid_until, coalesce(:checked_at, now()), :uid,
                   :evidence_document_id, :notes)
           returning *""",
        {"org": ctx.org_id, "s": supplier_id, "uid": ctx.user.id,
         **body.model_dump(exclude={"valid_until"}), "valid_until": valid_until},
    )
    scan_compliance(ctx.conn, str(ctx.org_id), settings.compliance_required_checks,
                    settings.compliance_expiry_warning_days, supplier_id=str(supplier_id))
    return check


@router.post("/suppliers/{supplier_id}/evidence", response_model=EvidenceOut, status_code=201)
async def upload_evidence(
    supplier_id: UUID,
    file: UploadFile = File(...),
    kind: str = Form("certidao", max_length=60),
    ctx: OrgContext = Depends(get_org),
    settings: Settings = Depends(get_settings),
):
    ctx.require_write()
    _supplier(ctx, supplier_id)
    content_type = (file.content_type or "").split(";")[0]
    if content_type not in ALLOWED_EVIDENCE_TYPES:
        raise Invalid(f"Tipo de arquivo não permitido: {content_type}")
    content = await _read_limited(file, settings.max_upload_bytes)
    path = content_path(str(ctx.org_id), "evidence", content, file.filename or "evidencia")
    get_storage().put(path, content, content_type)
    return fetch_one(
        ctx.conn,
        """insert into evidence_documents (organization_id, supplier_id, kind, file_name, content_type,
                                           size_bytes, sha256, storage_path, uploaded_by)
           values (:org, :s, :kind, :name, :ct, :size, :sha, :path, :uid) returning *""",
        {"org": ctx.org_id, "s": supplier_id, "kind": kind, "name": file.filename or "evidencia",
         "ct": content_type, "size": len(content), "sha": hashlib.sha256(content).hexdigest(),
         "path": path, "uid": ctx.user.id},
    )


@router.get("/evidence/{evidence_id}/download")
def download_evidence(evidence_id: UUID, ctx: OrgContext = Depends(get_org),
                      settings: Settings = Depends(get_settings)):
    ev = fetch_one(ctx.conn, "select * from evidence_documents where id = :id and organization_id = :org",
                   {"id": evidence_id, "org": ctx.org_id})
    if ev is None:
        raise NotFound("Evidência")
    storage = get_storage()
    url = storage.signed_url(ev["storage_path"], settings.signed_url_ttl_seconds)
    if url:
        return {"url": url, "expires_in": settings.signed_url_ttl_seconds}
    return Response(storage.get(ev["storage_path"]), media_type=ev["content_type"],
                    headers={"Content-Disposition": f'attachment; filename="{safe_filename(ev["file_name"])}"'})


@router.post("/compliance/scan")
def run_compliance_scan(ctx: OrgContext = Depends(get_org), settings: Settings = Depends(get_settings)):
    ctx.require_write()
    result = scan_compliance(ctx.conn, str(ctx.org_id), settings.compliance_required_checks,
                             settings.compliance_expiry_warning_days)
    log_event(ctx.conn, ctx.org_id, "compliance_scan", "suppliers", metadata=result)
    return result


@router.get("/compliance/report")
def compliance_report(
    ctx: OrgContext = Depends(get_org),
    company_id: UUID | None = None,
    format: str = Query("json", pattern="^(json|csv)$"),
):
    rows = fetch_all(
        ctx.conn,
        """
        select s.cnpj, s.legal_name, s.compliance_status::text as status, s.compliance_updated_at,
               lc.check_type::text as check_type, lc.result::text as result, lc.source,
               lc.valid_until, lc.checked_at,
               case when lc.valid_until < current_date then true else false end as expired
          from suppliers s
          left join lateral (
              select distinct on (check_type) * from compliance_checks c
               where c.supplier_id = s.id order by check_type, checked_at desc, created_at desc
          ) lc on true
         where s.organization_id = :org
           and (cast(:company as uuid) is null or exists (
                 select 1 from supplier_company_links l where l.supplier_id = s.id and l.company_id = cast(:company as uuid)))
         order by s.legal_name, lc.check_type
        """,
        {"org": ctx.org_id, "company": company_id},
    )
    log_event(ctx.conn, ctx.org_id, "export", "compliance_report",
              metadata={"format": format, "company_id": company_id, "rows": len(rows)})
    if format == "csv":
        headers = ["cnpj", "razao_social", "status", "status_atualizado_em", "verificacao", "resultado",
                   "fonte", "valido_ate", "verificado_em", "vencida"]
        return csv_response(f"compliance-{date.today().isoformat()}.csv", headers,
                            ([r[k] for k in r] for r in rows))
    return {"generated_at": date.today(), "rows": rows}
