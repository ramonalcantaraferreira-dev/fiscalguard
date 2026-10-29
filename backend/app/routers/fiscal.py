from __future__ import annotations

import hashlib
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import JSONResponse, Response

from app.config import Settings, get_settings
from app.db import fetch_all, fetch_one
from app.deps import OrgContext, get_org
from app.errors import Invalid, NotFound
from app.schemas import FiscalDocumentDetail, FiscalDocumentOut, JobOut
from app.services.analysis import analyze_document
from app.services.audit import log_event
from app.services.jobs import create_job, run_inline
from app.services.storage import content_path, get_storage

router = APIRouter(prefix="/api/v1/organizations/{org_id}", tags=["inteligência fiscal"])


def _document(ctx: OrgContext, document_id: UUID) -> dict:
    row = fetch_one(ctx.conn, "select * from fiscal_documents where id = :id and organization_id = :org",
                    {"id": document_id, "org": ctx.org_id})
    if row is None:
        raise NotFound("Documento fiscal")
    return row


@router.post("/companies/{company_id}/fiscal-documents/import", response_model=JobOut)
async def import_xml(
    company_id: UUID,
    files: list[UploadFile] = File(..., description="Um ou mais XML de NF-e (procNFe ou NFe)"),
    force_async: bool = Query(False, alias="async"),
    analyze: bool = True,
    ctx: OrgContext = Depends(get_org),
    settings: Settings = Depends(get_settings),
):
    """Importa XMLs de NF-e. Lotes pequenos são processados na hora (200);
    lotes grandes ou `async=true` são enfileirados (202) e acompanhados em /jobs/{id}."""
    ctx.require_company(company_id, write=True)
    if len(files) > settings.max_files_per_upload:
        raise Invalid(f"Máximo de {settings.max_files_per_upload} arquivos por envio")

    storage = get_storage()
    stored: list[dict] = []
    for upload in files:
        content = await upload.read(settings.max_upload_bytes + 1)
        if len(content) > settings.max_upload_bytes:
            raise Invalid(f"Arquivo {upload.filename} excede o tamanho máximo")
        path = content_path(str(ctx.org_id), "nfe", content, upload.filename or "nfe.xml")
        storage.put(path, content, "application/xml")
        stored.append({"name": upload.filename, "path": path, "sha256": hashlib.sha256(content).hexdigest()})

    batch_hash = hashlib.sha256(
        (str(company_id) + "|" + "|".join(sorted(f["sha256"] for f in stored))).encode()
    ).hexdigest()
    job, created = create_job(
        ctx.conn, org_id=str(ctx.org_id), kind="nfe_import", company_id=str(company_id),
        user_id=str(ctx.user.id), idempotency_key=f"nfe_import:{batch_hash}",
        payload={"company_id": str(company_id), "files": stored, "analyze": analyze},
    )
    log_event(ctx.conn, ctx.org_id, "import", "fiscal_documents", job["id"],
              {"files": len(stored), "company_id": company_id, "new_job": created})

    if created and not force_async and len(stored) <= settings.inline_import_limit:
        job = run_inline(ctx.conn, job)
        return JobOut.model_validate(job)
    status = 200 if job["status"] in ("succeeded", "failed", "dead") else 202
    return JSONResponse(JobOut.model_validate(job).model_dump(mode="json"), status_code=status)


@router.get("/fiscal-documents", response_model=list[FiscalDocumentOut])
def list_documents(
    ctx: OrgContext = Depends(get_org),
    company_id: UUID | None = None,
    status: str | None = Query(None, pattern="^(received|validated|invalid)$"),
    direction: str | None = Query(None, pattern="^(inbound|outbound)$"),
    date_from: date | None = None,
    date_to: date | None = None,
    q: str | None = Query(None, max_length=60, description="Chave de acesso, CNPJ ou nome do emitente"),
    limit: int = Query(100, le=500),
    offset: int = 0,
):
    return fetch_all(
        ctx.conn,
        """
        select * from fiscal_documents
         where organization_id = :org
           and (cast(:company as uuid) is null or company_id = cast(:company as uuid))
           and (cast(:status as text) is null or status::text = :status)
           and (cast(:direction as text) is null or direction::text = :direction)
           and (cast(:dfrom as date) is null or issue_date >= cast(:dfrom as date))
           and (cast(:dto as date) is null or issue_date < cast(:dto as date) + 1)
           and (cast(:q as text) is null or access_key like :q || '%' or issuer_cnpj like :q || '%'
                or issuer_name ilike '%' || :q || '%')
         order by issue_date desc nulls last limit :limit offset :offset
        """,
        {"org": ctx.org_id, "company": company_id, "status": status, "direction": direction,
         "dfrom": date_from, "dto": date_to, "q": q, "limit": limit, "offset": offset},
    )


@router.get("/fiscal-documents/{document_id}", response_model=FiscalDocumentDetail)
def get_document(document_id: UUID, ctx: OrgContext = Depends(get_org)):
    doc = _document(ctx, document_id)
    doc["items"] = fetch_all(ctx.conn, "select * from fiscal_document_items where document_id = :d order by item_number",
                             {"d": document_id})
    return doc


@router.get("/fiscal-documents/{document_id}/xml")
def download_xml(document_id: UUID, ctx: OrgContext = Depends(get_org)):
    doc = _document(ctx, document_id)
    if not doc["storage_path"]:
        raise NotFound("Arquivo XML")
    return Response(get_storage().get(doc["storage_path"]), media_type="application/xml",
                    headers={"Content-Disposition": f'attachment; filename="{doc["access_key"]}.xml"'})


@router.post("/fiscal-documents/{document_id}/analyze")
def reanalyze_document(document_id: UUID, ctx: OrgContext = Depends(get_org)):
    doc = _document(ctx, document_id)
    ctx.require_company(doc["company_id"], write=True)
    result = analyze_document(ctx.conn, document_id)
    log_event(ctx.conn, ctx.org_id, "reprocess", "fiscal_documents", document_id, result)
    return result


@router.post("/companies/{company_id}/reanalyze", response_model=JobOut, status_code=202)
def reanalyze_company(company_id: UUID, ctx: OrgContext = Depends(get_org)):
    """Reaplica as regras vigentes a todos os documentos da empresa (assíncrono)."""
    ctx.require_company(company_id, write=True)
    job, _ = create_job(ctx.conn, org_id=str(ctx.org_id), kind="reanalyze_company",
                        company_id=str(company_id), user_id=str(ctx.user.id),
                        payload={"company_id": str(company_id)})
    return job


@router.get("/fiscal-documents/stats/summary")
def fiscal_summary(ctx: OrgContext = Depends(get_org), company_id: UUID | None = None):
    return fetch_one(
        ctx.conn,
        """select count(*) as documents,
                  count(*) filter (where status = 'invalid') as invalid,
                  coalesce(sum(total_amount), 0) as total_amount,
                  max(created_at) as last_import
             from fiscal_documents
            where organization_id = :org and (cast(:c as uuid) is null or company_id = cast(:c as uuid))""",
        {"org": ctx.org_id, "c": company_id},
    )

