from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.db import fetch_all, fetch_one
from app.deps import OrgContext, get_org
from app.errors import NotFound
from app.schemas import AssessmentOut, ReviewIn
from app.services.audit import log_event
from app.services.export import csv_response

router = APIRouter(prefix="/api/v1/organizations/{org_id}/assessments", tags=["oportunidades e revisão"])

_SELECT = """
    select a.*, d.access_key, d.issuer_name
      from tax_assessments a join fiscal_documents d on d.id = a.document_id
     where a.organization_id = :org
       and (cast(:company as uuid) is null or a.company_id = cast(:company as uuid))
       and (cast(:document as uuid) is null or a.document_id = cast(:document as uuid))
       and (cast(:status as text) is null or a.review_status::text = :status)
       and (cast(:tax as text) is null or a.tax = :tax)
"""


def _filters(ctx: OrgContext, company_id, document_id, status, tax) -> dict:
    return {"org": ctx.org_id, "company": company_id, "document": document_id, "status": status, "tax": tax}


@router.get("", response_model=list[AssessmentOut])
def list_assessments(
    ctx: OrgContext = Depends(get_org),
    company_id: UUID | None = None,
    document_id: UUID | None = None,
    review_status: str | None = Query(None, pattern="^(pending_review|approved|rejected|needs_info)$"),
    tax: str | None = None,
    limit: int = Query(100, le=500),
    offset: int = 0,
):
    return fetch_all(
        ctx.conn,
        _SELECT + " order by a.created_at desc, a.id limit :limit offset :offset",
        {**_filters(ctx, company_id, document_id, review_status, tax), "limit": limit, "offset": offset},
    )


@router.get("/summary")
def summary(ctx: OrgContext = Depends(get_org), company_id: UUID | None = None):
    """Totais por tributo e status. Valores são estimativas de oportunidades potenciais."""
    return fetch_all(
        ctx.conn,
        """select tax, review_status::text as review_status, count(*) as count,
                  coalesce(sum(estimated_amount), 0) as estimated_amount
             from tax_assessments
            where organization_id = :org and (cast(:c as uuid) is null or company_id = cast(:c as uuid))
            group by tax, review_status order by tax, review_status""",
        {"org": ctx.org_id, "c": company_id},
    )


@router.get("/export")
def export_assessments(
    ctx: OrgContext = Depends(get_org),
    company_id: UUID | None = None,
    review_status: str | None = Query(None, pattern="^(pending_review|approved|rejected|needs_info)$"),
    tax: str | None = None,
):
    rows = fetch_all(ctx.conn, _SELECT + " order by a.created_at",
                     _filters(ctx, company_id, None, review_status, tax))
    log_event(ctx.conn, ctx.org_id, "export", "tax_assessments",
              metadata={"rows": len(rows), "company_id": company_id, "review_status": review_status})
    headers = ["id", "chave_acesso", "emitente", "tributo", "regra", "versao_regra", "hash_regra",
               "valor_estimado", "status_revisao", "justificativa", "notas_revisao", "revisado_em"]
    return csv_response(
        f"oportunidades-{date.today().isoformat()}.csv", headers,
        ([r["id"], r["access_key"], r["issuer_name"], r["tax"], r["rule_code"], r["rule_version"],
          r["rule_hash"], r["estimated_amount"], r["review_status"], r["justification"],
          r["review_notes"], r["reviewed_at"]] for r in rows),
    )


@router.get("/{assessment_id}", response_model=AssessmentOut)
def get_assessment(assessment_id: UUID, ctx: OrgContext = Depends(get_org)):
    row = fetch_one(ctx.conn, _SELECT + " and a.id = :id",
                    {**_filters(ctx, None, None, None, None), "id": assessment_id})
    if row is None:
        raise NotFound("Avaliação")
    return row


@router.patch("/{assessment_id}/review", response_model=AssessmentOut)
def review(assessment_id: UUID, body: ReviewIn, ctx: OrgContext = Depends(get_org)):
    """Revisão humana. Toda alteração fica registrada na auditoria (trigger)."""
    current = get_assessment(assessment_id, ctx)
    ctx.require_company(current["company_id"], write=True)
    fetch_one(
        ctx.conn,
        """update tax_assessments set review_status = cast(:st as review_status), review_notes = :notes,
                  reviewed_by = :uid, reviewed_at = now()
            where id = :id returning id""",
        {"id": assessment_id, "st": body.review_status, "notes": body.review_notes, "uid": ctx.user.id},
    )
    return get_assessment(assessment_id, ctx)
