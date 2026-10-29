from datetime import date

from app.services.compliance import evaluate_status
from app.services.supplier_import import decode_csv, parse_rows, validate_row

TODAY = date(2026, 10, 29)
REQUIRED = ["cnd_federal", "crf_fgts"]


def _check(result="regular", valid_until=date(2026, 12, 31)):
    return {"result": result, "valid_until": valid_until}


def test_all_regular():
    status, _ = evaluate_status({"cnd_federal": _check(), "crf_fgts": _check()}, REQUIRED, TODAY)
    assert status == "regular"


def test_missing_required_is_pending():
    status, findings = evaluate_status({"cnd_federal": _check()}, REQUIRED, TODAY)
    assert status == "pending"
    assert {"check_type": "crf_fgts", "kind": "missing"} in findings


def test_expired_and_irregular_precedence():
    expired = {"cnd_federal": _check(valid_until=date(2026, 10, 1)), "crf_fgts": _check()}
    assert evaluate_status(expired, REQUIRED, TODAY)[0] == "expired"
    irregular = {**expired, "crf_fgts": _check("irregular")}
    assert evaluate_status(irregular, REQUIRED, TODAY)[0] == "irregular"


def test_optional_irregular_check_still_counts():
    checks = {"cnd_federal": _check(), "crf_fgts": _check(), "cnd_municipal": _check("irregular")}
    assert evaluate_status(checks, REQUIRED, TODAY)[0] == "irregular"


def test_csv_semicolon_latin1_and_aliases():
    raw = "CNPJ;Razão Social;UF;Regime\n11.222.333/0001-81;Fornecedor Ação;sp;Lucro Real\n".encode("cp1252")
    rows, fatal = parse_rows(decode_csv(raw), 100)
    assert not fatal and len(rows) == 1
    line, row = rows[0]
    data, errors = validate_row(row)
    assert line == 2 and not errors
    assert data["cnpj"] == "11222333000181"
    assert data["legal_name"] == "Fornecedor Ação"
    assert data["uf"] == "SP" and data["tax_regime"] == "lucro_real"


def test_csv_row_errors_and_missing_columns():
    rows, _ = parse_rows("cnpj,razao_social,uf\n123,X,ZZ\n", 100)
    _, errors = validate_row(rows[0][1])
    assert "CNPJ inválido" in errors and any("UF" in e for e in errors)
    _, fatal = parse_rows("nome,uf\nA,SP\n", 100)
    assert fatal
