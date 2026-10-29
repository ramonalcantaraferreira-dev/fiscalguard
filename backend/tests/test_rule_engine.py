from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.rules.examples import EXAMPLE_RULES
from app.services.rule_engine import RuleDefinition, evaluate_rule


def _rule(**overrides) -> RuleDefinition:
    base = dict(
        code="T.RULE", name="Regra de teste", tax="ICMS", scope="item",
        conditions={"all": [
            {"fact": "item.icms_value", "op": "gt", "value": 0},
            {"fact": "company.tax_regime", "op": "in", "value": ["lucro_real"]},
            {"not": {"fact": "item.cfop", "op": "starts_with", "value": ["59", "69"]}},
        ]},
        estimate={"type": "field", "fact": "item.icms_value"},
        justification_template="Item {item.item_number} com ICMS R$ {item.icms_value}",
        valid_from=date(2024, 1, 1),
    )
    base.update(overrides)
    return RuleDefinition.model_validate(base)


FACTS = {
    "document": {"direction": "inbound", "status": "validated"},
    "company": {"tax_regime": "lucro_real", "is_industrial": True},
    "supplier": {"compliance_status": "regular"},
    "item": {"item_number": 1, "icms_value": Decimal("1234.5"), "cfop": "5102",
             "total_value": Decimal("1000"), "discount": Decimal("0")},
}


def test_match_with_trace_and_estimate():
    result = evaluate_rule(_rule(), FACTS)
    assert result.matched
    assert result.estimated_amount == Decimal("1234.50")
    assert result.justification == "Item 1 com ICMS R$ 1.234,50"
    assert result.trace["group"] == "all" and len(result.trace["children"]) == 3
    assert result.inputs["item.icms_value"] == "1234.5"


def test_no_match_keeps_full_trace():
    facts = {**FACTS, "company": {"tax_regime": "simples_nacional"}}
    result = evaluate_rule(_rule(), facts)
    assert not result.matched
    leaves = result.trace["children"]
    assert leaves[0]["result"] is True and leaves[1]["result"] is False
    assert leaves[1]["actual"] == "simples_nacional"
    assert result.estimated_amount is None


def test_rate_estimate_with_deductions():
    rule = _rule(estimate={"type": "rate", "base": ["item.total_value"],
                           "deduct": ["item.icms_value"], "rate": "0.0925"},
                 conditions={"fact": "item.total_value", "op": "gt", "value": 0})
    facts = {**FACTS, "item": {**FACTS["item"], "icms_value": Decimal("180")}}
    assert evaluate_rule(rule, facts).estimated_amount == Decimal("75.85")  # (1000-180) * 9,25%


def test_missing_fact_is_false_not_error():
    rule = _rule(conditions={"fact": "item.ipi_value", "op": "gt", "value": 0})
    assert not evaluate_rule(rule, FACTS).matched


@pytest.mark.parametrize("conditions", [
    {"fact": "item.x", "op": "regex", "value": ".*"},           # operador desconhecido
    {"fact": "os.system", "op": "eq", "value": 1},               # fato fora dos namespaces
    {"fact": "item.icms_value", "op": "gt"},                     # sem valor
    {"fact": "item.icms_value", "op": "gt", "value": "abc"},     # valor não numérico
    {"fact": "item.cfop", "op": "in", "value": "5102"},          # 'in' exige lista
    {"all": []},                                                  # grupo vazio
])
def test_invalid_definitions(conditions):
    with pytest.raises((ValidationError, ValueError)):
        _rule(conditions=conditions)


def test_document_scope_cannot_use_item_facts():
    with pytest.raises(ValidationError):
        _rule(scope="document", estimate=None)


def test_hash_is_stable_and_sensitive():
    a, b = _rule(), _rule()
    assert a.content_hash() == b.content_hash()
    assert _rule(valid_to=date(2030, 1, 1)).content_hash() == a.content_hash()  # fim de vigência não altera
    changed = _rule(conditions={"fact": "item.icms_value", "op": "gt", "value": 1})
    assert changed.content_hash() != a.content_hash()


def test_example_rules_are_valid():
    codes = {r.code for r in EXAMPLE_RULES}
    assert len(codes) == len(EXAMPLE_RULES)
    for rule in EXAMPLE_RULES:
        assert rule.name.startswith("[EXEMPLO]")
