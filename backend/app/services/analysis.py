"""Aplicação das regras tributárias publicadas aos documentos fiscais.

Resultados são *potenciais* oportunidades: cada um nasce com status
`pending_review` e só um revisor humano pode aprová-lo ou rejeitá-lo.
Reprocessar um documento é idempotente e nunca sobrescreve um resultado já
revisado.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, text

from app.db import fetch_all, fetch_one
from app.services.rule_engine import RuleDefinition, evaluate_rule

log = logging.getLogger("fiscalguard.analysis")

_RULE_FIELDS = (
    "code", "name", "description", "tax", "legal_basis", "scope", "conditions",
    "estimate", "justification_template", "valid_from", "valid_to",
)


def rule_from_row(row: dict) -> RuleDefinition:
    return RuleDefinition(**{k: row[k] for k in _RULE_FIELDS})


def applicable_rules(conn: Connection, org_id: UUID | str, on_date: date) -> list[tuple[dict, RuleDefinition]]:
    """Regras publicadas vigentes na data do documento.

    Para cada código vale a regra da organização (se houver) sobre a global, e a
    maior versão vigente. Regras cujo hash não confere são ignoradas (integridade).
    """
    rows = fetch_all(
        conn,
        """
        select * from tax_rules
         where status = 'published'
           and (organization_id = :org or organization_id is null)
           and valid_from <= :d and (valid_to is null or valid_to >= :d)
         order by code, (organization_id is null), version desc
        """,
        {"org": str(org_id), "d": on_date},
    )
    selected: dict[str, tuple[dict, RuleDefinition]] = {}
    for row in rows:
        if row["code"] in selected:
            continue
        definition = rule_from_row(row)
        if definition.content_hash() != row["content_hash"]:
            log.error("Hash divergente na regra %s v%s; ignorada", row["code"], row["version"])
            continue
        selected[row["code"]] = (row, definition)
    return list(selected.values())


def _plain(row: dict | None) -> dict[str, Any]:
    if not row:
        return {}
    out: dict[str, Any] = {}
    for k, v in row.items():
        if isinstance(v, UUID):
            v = str(v)
        out[k] = v
    return out


def build_facts(document: dict, company: dict, supplier: dict | None) -> dict[str, dict[str, Any]]:
    return {
        "document": _plain(document),
        "company": _plain(company),
        "supplier": _plain(supplier),
    }


def _json(value: Any) -> str:
    def default(o: Any) -> Any:
        if isinstance(o, (Decimal, UUID)):
            return str(o)
        if isinstance(o, (date, datetime)):
            return o.isoformat()
        raise TypeError(type(o))

    return json.dumps(value, default=default, ensure_ascii=False)


_UPSERT = text(
    """
    insert into tax_assessments (
      organization_id, company_id, document_id, item_id, rule_id, rule_code, rule_version,
      rule_hash, run_id, tax, estimated_amount, inputs, criteria, justification, evidence
    ) values (
      :org, :company, :doc, :item, :rule_id, :code, :version, :hash, :run, :tax, :amount,
      cast(:inputs as jsonb), cast(:criteria as jsonb), :justification, cast(:evidence as jsonb)
    )
    on conflict (document_id, item_id, rule_id) do update set
      run_id = excluded.run_id,
      estimated_amount = excluded.estimated_amount,
      inputs = excluded.inputs,
      criteria = excluded.criteria,
      justification = excluded.justification,
      evidence = excluded.evidence
    where tax_assessments.review_status = 'pending_review'
    """
)


def analyze_document(conn: Connection, document_id: UUID | str) -> dict[str, Any]:
    document = fetch_one(conn, "select * from fiscal_documents where id = :id", {"id": str(document_id)})
    if document is None:
        raise LookupError("documento não encontrado")
    company = fetch_one(conn, "select * from client_companies where id = :id", {"id": document["company_id"]})
    supplier = None
    if document["supplier_id"]:
        supplier = fetch_one(conn, "select * from suppliers where id = :id", {"id": document["supplier_id"]})
    items = fetch_all(
        conn, "select * from fiscal_document_items where document_id = :id order by item_number",
        {"id": str(document_id)},
    )

    on_date = (document["issue_date"] or document["created_at"]).date()
    rules = applicable_rules(conn, document["organization_id"], on_date)
    base_facts = build_facts(document, company, supplier)
    run_id = uuid.uuid4()
    matches = 0
    total = Decimal(0)

    for row, rule in rules:
        targets: list[dict | None] = items if rule.scope == "item" else [None]
        for item in targets:
            facts = dict(base_facts, item=_plain(item))
            result = evaluate_rule(rule, facts)
            if not result.matched:
                continue
            matches += 1
            if result.estimated_amount and row["tax"] != "RISCO":
                total += result.estimated_amount
            evidence = [{
                "type": "fiscal_document",
                "access_key": document["access_key"],
                "item_number": item["item_number"] if item else None,
                "storage_path": document["storage_path"],
                "rule_legal_basis": row["legal_basis"],
                "rule_validated_by_specialist": row["validated_by_specialist"],
            }]
            conn.execute(_UPSERT, {
                "org": str(document["organization_id"]),
                "company": str(document["company_id"]),
                "doc": str(document_id),
                "item": str(item["id"]) if item else None,
                "rule_id": str(row["id"]),
                "code": row["code"],
                "version": row["version"],
                "hash": row["content_hash"],
                "run": str(run_id),
                "tax": row["tax"],
                "amount": result.estimated_amount,
                "inputs": _json(result.inputs),
                "criteria": _json(result.trace),
                "justification": result.justification,
                "evidence": _json(evidence),
            })

    # Resultados pendentes que deixaram de se aplicar são removidos; revisados permanecem.
    removed = conn.execute(
        text("""delete from tax_assessments
                 where document_id = :doc and review_status = 'pending_review' and run_id <> :run"""),
        {"doc": str(document_id), "run": str(run_id)},
    ).rowcount
    conn.execute(text("update fiscal_documents set analyzed_at = now() where id = :id"), {"id": str(document_id)})

    return {
        "run_id": str(run_id),
        "rules_evaluated": len(rules),
        "matches": matches,
        "stale_removed": removed,
        "estimated_total": str(total),
    }
