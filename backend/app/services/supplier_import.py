"""Importação de fornecedores via CSV (idempotente: upsert por CNPJ)."""

from __future__ import annotations

import csv
import io
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Connection

from app.db import fetch_all, fetch_one, fetch_value
from app.domain.documents import is_valid_cnpj, normalize_cnpj

UFS = {
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG", "PA", "PB",
    "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO",
}

_HEADER_ALIASES = {
    "cnpj": "cnpj",
    "razao_social": "legal_name", "razao": "legal_name", "nome": "legal_name", "legal_name": "legal_name",
    "nome_fantasia": "trade_name", "fantasia": "trade_name", "trade_name": "trade_name",
    "uf": "uf", "estado": "uf",
    "regime": "tax_regime", "regime_tributario": "tax_regime", "tax_regime": "tax_regime",
    "email": "email", "e_mail": "email",
    "telefone": "phone", "fone": "phone", "phone": "phone",
    "empresas": "companies", "empresas_cnpj": "companies", "companies": "companies",
}

_REGIME_ALIASES = {
    "simples": "simples_nacional", "simples nacional": "simples_nacional", "simples_nacional": "simples_nacional",
    "mei": "mei",
    "presumido": "lucro_presumido", "lucro presumido": "lucro_presumido", "lucro_presumido": "lucro_presumido",
    "real": "lucro_real", "lucro real": "lucro_real", "lucro_real": "lucro_real",
    "outro": "outro",
}


def _slug(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return "_".join(value.strip().lower().replace("-", " ").split())


def decode_csv(content: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("Codificação do arquivo não reconhecida (use UTF-8)")


@dataclass
class RowError:
    line: int
    errors: list[str]


@dataclass
class ImportReport:
    total: int = 0
    created: int = 0
    updated: int = 0
    linked: int = 0
    errors: list[RowError] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "total": self.total, "created": self.created, "updated": self.updated,
            "linked": self.linked, "rejected": len(self.errors),
            "errors": [{"line": e.line, "errors": e.errors} for e in self.errors],
        }


def parse_rows(text_content: str, max_rows: int) -> tuple[list[tuple[int, dict]], list[str]]:
    sample = text_content[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        delimiter = ";" if sample.count(";") > sample.count(",") else ","
        dialect = type("FallbackDialect", (csv.excel,), {"delimiter": delimiter})
    reader = csv.DictReader(io.StringIO(text_content), dialect=dialect)
    if not reader.fieldnames:
        return [], ["Arquivo vazio"]
    mapping = {name: _HEADER_ALIASES.get(_slug(name)) for name in reader.fieldnames}
    if "cnpj" not in mapping.values() or "legal_name" not in mapping.values():
        return [], ["Colunas obrigatórias: cnpj e razao_social"]
    rows: list[tuple[int, dict]] = []
    for line, raw in enumerate(reader, start=2):
        if len(rows) >= max_rows:
            return rows, [f"Limite de {max_rows} linhas excedido"]
        row = {mapping[k]: (v or "").strip() for k, v in raw.items() if k and mapping.get(k)}
        if any(row.values()):
            rows.append((line, row))
    return rows, []


def validate_row(row: dict) -> tuple[dict | None, list[str]]:
    errors: list[str] = []
    cnpj = normalize_cnpj(row.get("cnpj"))
    if not is_valid_cnpj(cnpj):
        errors.append("CNPJ inválido")
    legal_name = row.get("legal_name") or ""
    if len(legal_name) < 2:
        errors.append("Razão social obrigatória")
    uf = (row.get("uf") or "").upper() or None
    if uf and uf not in UFS:
        errors.append(f"UF inválida: {uf}")
    regime = None
    if row.get("tax_regime"):
        regime = _REGIME_ALIASES.get(row["tax_regime"].strip().lower())
        if regime is None:
            errors.append(f"Regime tributário desconhecido: {row['tax_regime']}")
    if errors:
        return None, errors
    companies = [normalize_cnpj(c) for c in (row.get("companies") or "").replace(",", "|").replace(";", "|").split("|") if c.strip()]
    return {
        "cnpj": cnpj, "legal_name": legal_name[:300], "trade_name": row.get("trade_name") or None,
        "uf": uf, "tax_regime": regime, "email": row.get("email") or None,
        "phone": row.get("phone") or None, "companies": companies,
    }, []


def import_suppliers_csv(conn: Connection, org_id: str, content: bytes, max_rows: int) -> ImportReport:
    report = ImportReport()
    rows, fatal = parse_rows(decode_csv(content), max_rows)
    if fatal:
        report.errors.append(RowError(1, fatal))
        if not rows:
            return report

    companies = {
        c["cnpj"]: c for c in fetch_all(
            conn,
            """select id, cnpj, app.can_write_company(id) as writable
                 from client_companies where organization_id = :org""",
            {"org": org_id},
        )
    }
    seen: set[str] = set()
    for line, raw in rows:
        report.total += 1
        data, errors = validate_row(raw)
        if data and data["cnpj"] in seen:
            errors = ["CNPJ repetido no arquivo"]
        unknown = [c for c in (data or {}).get("companies", []) if c not in companies]
        if unknown:
            errors.append("Empresa(s) não encontrada(s): " + ", ".join(unknown))
        if errors or data is None:
            report.errors.append(RowError(line, errors))
            continue
        seen.add(data["cnpj"])
        with conn.begin_nested():
            result = fetch_one(
                conn,
                """
                insert into suppliers (organization_id, cnpj, legal_name, trade_name, uf, tax_regime, email, phone)
                values (:org, :cnpj, :legal_name, :trade_name, :uf, :tax_regime, :email, :phone)
                on conflict (organization_id, cnpj) do update set
                  legal_name = excluded.legal_name,
                  trade_name = coalesce(excluded.trade_name, suppliers.trade_name),
                  uf = coalesce(excluded.uf, suppliers.uf),
                  tax_regime = coalesce(excluded.tax_regime, suppliers.tax_regime),
                  email = coalesce(excluded.email, suppliers.email),
                  phone = coalesce(excluded.phone, suppliers.phone)
                returning id, (xmax = 0) as inserted
                """,
                {"org": org_id, **{k: v for k, v in data.items() if k != "companies"}},
            )
            if result["inserted"]:
                report.created += 1
            else:
                report.updated += 1
            for cnpj in data["companies"]:
                if not companies[cnpj]["writable"]:
                    report.errors.append(RowError(line, [f"Sem permissão para vincular à empresa {cnpj}"]))
                    continue
                linked = fetch_value(
                    conn,
                    """insert into supplier_company_links (organization_id, supplier_id, company_id)
                       values (:org, :s, :c) on conflict (supplier_id, company_id) do nothing returning id""",
                    {"org": org_id, "s": result["id"], "c": companies[cnpj]["id"]},
                )
                report.linked += 1 if linked else 0
    return report
