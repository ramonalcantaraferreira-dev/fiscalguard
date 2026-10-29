"""Compliance de fornecedores: status consolidado, vencimentos e alertas."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy import Connection, text

from app.db import fetch_all

# Validade usual quando a certidão não informa a data (ajustável pelo especialista).
DEFAULT_VALIDITY_DAYS = {
    "cnd_federal": 180,
    "crf_fgts": 30,
    "cndt": 180,
    "cnd_estadual": 60,
    "cnd_municipal": 60,
    "cadastro_cnpj": 30,
    "sintegra": 30,
}

CHECK_LABELS = {
    "cadastro_cnpj": "Situação cadastral do CNPJ",
    "cnd_federal": "CND Federal (RFB/PGFN)",
    "crf_fgts": "CRF do FGTS",
    "cndt": "CNDT (Justiça do Trabalho)",
    "cnd_estadual": "CND Estadual",
    "cnd_municipal": "CND Municipal",
    "sintegra": "Sintegra",
    "outro": "Outra verificação",
}


def default_valid_until(check_type: str, issued_at: date | None, result: str) -> date | None:
    if result != "regular" or check_type not in DEFAULT_VALIDITY_DAYS:
        return None
    return (issued_at or date.today()) + timedelta(days=DEFAULT_VALIDITY_DAYS[check_type])


def evaluate_status(latest: dict[str, dict], required: list[str], today: date) -> tuple[str, list[dict]]:
    """Calcula o status consolidado e a lista de pendências a partir da última verificação de cada tipo."""
    findings: list[dict] = []
    for check_type in sorted(set(required) | set(latest)):
        check = latest.get(check_type)
        if check is None:
            findings.append({"check_type": check_type, "kind": "missing"})
            continue
        result, valid_until = check["result"], check["valid_until"]
        if result == "irregular":
            findings.append({"check_type": check_type, "kind": "irregular"})
        elif result in ("pending", "not_found", "error"):
            findings.append({"check_type": check_type, "kind": "pending"})
        elif valid_until is not None and valid_until < today:
            findings.append({"check_type": check_type, "kind": "expired", "valid_until": valid_until})
        elif valid_until is not None:
            findings.append({"check_type": check_type, "kind": "valid", "valid_until": valid_until})

    kinds = {f["kind"] for f in findings if f["check_type"] in required or f["kind"] == "irregular"}
    if "irregular" in kinds:
        status = "irregular"
    elif "expired" in kinds:
        status = "expired"
    elif kinds & {"missing", "pending"}:
        status = "pending"
    else:
        status = "regular"
    return status, findings


def latest_checks(conn: Connection, org_id: str, supplier_id: str | None = None) -> dict[str, dict[str, dict]]:
    rows = fetch_all(
        conn,
        """
        select distinct on (supplier_id, check_type)
               supplier_id, check_type::text, result::text, valid_until, checked_at
          from compliance_checks
         where organization_id = :org and (cast(:sid as uuid) is null or supplier_id = cast(:sid as uuid))
         order by supplier_id, check_type, checked_at desc, created_at desc
        """,
        {"org": org_id, "sid": supplier_id},
    )
    out: dict[str, dict[str, dict]] = {}
    for r in rows:
        out.setdefault(str(r["supplier_id"]), {})[r["check_type"]] = r
    return out


def _upsert_alert(conn: Connection, org_id: str, supplier: dict, finding: dict, warning_days: int, today: date) -> str | None:
    kind, check_type = finding["kind"], finding["check_type"]
    label = CHECK_LABELS.get(check_type, check_type)
    name = supplier["legal_name"]
    due = finding.get("valid_until")
    if kind == "irregular":
        severity, title = "critical", f"{label} irregular — {name}"
    elif kind == "expired":
        severity, title = "critical", f"{label} vencida — {name}"
    elif kind == "valid" and due is not None and due <= today + timedelta(days=warning_days):
        severity, title, kind = "warning", f"{label} vence em {(due - today).days} dia(s) — {name}", "expiring"
    elif kind in ("missing", "pending"):
        severity, title = "info", f"{label} pendente — {name}"
    else:
        return None
    key = f"compliance:{supplier['id']}:{check_type}:{kind}"
    conn.execute(
        text(
            """
            insert into alerts (organization_id, supplier_id, kind, severity, title, due_date, dedupe_key, message)
            values (:org, :sid, :kind, :sev, :title, :due, :key, :msg)
            on conflict (organization_id, dedupe_key) where status <> 'resolved'
            do update set title = excluded.title, severity = excluded.severity, due_date = excluded.due_date
            """
        ),
        {"org": org_id, "sid": str(supplier["id"]), "kind": f"compliance_{kind}", "sev": severity,
         "title": title, "due": due, "key": key, "msg": f"CNPJ {supplier['cnpj']}"},
    )
    return key


def scan_compliance(
    conn: Connection, org_id: str, required: list[str], warning_days: int, today: date | None = None,
    supplier_id: str | None = None,
) -> dict[str, Any]:
    """Recalcula status de fornecedores e sincroniza alertas (cria, atualiza e resolve)."""
    today = today or date.today()
    suppliers = fetch_all(
        conn,
        """select id, cnpj, legal_name, compliance_status::text as status from suppliers
            where organization_id = :org and (cast(:sid as uuid) is null or id = cast(:sid as uuid))""",
        {"org": org_id, "sid": supplier_id},
    )
    checks = latest_checks(conn, org_id, supplier_id)
    changed = 0
    active_keys: list[str] = []
    for s in suppliers:
        status, findings = evaluate_status(checks.get(str(s["id"]), {}), required, today)
        if status != s["status"]:
            changed += 1
            conn.execute(
                text("""update suppliers set compliance_status = :st, compliance_updated_at = now()
                         where id = :id"""),
                {"st": status, "id": str(s["id"])},
            )
        for f in findings:
            if f["kind"] == "missing" and f["check_type"] not in required:
                continue
            key = _upsert_alert(conn, org_id, s, f, warning_days, today)
            if key:
                active_keys.append(key)

    ids = [str(s["id"]) for s in suppliers]
    resolved = 0
    if ids:
        resolved = conn.execute(
            text(
                """
                update alerts set status = 'resolved', resolved_at = now()
                 where organization_id = :org and status <> 'resolved'
                   and dedupe_key like 'compliance:%'
                   and cast(supplier_id as text) = any(:ids)
                   and not (dedupe_key = any(:keys))
                """
            ),
            {"org": org_id, "ids": ids, "keys": active_keys},
        ).rowcount
    return {"suppliers": len(suppliers), "status_changed": changed,
            "active_alerts": len(active_keys), "resolved_alerts": resolved}
