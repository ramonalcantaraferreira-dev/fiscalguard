"""Importação idempotente de XML de NF-e para uma empresa."""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, text

from app.db import fetch_one, fetch_value
from app.services.nfe_parser import NFeDocument, NFeParseError, parse_nfe
from app.services.storage import Storage

log = logging.getLogger("fiscalguard.import")


def _direction(doc: NFeDocument, company_cnpj: str) -> str:
    if doc.recipient_cnpj == company_cnpj:
        return "inbound"
    if doc.issuer_cnpj == company_cnpj:
        return "outbound"
    return "unrelated"


def _ensure_supplier(conn: Connection, org_id: str, company_id: str, doc: NFeDocument) -> str | None:
    """Cadastra (se necessário) o emitente como fornecedor e o vincula à empresa."""
    if not doc.issuer_cnpj or len(doc.issuer_cnpj) != 14:
        return None
    supplier_id = fetch_value(
        conn,
        """
        insert into suppliers (organization_id, cnpj, legal_name, uf)
        values (:org, :cnpj, :name, :uf)
        on conflict (organization_id, cnpj) do update set cnpj = excluded.cnpj
        returning id
        """,
        {"org": org_id, "cnpj": doc.issuer_cnpj, "name": doc.issuer_name or doc.issuer_cnpj, "uf": doc.issuer_uf},
    )
    conn.execute(
        text("""insert into supplier_company_links (organization_id, supplier_id, company_id)
                values (:org, :s, :c) on conflict (supplier_id, company_id) do nothing"""),
        {"org": org_id, "s": supplier_id, "c": company_id},
    )
    return str(supplier_id)


_ITEM_COLUMNS = (
    "item_number", "product_code", "description", "ncm", "cest", "cfop", "unit", "quantity",
    "unit_price", "total_value", "discount", "icms_origin", "icms_cst", "icms_base", "icms_rate",
    "icms_value", "icms_st_value", "ipi_cst", "ipi_value", "pis_cst", "pis_base", "pis_rate",
    "pis_value", "cofins_cst", "cofins_base", "cofins_rate", "cofins_value",
)
_INSERT_ITEM = text(
    f"""insert into fiscal_document_items (organization_id, document_id, raw_taxes, {", ".join(_ITEM_COLUMNS)})
        values (:org, :doc, cast(:raw_taxes as jsonb), {", ".join(":" + c for c in _ITEM_COLUMNS)})"""
)


def import_nfe(
    conn: Connection,
    *,
    org_id: UUID | str,
    company: dict,
    content: bytes,
    filename: str,
    storage_path: str | None,
    user_id: UUID | str | None,
    job_id: UUID | str | None = None,
) -> dict[str, Any]:
    """Importa um XML. Retorna um dict com `status` em:
    imported | imported_with_errors | duplicate | rejected
    """
    org_id, company_id = str(org_id), str(company["id"])
    try:
        doc = parse_nfe(content)
    except NFeParseError as exc:
        return {"file": filename, "status": "rejected", "errors": [{"code": "parse_error", "message": str(exc)}]}

    direction = _direction(doc, company["cnpj"])
    if direction == "unrelated":
        return {
            "file": filename,
            "status": "rejected",
            "access_key": doc.access_key,
            "errors": [{"code": "not_company_document",
                        "message": "A empresa não é emitente nem destinatária desta NF-e"}],
        }

    existing = fetch_one(
        conn,
        "select id from fiscal_documents where company_id = :c and access_key = :k",
        {"c": company_id, "k": doc.access_key},
    )
    if existing:
        return {"file": filename, "status": "duplicate", "access_key": doc.access_key,
                "document_id": str(existing["id"])}

    supplier_id = _ensure_supplier(conn, org_id, company_id, doc) if direction == "inbound" else None

    document_id = fetch_value(
        conn,
        """
        insert into fiscal_documents (
          organization_id, company_id, supplier_id, model, access_key, number, series, issue_date,
          operation_type, direction, issuer_cnpj, issuer_name, issuer_uf, issuer_crt,
          recipient_cnpj, recipient_name, recipient_uf, total_products, total_discount, total_icms,
          total_icms_st, total_ipi, total_pis, total_cofins, total_amount, protocol_number, status,
          validation_errors, raw_sha256, storage_path, import_job_id, imported_by
        ) values (
          :org, :company, :supplier, coalesce(:model, '55'), :key, :number, :series, :issue_date,
          :op, :direction, :issuer_cnpj, :issuer_name, :issuer_uf, :issuer_crt,
          :recipient_cnpj, :recipient_name, :recipient_uf, :t_prod, :t_desc, :t_icms,
          :t_st, :t_ipi, :t_pis, :t_cofins, :t_nf, :protocol, :status,
          cast(:issues as jsonb), :sha, :path, :job, :user
        )
        on conflict (company_id, access_key) do nothing
        returning id
        """,
        {
            "org": org_id, "company": company_id, "supplier": supplier_id, "model": doc.model,
            "key": doc.access_key, "number": doc.number, "series": doc.series,
            "issue_date": doc.issue_date, "op": doc.operation_type, "direction": direction,
            "issuer_cnpj": doc.issuer_cnpj, "issuer_name": doc.issuer_name, "issuer_uf": doc.issuer_uf,
            "issuer_crt": doc.issuer_crt, "recipient_cnpj": doc.recipient_cnpj,
            "recipient_name": doc.recipient_name, "recipient_uf": doc.recipient_uf,
            "t_prod": doc.total_products, "t_desc": doc.total_discount, "t_icms": doc.total_icms,
            "t_st": doc.total_icms_st, "t_ipi": doc.total_ipi, "t_pis": doc.total_pis,
            "t_cofins": doc.total_cofins, "t_nf": doc.total_amount, "protocol": doc.protocol_number,
            "status": "validated" if doc.is_valid else "invalid",
            "issues": json.dumps(doc.issues_as_json(), ensure_ascii=False),
            "sha": doc.sha256, "path": storage_path,
            "job": str(job_id) if job_id else None, "user": str(user_id) if user_id else None,
        },
    )
    if document_id is None:  # corrida com outra importação concorrente
        existing_id = fetch_value(
            conn, "select id from fiscal_documents where company_id = :c and access_key = :k",
            {"c": company_id, "k": doc.access_key},
        )
        return {"file": filename, "status": "duplicate", "access_key": doc.access_key,
                "document_id": str(existing_id)}

    for item in doc.items:
        params = {c: getattr(item, c) for c in _ITEM_COLUMNS}
        params.update(org=org_id, doc=str(document_id), raw_taxes=json.dumps(item.raw_taxes, ensure_ascii=False))
        conn.execute(_INSERT_ITEM, params)

    return {
        "file": filename,
        "status": "imported" if doc.is_valid else "imported_with_errors",
        "access_key": doc.access_key,
        "document_id": str(document_id),
        "direction": direction,
        "issues": doc.issues_as_json(),
    }


def process_nfe_batch(
    conn: Connection,
    *,
    org_id: str,
    company_id: str,
    files: list[dict],
    storage: Storage,
    user_id: str | None,
    job_id: str | None,
    analyze: bool = True,
) -> dict[str, Any]:
    """Processa um lote; cada arquivo roda num SAVEPOINT para isolar falhas."""
    from app.services.analysis import analyze_document

    company = fetch_one(conn, "select * from client_companies where id = :id and organization_id = :org",
                        {"id": company_id, "org": org_id})
    if company is None:
        raise LookupError("empresa não encontrada ou sem acesso")

    results: list[dict] = []
    for f in files:
        try:
            with conn.begin_nested():
                content = storage.get(f["path"])
                result = import_nfe(
                    conn, org_id=org_id, company=company, content=content, filename=f["name"],
                    storage_path=f["path"], user_id=user_id, job_id=job_id,
                )
                if analyze and result["status"] in ("imported", "imported_with_errors"):
                    result["analysis"] = analyze_document(conn, result["document_id"])
        except Exception as exc:  # noqa: BLE001 — falha de um arquivo não derruba o lote
            log.exception("Falha ao importar %s", f.get("name"))
            result = {"file": f.get("name"), "status": "failed", "errors": [{"code": "internal", "message": str(exc)[:500]}]}
        results.append(result)

    summary: dict[str, int] = {}
    for r in results:
        summary[r["status"]] = summary.get(r["status"], 0) + 1
    return {"summary": summary, "files": results}
