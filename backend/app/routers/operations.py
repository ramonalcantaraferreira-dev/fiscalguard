from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.db import fetch_all, fetch_one
from app.deps import OrgContext, get_org
from app.errors import Conflict, NotFound
from app.schemas import AlertOut, AlertUpdate, AuditEventOut, JobOut
from app.services.audit import log_event
from app.services.jobs import create_job, requeue

router = APIRouter(prefix="/api/v1/organizations/{org_id}", tags=["operação e auditoria"])


@router.get("/dashboard")
def dashboard(ctx: OrgContext = Depends(get_org), company_id: UUID | None = None):
    """Visão consolidada do escritório (ou de uma empresa)."""
    params = {"org": ctx.org_id, "c": company_id}
    company_filter = "(cast(:c as uuid) is null or company_id = cast(:c as uuid))"
    supplier_filter = """(cast(:c as uuid) is null or exists (select 1 from supplier_company_links l
                           where l.supplier_id = s.id and l.company_id = cast(:c as uuid)))"""
    return {
        "companies": fetch_one(ctx.conn, """select count(*) as total, count(*) filter (where active) as active
                                             from client_companies where organization_id = :org""", params),
        "suppliers_by_status": fetch_all(
            ctx.conn,
            f"""select compliance_status::text as status, count(*) as count from suppliers s
                 where organization_id = :org and {supplier_filter} group by 1 order by 1""", params),
        "documents": fetch_one(
            ctx.conn,
            f"""select count(*) as total, count(*) filter (where status = 'invalid') as invalid,
                       count(*) filter (where analyzed_at is null) as not_analyzed
                  from fiscal_documents where organization_id = :org and {company_filter}""", params),
        "opportunities": fetch_all(
            ctx.conn,
            f"""select tax, review_status::text as review_status, count(*) as count,
                       coalesce(sum(estimated_amount), 0) as estimated_amount
                  from tax_assessments where organization_id = :org and {company_filter}
                 group by 1, 2 order by 1, 2""", params),
        "open_alerts": fetch_all(
            ctx.conn,
            """select severity::text as severity, count(*) as count from alerts
                where organization_id = :org and status <> 'resolved' group by 1""", params),
        "recent_jobs": fetch_all(
            ctx.conn,
            """select id, kind, status::text as status, created_at, finished_at from integration_jobs
                where organization_id = :org order by created_at desc limit 5""", params),
    }


# ------------------------------------------------------------------ alertas

@router.get("/alerts", response_model=list[AlertOut])
def list_alerts(
    ctx: OrgContext = Depends(get_org),
    status: str | None = Query("open", pattern="^(open|acknowledged|resolved|all)$"),
    severity: str | None = Query(None, pattern="^(info|warning|critical)$"),
    limit: int = Query(100, le=500),
):
    return fetch_all(
        ctx.conn,
        """select * from alerts where organization_id = :org
              and (:status = 'all' or status::text = :status)
              and (cast(:sev as text) is null or severity::text = :sev)
            order by case severity when 'critical' then 0 when 'warning' then 1 else 2 end,
                     due_date nulls last, created_at desc
            limit :limit""",
        {"org": ctx.org_id, "status": status, "sev": severity, "limit": limit},
    )


@router.patch("/alerts/{alert_id}", response_model=AlertOut)
def update_alert(alert_id: UUID, body: AlertUpdate, ctx: OrgContext = Depends(get_org)):
    ctx.require_write()
    row = fetch_one(
        ctx.conn,
        """update alerts set status = cast(:st as alert_status),
                  resolved_at = case when :st = 'resolved' then now() else resolved_at end
            where id = :id and organization_id = :org returning *""",
        {"id": alert_id, "org": ctx.org_id, "st": body.status},
    )
    if row is None:
        raise NotFound("Alerta")
    return row


# ------------------------------------------------------------------ tarefas

@router.get("/jobs", response_model=list[JobOut])
def list_jobs(
    ctx: OrgContext = Depends(get_org),
    status: str | None = Query(None, pattern="^(queued|running|succeeded|failed|dead)$"),
    limit: int = Query(50, le=200),
):
    return fetch_all(
        ctx.conn,
        """select * from integration_jobs where organization_id = :org
              and (cast(:st as text) is null or status::text = :st)
            order by created_at desc limit :limit""",
        {"org": ctx.org_id, "st": status, "limit": limit},
    )


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: UUID, ctx: OrgContext = Depends(get_org)):
    row = fetch_one(ctx.conn, "select * from integration_jobs where id = :id and organization_id = :org",
                    {"id": job_id, "org": ctx.org_id})
    if row is None:
        raise NotFound("Tarefa")
    return row


@router.post("/jobs/{job_id}/retry", response_model=JobOut)
def retry_job(job_id: UUID, ctx: OrgContext = Depends(get_org)):
    ctx.require_write()
    get_job(job_id, ctx)
    row = requeue(ctx.conn, job_id)
    if row is None:
        raise Conflict("A tarefa ainda está em execução ou na fila")
    log_event(ctx.conn, ctx.org_id, "reprocess", "integration_jobs", job_id)
    return row


@router.post("/compliance/scan/async", response_model=JobOut, status_code=202)
def enqueue_compliance_scan(ctx: OrgContext = Depends(get_org)):
    ctx.require_write()
    job, _ = create_job(ctx.conn, org_id=str(ctx.org_id), kind="compliance_scan", payload={},
                        user_id=str(ctx.user.id))
    return job


# ------------------------------------------------------------------ auditoria

@router.get("/audit-events", response_model=list[AuditEventOut])
def list_audit_events(
    ctx: OrgContext = Depends(get_org),
    entity_type: str | None = None,
    entity_id: UUID | None = None,
    limit: int = Query(100, le=500),
    before_id: int | None = None,
):
    ctx.require_admin()
    return fetch_all(
        ctx.conn,
        """select * from audit_events where organization_id = :org
              and (cast(:et as text) is null or entity_type = :et)
              and (cast(:eid as uuid) is null or entity_id = cast(:eid as uuid))
              and (cast(:before as bigint) is null or id < :before)
            order by id desc limit :limit""",
        {"org": ctx.org_id, "et": entity_type, "eid": entity_id, "before": before_id, "limit": limit},
    )
