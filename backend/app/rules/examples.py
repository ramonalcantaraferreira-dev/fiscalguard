"""Regras de EXEMPLO para desenvolvimento e demonstração.

ATENÇÃO: estas regras ilustram o formato do motor e NÃO foram validadas por
especialista tributário. Antes de qualquer uso real, um especialista deve
revisar critérios, base legal e vigência, e registrar a validação em
`validated_by_specialist` ao publicar uma nova versão.
"""

from datetime import date

from app.services.rule_engine import RuleDefinition

_PURCHASE_CFOPS = ["5101", "5102", "6101", "6102"]  # venda de produção / de mercadoria adquirida

EXAMPLE_RULES: list[RuleDefinition] = [
    RuleDefinition(
        code="EX.ICMS_CREDITO_AQUISICAO",
        name="[EXEMPLO] ICMS destacado em aquisição de mercadoria",
        description="Item adquirido com ICMS destacado por empresa fora do Simples Nacional.",
        tax="ICMS",
        legal_basis="LC 87/1996, arts. 19 a 21 (não cumulatividade). Confirmar destinação "
                    "(revenda, industrialização ou ativo) e a legislação da UF.",
        scope="item",
        conditions={"all": [
            {"fact": "document.direction", "op": "eq", "value": "inbound"},
            {"fact": "document.status", "op": "eq", "value": "validated"},
            {"fact": "company.tax_regime", "op": "in", "value": ["lucro_real", "lucro_presumido"]},
            {"fact": "item.cfop", "op": "starts_with", "value": _PURCHASE_CFOPS},
            {"fact": "item.icms_value", "op": "gt", "value": 0},
        ]},
        estimate={"type": "field", "fact": "item.icms_value"},
        justification_template=(
            "Item {item.item_number} ({item.description}) adquirido de {document.issuer_name} "
            "com ICMS destacado de R$ {item.icms_value} (CFOP {item.cfop}, CST {item.icms_cst}). "
            "Empresa no regime {company.tax_regime}. Potencial crédito sujeito à confirmação da "
            "destinação da mercadoria e de eventual escrituração anterior."
        ),
        valid_from=date(2020, 1, 1),
    ),
    RuleDefinition(
        code="EX.PIS_COFINS_NAO_CUMULATIVO",
        name="[EXEMPLO] PIS/COFINS não cumulativo sobre aquisições",
        description="Aquisição tributada por empresa do Lucro Real; base sem o ICMS destacado.",
        tax="PIS/COFINS",
        legal_basis="Leis 10.637/2002 e 10.833/2003, art. 3º; conceito de insumo (STJ, REsp "
                    "1.221.170/PR); exclusão do ICMS da base do crédito (Lei 14.592/2023).",
        scope="item",
        conditions={"all": [
            {"fact": "document.direction", "op": "eq", "value": "inbound"},
            {"fact": "document.status", "op": "eq", "value": "validated"},
            {"fact": "company.tax_regime", "op": "eq", "value": "lucro_real"},
            {"fact": "item.cfop", "op": "starts_with", "value": _PURCHASE_CFOPS},
            {"fact": "item.total_value", "op": "gt", "value": 0},
            # CSTs de saída que tipicamente indicam monofásico, ST, alíquota zero, isenção etc.
            {"fact": "item.pis_cst", "op": "not_in", "value": ["04", "05", "06", "07", "08", "09"]},
        ]},
        estimate={
            "type": "rate",
            "base": ["item.total_value"],
            "deduct": ["item.discount", "item.icms_value"],
            "rate": "0.0925",
        },
        justification_template=(
            "Item {item.item_number} ({item.description}, NCM {item.ncm}) adquirido por empresa no "
            "Lucro Real, CST PIS {item.pis_cst} no documento do fornecedor. Estimativa de 9,25% sobre "
            "o valor do item deduzidos desconto e ICMS. Requer análise de essencialidade/relevância "
            "como insumo ou confirmação de aquisição para revenda."
        ),
        valid_from=date(2023, 5, 1),
    ),
    RuleDefinition(
        code="EX.IPI_CREDITO_INDUSTRIAL",
        name="[EXEMPLO] IPI destacado em aquisição por estabelecimento industrial",
        tax="IPI",
        legal_basis="RIPI (Decreto 7.212/2010), arts. 225 e 226. Confirmar emprego no processo produtivo.",
        scope="item",
        conditions={"all": [
            {"fact": "document.direction", "op": "eq", "value": "inbound"},
            {"fact": "document.status", "op": "eq", "value": "validated"},
            {"fact": "company.is_industrial", "op": "is_true"},
            {"fact": "item.ipi_value", "op": "gt", "value": 0},
        ]},
        estimate={"type": "field", "fact": "item.ipi_value"},
        justification_template=(
            "Item {item.item_number} ({item.description}) com IPI destacado de R$ {item.ipi_value} "
            "adquirido por estabelecimento industrial. Potencial crédito se empregado como matéria-prima, "
            "produto intermediário ou material de embalagem."
        ),
        valid_from=date(2020, 1, 1),
    ),
    RuleDefinition(
        code="EX.RISCO_FORNECEDOR_IRREGULAR",
        name="[EXEMPLO] Documento de fornecedor com compliance irregular",
        description="Sinaliza risco sobre créditos de documentos emitidos por fornecedor irregular.",
        tax="RISCO",
        legal_basis="Diligência na aquisição; boa-fé do adquirente (STJ, Súmula 509).",
        scope="document",
        conditions={"all": [
            {"fact": "document.direction", "op": "eq", "value": "inbound"},
            {"fact": "supplier.compliance_status", "op": "in", "value": ["irregular", "expired"]},
        ]},
        justification_template=(
            "Fornecedor {document.issuer_name} (CNPJ {document.issuer_cnpj}) está com status de "
            "compliance '{supplier.compliance_status}'. Créditos deste documento devem ser revisados "
            "com evidências de diligência."
        ),
        valid_from=date(2020, 1, 1),
    ),
]
