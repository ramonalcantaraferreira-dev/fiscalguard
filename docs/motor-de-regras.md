# Motor de regras tributárias

Implementação: `backend/app/services/rule_engine.py` (avaliação pura) e
`backend/app/services/analysis.py` (aplicação aos documentos).

## Princípios

1. **Determinístico** — mesmas entradas e mesma versão de regra produzem o mesmo resultado.
2. **Declarativo** — regras são JSON validado; não há código executável nem regex (sem risco de injeção/ReDoS).
3. **Versionado e imutável** — publicar exige o registro do especialista que validou; alterações criam nova versão.
4. **Reprodutível** — cada resultado guarda versão, hash do conteúdo da regra, fatos usados e trilha de cada condição.
5. **Revisão humana obrigatória** — resultados nascem `pending_review`.

## Estrutura de uma regra

```json
{
  "code": "ESC.ICMS_INSUMOS",
  "name": "ICMS sobre insumos industriais",
  "tax": "ICMS",
  "legal_basis": "LC 87/1996, art. 20; RICMS/UF ...",
  "scope": "item",
  "valid_from": "2026-01-01",
  "valid_to": null,
  "conditions": {"all": [
    {"fact": "document.direction", "op": "eq", "value": "inbound"},
    {"fact": "document.status", "op": "eq", "value": "validated"},
    {"fact": "company.tax_regime", "op": "in", "value": ["lucro_real", "lucro_presumido"]},
    {"fact": "item.cfop", "op": "starts_with", "value": ["5101", "6101"]},
    {"fact": "item.icms_value", "op": "gt", "value": 0},
    {"not": {"fact": "item.ncm", "op": "starts_with", "value": ["2710"]}}
  ]},
  "estimate": {"type": "field", "fact": "item.icms_value"},
  "justification_template": "Item {item.item_number} ({item.description}) com ICMS de R$ {item.icms_value}."
}
```

### Fatos disponíveis

| Namespace | Origem |
|---|---|
| `document.*` | colunas de `fiscal_documents` (`direction`, `status`, `issuer_cnpj`, `issuer_crt`, `total_*`, …) |
| `item.*` | colunas de `fiscal_document_items` (`cfop`, `ncm`, `icms_cst`, `icms_value`, `pis_cst`, `ipi_value`, …) — apenas `scope: "item"` |
| `company.*` | colunas de `client_companies` (`tax_regime`, `is_industrial`, `uf`, …) |
| `supplier.*` | colunas de `suppliers` (`compliance_status`, `tax_regime`, …) |

### Operadores

`eq`, `ne`, `in`, `not_in`, `gt`, `gte`, `lt`, `lte`, `between`, `exists`,
`not_exists`, `starts_with` (texto ou lista de prefixos), `is_true`, `is_false`.
Agrupadores: `all`, `any`, `not` (até 8 níveis). Fato ausente nunca gera erro: a
condição é falsa (exceto `ne`/`not_in`/`not_exists`).

### Estimativas

- `{"type": "field", "fact": "item.icms_value"}` — valor destacado.
- `{"type": "rate", "base": ["item.total_value"], "deduct": ["item.discount", "item.icms_value"], "rate": "0.0925"}` — alíquota sobre base (nunca negativa).

## Ciclo de vida

```
rascunho ──(PATCH edita)──► rascunho ──(publish + especialista)──► publicada ──(retire)──► aposentada
                                                        │
                                       nova versão ◄────┘ (POST /tax-rules/{id}/versions)
```

- Ao publicar, a versão anterior do mesmo código (da organização) tem a vigência encerrada no dia anterior ao início da nova.
- Para cada documento, vale a regra **vigente na data de emissão**; regra da organização com o mesmo código substitui a global.
- O hash é recalculado ao carregar a regra; se divergir do gravado, a regra é ignorada e o fato é registrado em log.
- `POST /tax-rules/{id}/test` simula a regra contra fatos informados, sem gravar nada.
- `POST /companies/{id}/reanalyze` reaplica as regras vigentes a todos os documentos (assíncrono).

## Regras de exemplo

`backend/app/rules/examples.py` contém quatro regras **[EXEMPLO]** (ICMS em
aquisições, PIS/COFINS não cumulativo, IPI para indústria e risco por fornecedor
irregular). Elas ilustram o formato e **não foram validadas por especialista**.
Para uso real, crie versões da organização a partir delas, ajuste critérios e
base legal, e publique informando o especialista responsável.
