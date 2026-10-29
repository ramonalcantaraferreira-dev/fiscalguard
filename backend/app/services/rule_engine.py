"""Motor de regras tributárias determinístico.

Regras são dados (JSON), não código: podem ser versionadas, auditadas e
reproduzidas. Cada avaliação produz uma trilha com o resultado de cada
condição, o valor observado e o esperado.

Formato das condições:

    {"all": [cond, ...]} | {"any": [cond, ...]} | {"not": cond}
    {"fact": "item.icms_value", "op": "gt", "value": 0}

Operadores: eq, ne, in, not_in, gt, gte, lt, lte, between, exists,
not_exists, starts_with (prefixo ou lista de prefixos), is_true, is_false.

Estimativas:

    {"type": "field", "fact": "item.icms_value"}
    {"type": "rate", "base": ["item.total_value"], "deduct": ["item.icms_value"], "rate": "0.0925"}
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

FACT_NAMESPACES = ("document", "item", "company", "supplier")
_FACT_RE = re.compile(r"^(document|item|company|supplier)\.[a-z_][a-z0-9_]*$")
_PLACEHOLDER_RE = re.compile(r"\{((?:document|item|company|supplier)\.[a-z_][a-z0-9_]*)\}")

Op = Literal[
    "eq", "ne", "in", "not_in", "gt", "gte", "lt", "lte", "between",
    "exists", "not_exists", "starts_with", "is_true", "is_false",
]
_NUMERIC_OPS = {"gt", "gte", "lt", "lte", "between"}
MAX_DEPTH = 8


class RuleDefinitionError(ValueError):
    pass


# ----------------------------------------------------------------- validação

def _validate_condition(node: Any, depth: int = 0) -> None:
    if depth > MAX_DEPTH:
        raise RuleDefinitionError("Condições aninhadas demais")
    if not isinstance(node, dict):
        raise RuleDefinitionError("Condição deve ser um objeto")
    keys = set(node)
    if keys & {"all", "any"}:
        if len(keys) != 1:
            raise RuleDefinitionError("'all'/'any' não podem ser combinados com outras chaves")
        children = next(iter(node.values()))
        if not isinstance(children, list) or not children:
            raise RuleDefinitionError("'all'/'any' exigem uma lista não vazia")
        for child in children:
            _validate_condition(child, depth + 1)
        return
    if keys == {"not"}:
        _validate_condition(node["not"], depth + 1)
        return
    if not {"fact", "op"} <= keys or keys - {"fact", "op", "value"}:
        raise RuleDefinitionError(f"Condição inválida: {sorted(keys)}")
    if not _FACT_RE.match(str(node["fact"])):
        raise RuleDefinitionError(f"Fato desconhecido: {node['fact']!r}")
    op = node["op"]
    if op not in Op.__args__:  # type: ignore[attr-defined]
        raise RuleDefinitionError(f"Operador desconhecido: {op!r}")
    needs_value = op not in {"exists", "not_exists", "is_true", "is_false"}
    if needs_value and "value" not in node:
        raise RuleDefinitionError(f"Operador {op!r} exige 'value'")
    value = node.get("value")
    if op in {"in", "not_in"} and not isinstance(value, list):
        raise RuleDefinitionError(f"Operador {op!r} exige lista")
    if op == "between" and not (isinstance(value, list) and len(value) == 2):
        raise RuleDefinitionError("'between' exige [mínimo, máximo]")
    if op in _NUMERIC_OPS:
        for v in value if isinstance(value, list) else [value]:
            _to_decimal(v, strict=True)


class EstimateSpec(BaseModel):
    type: Literal["field", "rate"]
    fact: str | None = None
    base: list[str] = Field(default_factory=list)
    deduct: list[str] = Field(default_factory=list)
    rate: Decimal | None = None

    @model_validator(mode="after")
    def _check(self) -> "EstimateSpec":
        facts = ([self.fact] if self.fact else []) + self.base + self.deduct
        for f in facts:
            if not _FACT_RE.match(f):
                raise ValueError(f"Fato desconhecido na estimativa: {f!r}")
        if self.type == "field" and not self.fact:
            raise ValueError("Estimativa 'field' exige 'fact'")
        if self.type == "rate" and (not self.base or self.rate is None):
            raise ValueError("Estimativa 'rate' exige 'base' e 'rate'")
        if self.rate is not None and not (Decimal(0) <= self.rate <= Decimal(1)):
            raise ValueError("'rate' deve estar entre 0 e 1")
        return self


class RuleDefinition(BaseModel):
    """Conteúdo lógico de uma regra (o que entra no hash de versão)."""

    code: str = Field(pattern=r"^[A-Z0-9_.-]{2,64}$")
    name: str = Field(min_length=3, max_length=200)
    description: str | None = None
    tax: str = Field(min_length=2, max_length=40)
    legal_basis: str | None = None
    scope: Literal["item", "document"] = "item"
    conditions: dict[str, Any]
    estimate: EstimateSpec | None = None
    justification_template: str = Field(min_length=10)
    valid_from: date
    valid_to: date | None = None

    @field_validator("conditions")
    @classmethod
    def _conditions(cls, v: dict[str, Any]) -> dict[str, Any]:
        _validate_condition(v)
        return v

    @model_validator(mode="after")
    def _scope_facts(self) -> "RuleDefinition":
        if self.valid_to and self.valid_to < self.valid_from:
            raise ValueError("valid_to anterior a valid_from")
        if self.scope == "document":
            text = json.dumps(self.conditions) + self.justification_template
            if self.estimate:
                text += self.estimate.model_dump_json()
            if '"item.' in text or "{item." in text:
                raise ValueError("Regras de escopo 'document' não podem usar fatos 'item.*'")
        return self

    def content_hash(self) -> str:
        """Hash estável do conteúdo lógico (independe de status e fim de vigência)."""
        payload = self.model_dump(mode="json", exclude={"valid_to"})
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(canonical.encode()).hexdigest()


# ----------------------------------------------------------------- avaliação

def _to_decimal(value: Any, strict: bool = False) -> Decimal | None:
    if value is None or isinstance(value, bool):
        if strict:
            raise RuleDefinitionError(f"Valor numérico inválido: {value!r}")
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        if strict:
            raise RuleDefinitionError(f"Valor numérico inválido: {value!r}") from None
        return None


def _resolve(facts: dict[str, dict[str, Any]], path: str) -> Any:
    namespace, _, key = path.partition(".")
    return (facts.get(namespace) or {}).get(key)


def _norm(value: Any) -> Any:
    """Normaliza para comparação: números como Decimal, demais como string."""
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float, Decimal)):
        return Decimal(str(value))
    return str(value)


def _apply(op: str, actual: Any, expected: Any) -> bool:
    if op == "exists":
        return actual not in (None, "")
    if op == "not_exists":
        return actual in (None, "")
    if op == "is_true":
        return actual is True
    if op == "is_false":
        return actual is False
    if actual is None:
        return op in {"ne", "not_in"}
    if op in _NUMERIC_OPS:
        a = _to_decimal(actual)
        if a is None:
            return False
        if op == "between":
            lo, hi = (_to_decimal(v) for v in expected)
            return lo <= a <= hi
        e = _to_decimal(expected)
        return {"gt": a > e, "gte": a >= e, "lt": a < e, "lte": a <= e}[op]
    if op == "eq":
        return _norm(actual) == _norm(expected)
    if op == "ne":
        return _norm(actual) != _norm(expected)
    if op == "in":
        return _norm(actual) in {_norm(v) for v in expected}
    if op == "not_in":
        return _norm(actual) not in {_norm(v) for v in expected}
    if op == "starts_with":
        prefixes = expected if isinstance(expected, list) else [expected]
        return any(str(actual).startswith(str(p)) for p in prefixes)
    raise RuleDefinitionError(f"Operador desconhecido: {op}")


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    return value


def evaluate_conditions(node: dict[str, Any], facts: dict[str, dict[str, Any]]) -> tuple[bool, dict]:
    """Avalia sem curto-circuito para que a trilha seja completa e reprodutível."""
    if "all" in node or "any" in node:
        kind = "all" if "all" in node else "any"
        results = [evaluate_conditions(child, facts) for child in node[kind]]
        passed = all(r for r, _ in results) if kind == "all" else any(r for r, _ in results)
        return passed, {"group": kind, "result": passed, "children": [t for _, t in results]}
    if "not" in node:
        inner, trace = evaluate_conditions(node["not"], facts)
        return not inner, {"group": "not", "result": not inner, "children": [trace]}
    actual = _resolve(facts, node["fact"])
    passed = _apply(node["op"], actual, node.get("value"))
    return passed, {
        "fact": node["fact"],
        "op": node["op"],
        "expected": node.get("value"),
        "actual": _jsonable(actual),
        "result": passed,
    }


def compute_estimate(spec: EstimateSpec | None, facts: dict[str, dict[str, Any]]) -> Decimal | None:
    if spec is None:
        return None
    if spec.type == "field":
        value = _to_decimal(_resolve(facts, spec.fact or ""))
    else:
        base = sum((_to_decimal(_resolve(facts, f)) or Decimal(0) for f in spec.base), Decimal(0))
        base -= sum((_to_decimal(_resolve(facts, f)) or Decimal(0) for f in spec.deduct), Decimal(0))
        value = max(base, Decimal(0)) * (spec.rate or Decimal(0))
    if value is None:
        return None
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def render_justification(template: str, facts: dict[str, dict[str, Any]]) -> str:
    def repl(match: re.Match[str]) -> str:
        value = _resolve(facts, match.group(1))
        if value is None:
            return "—"
        if isinstance(value, Decimal):
            return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        return str(value)

    return _PLACEHOLDER_RE.sub(repl, template)


@dataclass
class RuleResult:
    matched: bool
    trace: dict
    estimated_amount: Decimal | None = None
    justification: str | None = None
    inputs: dict[str, Any] = field(default_factory=dict)


def _referenced_facts(rule: RuleDefinition) -> set[str]:
    blob = json.dumps(rule.conditions) + rule.justification_template
    if rule.estimate:
        blob += rule.estimate.model_dump_json()
    return set(re.findall(r"(?:document|item|company|supplier)\.[a-z_][a-z0-9_]*", blob))


def evaluate_rule(rule: RuleDefinition, facts: dict[str, dict[str, Any]]) -> RuleResult:
    matched, trace = evaluate_conditions(rule.conditions, facts)
    # Snapshot apenas dos fatos referenciados: suficiente para reproduzir a análise.
    inputs = {f: _jsonable(_resolve(facts, f)) for f in sorted(_referenced_facts(rule))}
    if not matched:
        return RuleResult(False, trace, inputs=inputs)
    return RuleResult(
        matched=True,
        trace=trace,
        estimated_amount=compute_estimate(rule.estimate, facts),
        justification=render_justification(rule.justification_template, facts),
        inputs=inputs,
    )
