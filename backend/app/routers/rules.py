"""Gestão de regras tributárias versionadas.

Fluxo: rascunho → (validação do especialista) → publicada → aposentada.
Uma regra publicada nunca é editada: alterações geram nova versão, e as
avaliações antigas continuam apontando para a versão (e hash) que as produziu.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import ValidationError

from app.db import fetch_all, fetch_one, fetch_value
from app.deps import OrgContext, get_org
from app.errors import Conflict, Invalid, NotFound
from app.schemas import PublishIn, RetireIn, RuleTestIn, TaxRuleOut
from app.services.analysis import rule_from_row
from app.services.rule_engine import RuleDefinition, RuleDefinitionError, evaluate_rule

router = APIRouter(prefix="/api/v1/organizations/{org_id}/tax-rules", tags=["regras tributárias"])


def _rule(ctx: OrgContext, rule_id: UUID) -> dict:
    row = fetch_one(
        ctx.conn,
        "select * from tax_rules where id = :id and (organization_id = :org or organization_id is null)",
        {"id": rule_id, "org": ctx.org_id},
    )
    if row is None:
        raise NotFound("Regra")
    return row


def _insert(ctx: OrgContext, definition: RuleDefinition, version: int, supersedes: UUID | None) -> dict:
    data = definition.model_dump(mode="json")
    return fetch_one(
        ctx.conn,
        """
        insert into tax_rules (organization_id, code, version, name, description, tax, legal_basis, scope,
                               conditions, estimate, justification_template, valid_from, valid_to,
                               status, content_hash, supersedes_id, created_by)
        values (:org, :code, :version, :name, :description, :tax, :legal_basis, cast(:scope as rule_scope),
                cast(:conditions as jsonb), cast(:estimate as jsonb), :justification_template,
                :valid_from, :valid_to, 'draft', :hash, :supersedes, :uid)
        returning *
        """,
        {
            **data, "org": ctx.org_id, "version": version, "hash": definition.content_hash(),
            "conditions": json.dumps(data["conditions"]),
            "estimate": json.dumps(data["estimate"]) if data["estimate"] else None,
            "supersedes": supersedes, "uid": ctx.user.id,
        },
    )


def _parse(payload: dict) -> RuleDefinition:
    try:
        return RuleDefinition.model_validate(payload)
    except (ValidationError, RuleDefinitionError) as exc:
        details = exc.errors(include_url=False, include_context=False) if isinstance(exc, ValidationError) else str(exc)
        raise Invalid("Definição de regra inválida", json.loads(json.dumps(details, default=str))) from exc


@router.get("", response_model=list[TaxRuleOut])
def list_rules(
    ctx: OrgContext = Depends(get_org),
    status: str | None = Query(None, pattern="^(draft|published|retired)$"),
    code: str | None = None,
):
    return fetch_all(
        ctx.conn,
        """select * from tax_rules
            where (organization_id = :org or organization_id is null)
              and (cast(:status as text) is null or status::text = :status)
              and (cast(:code as text) is null or code = :code)
            order by code, version desc""",
        {"org": ctx.org_id, "status": status, "code": code},
    )


@router.get("/{rule_id}", response_model=TaxRuleOut)
def get_rule(rule_id: UUID, ctx: OrgContext = Depends(get_org)):
    return _rule(ctx, rule_id)


@router.post("", response_model=TaxRuleOut, status_code=201)
def create_rule(payload: dict, ctx: OrgContext = Depends(get_org)):
    """Cria a versão 1 de uma regra da organização, como rascunho."""
    ctx.require_admin()
    definition = _parse(payload)
    exists = fetch_value(ctx.conn, "select 1 from tax_rules where organization_id = :org and code = :code",
                         {"org": ctx.org_id, "code": definition.code})
    if exists:
        raise Conflict("Código já existe; crie uma nova versão")
    return _insert(ctx, definition, 1, None)


@router.post("/{rule_id}/versions", response_model=TaxRuleOut, status_code=201)
def new_version(rule_id: UUID, payload: dict, ctx: OrgContext = Depends(get_org)):
    """Cria uma nova versão (rascunho) a partir de uma regra existente — inclusive global."""
    ctx.require_admin()
    base = _rule(ctx, rule_id)
    definition = _parse({**{k: base[k] for k in ("code", "name", "description", "tax", "legal_basis", "scope",
                                                 "conditions", "estimate", "justification_template",
                                                 "valid_from")}, **payload, "code": base["code"]})
    latest = fetch_value(
        ctx.conn,
        "select max(version) from tax_rules where code = :code and (organization_id = :org or organization_id is null)",
        {"code": base["code"], "org": ctx.org_id},
    )
    return _insert(ctx, definition, (latest or 0) + 1, base["id"])


@router.patch("/{rule_id}", response_model=TaxRuleOut)
def update_draft(rule_id: UUID, payload: dict, ctx: OrgContext = Depends(get_org)):
    ctx.require_admin()
    row = _rule(ctx, rule_id)
    if row["status"] != "draft" or row["organization_id"] is None:
        raise Conflict("Somente rascunhos da organização podem ser editados")
    current = rule_from_row(row).model_dump(mode="json")
    definition = _parse({**current, **payload, "code": row["code"]})
    data = definition.model_dump(mode="json")
    return fetch_one(
        ctx.conn,
        """update tax_rules set name = :name, description = :description, tax = :tax, legal_basis = :legal_basis,
                  scope = cast(:scope as rule_scope), conditions = cast(:conditions as jsonb),
                  estimate = cast(:estimate as jsonb), justification_template = :justification_template,
                  valid_from = :valid_from, valid_to = :valid_to, content_hash = :hash
            where id = :id returning *""",
        {**data, "id": rule_id, "hash": definition.content_hash(),
         "conditions": json.dumps(data["conditions"]),
         "estimate": json.dumps(data["estimate"]) if data["estimate"] else None},
    )


@router.post("/{rule_id}/publish", response_model=TaxRuleOut)
def publish(rule_id: UUID, body: PublishIn, ctx: OrgContext = Depends(get_org)):
    """Publica o rascunho. Exige o registro do especialista que validou a regra.
    A versão anterior vigente do mesmo código tem sua vigência encerrada."""
    ctx.require_admin()
    row = _rule(ctx, rule_id)
    if row["status"] != "draft" or row["organization_id"] is None:
        raise Conflict("Apenas rascunhos da organização podem ser publicados")
    if rule_from_row(row).content_hash() != row["content_hash"]:
        raise Conflict("Hash da regra não confere; edite o rascunho novamente")
    fetch_all(
        ctx.conn,
        """update tax_rules set valid_to = :end
            where organization_id = :org and code = :code and status = 'published' and id <> :id
              and (valid_to is null or valid_to >= :start) and valid_from < :start
            returning id""",
        {"org": ctx.org_id, "code": row["code"], "id": rule_id,
         "start": row["valid_from"], "end": row["valid_from"] - timedelta(days=1)},
    )
    return fetch_one(
        ctx.conn,
        """update tax_rules set status = 'published', published_at = now(), validated_by_specialist = :who
            where id = :id returning *""",
        {"id": rule_id, "who": body.validated_by_specialist},
    )


@router.post("/{rule_id}/retire", response_model=TaxRuleOut)
def retire(rule_id: UUID, body: RetireIn, ctx: OrgContext = Depends(get_org)):
    ctx.require_admin()
    row = _rule(ctx, rule_id)
    if row["organization_id"] is None:
        raise Conflict("Regras globais são administradas pela plataforma")
    if row["status"] != "published":
        raise Conflict("Somente regras publicadas podem ser aposentadas")
    return fetch_one(
        ctx.conn,
        "update tax_rules set status = 'retired', valid_to = coalesce(:vt, valid_to, current_date) where id = :id returning *",
        {"id": rule_id, "vt": body.valid_to},
    )


@router.post("/{rule_id}/test")
def test_rule(rule_id: UUID, body: RuleTestIn, ctx: OrgContext = Depends(get_org)):
    """Avalia a regra contra fatos informados (simulação, nada é gravado)."""
    definition = rule_from_row(_rule(ctx, rule_id))
    result = evaluate_rule(definition, body.facts)
    return {
        "matched": result.matched,
        "estimated_amount": str(result.estimated_amount) if result.estimated_amount is not None else None,
        "justification": result.justification,
        "criteria": result.trace,
        "inputs": result.inputs,
    }


@router.post("/validate")
def validate_definition(payload: dict, ctx: OrgContext = Depends(get_org)):
    definition = _parse(payload)
    return {"valid": True, "content_hash": definition.content_hash(), "today": date.today()}
