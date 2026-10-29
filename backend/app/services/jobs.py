"""Fila de tarefas assíncronas sobre a tabela integration_jobs.

Usa `FOR UPDATE SKIP LOCKED`, permitindo vários workers sem infraestrutura
adicional (Redis etc.). Cada tarefa é executada *em nome do usuário que a
criou* (impersonação), de modo que a RLS continua valendo no worker.
"""

from __future__ import annotations

import json
import logging
import socket
import traceback
from collections.abc import Callable
from datetime import timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, text

from app.config import get_settings
from app.db import fetch_one, impersonate, service_connection

log = logging.getLogger("fiscalguard.jobs")

Handler = Callable[[Connection, dict], dict]
HANDLERS: dict[str, Handler] = {}
STALE_AFTER = timedelta(minutes=15)


def handler(kind: str) -> Callable[[Handler], Handler]:
    def register(fn: Handler) -> Handler:
        HANDLERS[kind] = fn
        return fn
    return register


def create_job(
    conn: Connection,
    *,
    org_id: str,
    kind: str,
    payload: dict,
    user_id: str,
    company_id: str | None = None,
    idempotency_key: str | None = None,
    max_attempts: int = 3,
) -> tuple[dict, bool]:
    """Cria a tarefa; se a chave de idempotência já existir, devolve a existente (created=False)."""
    job = fetch_one(
        conn,
        """
        insert into integration_jobs (organization_id, company_id, kind, payload, created_by, idempotency_key, max_attempts)
        values (:org, :company, :kind, cast(:payload as jsonb), :user, :key, :max)
        on conflict (organization_id, idempotency_key) do nothing
        returning *
        """,
        {"org": org_id, "company": company_id, "kind": kind, "payload": json.dumps(payload),
         "user": user_id, "key": idempotency_key, "max": max_attempts},
    )
    if job:
        return job, True
    existing = fetch_one(
        conn,
        "select * from integration_jobs where organization_id = :org and idempotency_key = :key",
        {"org": org_id, "key": idempotency_key},
    )
    return existing, False


def run_inline(conn: Connection, job: dict) -> dict:
    """Executa a tarefa na conexão atual (requisição síncrona para lotes pequenos)."""
    conn.execute(
        text("""update integration_jobs set status = 'running', attempts = attempts + 1,
                       started_at = now(), locked_by = 'inline' where id = :id"""),
        {"id": str(job["id"])},
    )
    result = HANDLERS[job["kind"]](conn, job)
    return fetch_one(
        conn,
        """update integration_jobs set status = 'succeeded', result = cast(:r as jsonb), error = null,
                  finished_at = now(), locked_by = null where id = :id returning *""",
        {"id": str(job["id"]), "r": json.dumps(result, default=str)},
    )


def requeue(conn: Connection, job_id: UUID | str) -> dict | None:
    """Reprocessamento manual de uma tarefa com falha."""
    return fetch_one(
        conn,
        """update integration_jobs set status = 'queued', run_after = now(), error = null,
                  attempts = 0, finished_at = null
            where id = :id and status in ('failed', 'dead', 'succeeded') returning *""",
        {"id": str(job_id)},
    )


# ------------------------------------------------------------------ worker

def _claim(worker_id: str) -> dict | None:
    with service_connection() as conn:
        conn.execute(
            text("""update integration_jobs set status = 'queued', locked_at = null, locked_by = null
                     where status = 'running' and locked_at < now() - :stale"""),
            {"stale": STALE_AFTER},
        )
        return fetch_one(
            conn,
            """
            update integration_jobs set status = 'running', locked_at = now(), locked_by = :w,
                   started_at = now(), attempts = attempts + 1
             where id = (select id from integration_jobs
                          where status = 'queued' and run_after <= now()
                          order by run_after for update skip locked limit 1)
            returning *
            """,
            {"w": worker_id},
        )


def run_next(worker_id: str | None = None) -> dict | None:
    """Processa uma tarefa da fila. Retorna a tarefa processada ou None se a fila estiver vazia."""
    worker_id = worker_id or f"{socket.gethostname()}"
    job = _claim(worker_id)
    if job is None:
        return None
    try:
        with service_connection() as conn:
            if job["created_by"]:
                impersonate(conn, job["created_by"])
            fn = HANDLERS.get(job["kind"])
            if fn is None:
                raise RuntimeError(f"tipo de tarefa desconhecido: {job['kind']}")
            result = fn(conn, job)
            conn.execute(
                text("""update integration_jobs set status = 'succeeded', result = cast(:r as jsonb),
                               error = null, finished_at = now(), locked_by = null where id = :id"""),
                {"id": str(job["id"]), "r": json.dumps(result, default=str)},
            )
        log.info("job %s (%s) concluído", job["id"], job["kind"])
    except Exception as exc:  # noqa: BLE001
        log.exception("job %s falhou", job["id"])
        dead = job["attempts"] >= job["max_attempts"]
        backoff = timedelta(seconds=30 * 2 ** (job["attempts"] - 1))
        with service_connection() as conn:
            conn.execute(
                text("""update integration_jobs
                           set status = :st, error = :err, locked_by = null, locked_at = null,
                               run_after = now() + :backoff, finished_at = case when :dead then now() end
                         where id = :id"""),
                {"id": str(job["id"]), "st": "dead" if dead else "queued", "dead": dead,
                 "err": f"{exc}\n{traceback.format_exc(limit=5)}"[:4000], "backoff": backoff},
            )
    return job


# ------------------------------------------------------------------ handlers

@handler("nfe_import")
def _nfe_import(conn: Connection, job: dict) -> dict[str, Any]:
    from app.services.fiscal_import import process_nfe_batch
    from app.services.storage import get_storage

    p = job["payload"]
    return process_nfe_batch(
        conn,
        org_id=str(job["organization_id"]),
        company_id=p["company_id"],
        files=p["files"],
        storage=get_storage(),
        user_id=str(job["created_by"]) if job["created_by"] else None,
        job_id=str(job["id"]),
        analyze=p.get("analyze", True),
    )


@handler("reanalyze_company")
def _reanalyze(conn: Connection, job: dict) -> dict[str, Any]:
    from app.db import fetch_all
    from app.services.analysis import analyze_document

    docs = fetch_all(conn, "select id from fiscal_documents where company_id = :c",
                     {"c": job["payload"]["company_id"]})
    matches = 0
    for d in docs:
        with conn.begin_nested():
            matches += analyze_document(conn, d["id"])["matches"]
    return {"documents": len(docs), "matches": matches}


@handler("compliance_scan")
def _compliance_scan(conn: Connection, job: dict) -> dict[str, Any]:
    from app.services.compliance import scan_compliance

    s = get_settings()
    return scan_compliance(conn, str(job["organization_id"]), s.compliance_required_checks,
                           s.compliance_expiry_warning_days)
