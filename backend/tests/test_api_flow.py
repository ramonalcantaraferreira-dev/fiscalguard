"""Fluxo ponta a ponta: empresa → fornecedores → compliance → NF-e → oportunidades → revisão."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import text

from app.db import fetch_value, service_connection
from app.services import jobs
from tests.factories import build_nfe, make_cnpj, nfe_item

SUPPLIER = make_cnpj("550000000001")


@pytest.fixture
def setup(client, make_user):
    admin = make_user("admin")
    h = admin.headers
    org = client.post("/api/v1/organizations", json={"name": "Contábil Fluxo"}, headers=h).json()["id"]
    company = client.post(f"/api/v1/organizations/{org}/companies", headers=h, json={
        "legal_name": "Indústria Compradora SA", "cnpj": make_cnpj("660000000001"),
        "tax_regime": "lucro_real", "is_industrial": True, "uf": "SP",
    }).json()
    return {"h": h, "org": org, "company": company, "base": f"/api/v1/organizations/{org}", "admin": admin}


def _import(client, s, *xmls, async_=False):
    files = [("files", (f"nf{i}.xml", x, "application/xml")) for i, x in enumerate(xmls)]
    url = f"{s['base']}/companies/{s['company']['id']}/fiscal-documents/import"
    return client.post(url, files=files, headers=s["h"], params={"async": str(async_).lower()})


def test_nfe_import_analysis_and_review(client, setup):
    s = setup
    xml = build_nfe(SUPPLIER, s["company"]["cnpj"], number=1, items=[
        nfe_item(1, "1000.00", icms="180.00", ipi="100.00"),
        nfe_item(2, "200.00", icms=None, pis_cst="04"),  # monofásico: sem PIS/COFINS, sem ICMS
    ])
    r = _import(client, s, xml)
    assert r.status_code == 200, r.text
    job = r.json()
    assert job["status"] == "succeeded"
    file_result = job["result"]["files"][0]
    assert file_result["status"] == "imported" and file_result["direction"] == "inbound"
    doc_id = file_result["document_id"]

    # Idempotência: mesmo arquivo de novo → mesma tarefa; outro lote com a mesma NF-e → duplicate.
    assert _import(client, s, xml).json()["id"] == job["id"]
    other = _import(client, s, xml, build_nfe(SUPPLIER, s["company"]["cnpj"], number=2))
    statuses = sorted(f["status"] for f in other.json()["result"]["files"])
    assert statuses == ["duplicate", "imported"]

    # Fornecedor criado automaticamente e vinculado à empresa.
    sups = client.get(f"{s['base']}/suppliers", headers=s["h"], params={"company_id": s["company"]["id"]}).json()
    assert [x["cnpj"] for x in sups] == [SUPPLIER]

    detail = client.get(f"{s['base']}/fiscal-documents/{doc_id}", headers=s["h"]).json()
    assert len(detail["items"]) == 2 and detail["status"] == "validated"

    found = client.get(f"{s['base']}/assessments", headers=s["h"], params={"document_id": doc_id}).json()
    by_rule = {(a["rule_code"], a["item_id"] is not None): a for a in found}
    icms = by_rule[("EX.ICMS_CREDITO_AQUISICAO", True)]
    assert icms["estimated_amount"] == "180.00"
    assert icms["review_status"] == "pending_review"
    assert icms["criteria"]["result"] is True and icms["justification"].startswith("Item 1")
    assert by_rule[("EX.IPI_CREDITO_INDUSTRIAL", True)]["estimated_amount"] == "100.00"
    pis = [a for a in found if a["rule_code"] == "EX.PIS_COFINS_NAO_CUMULATIVO"]
    assert len(pis) == 1 and pis[0]["estimated_amount"] == "75.85"  # (1000 - 180) * 9,25%; item 2 excluído

    # Revisão humana e reprocessamento não sobrescreve o que foi revisado.
    r = client.patch(f"{s['base']}/assessments/{icms['id']}/review", headers=s["h"],
                     json={"review_status": "approved", "review_notes": "Mercadoria para industrialização"})
    assert r.status_code == 200 and r.json()["review_status"] == "approved"
    client.patch(f"{s['base']}/companies/{s['company']['id']}", headers=s["h"], json={"tax_regime": "simples_nacional"})
    rerun = client.post(f"{s['base']}/fiscal-documents/{doc_id}/analyze", headers=s["h"]).json()
    assert rerun["stale_removed"] == 1  # PIS/COFINS pendente deixa de se aplicar; ICMS aprovado é preservado
    after = client.get(f"{s['base']}/assessments", headers=s["h"], params={"document_id": doc_id}).json()
    kept = {a["rule_code"]: a["review_status"] for a in after}
    assert kept["EX.ICMS_CREDITO_AQUISICAO"] == "approved"
    assert "EX.PIS_COFINS_NAO_CUMULATIVO" not in kept

    # Exportação CSV e trilha de auditoria da revisão.
    csv = client.get(f"{s['base']}/assessments/export", headers=s["h"])
    assert csv.status_code == 200 and "EX.ICMS_CREDITO_AQUISICAO" in csv.text
    audit = client.get(f"{s['base']}/audit-events", headers=s["h"],
                       params={"entity_type": "tax_assessments", "entity_id": icms["id"]}).json()
    assert any(e["action"] == "update" and e["after"]["review_status"] == "approved" for e in audit)


def test_rejects_foreign_and_broken_xml(client, setup):
    s = setup
    foreign = build_nfe(SUPPLIER, make_cnpj("770000000001"), number=9)
    r = _import(client, s, foreign, b"<not-xml")
    results = {f["file"]: f for f in r.json()["result"]["files"]}
    assert results["nf0.xml"]["errors"][0]["code"] == "not_company_document"
    assert results["nf1.xml"]["status"] == "rejected"

    bad_total = build_nfe(SUPPLIER, s["company"]["cnpj"], number=10)
    bad_total = bad_total.replace(b"<vProd>1000.00</vProd>\n        <vDesc>", b"<vProd>10.00</vProd>\n        <vDesc>")
    res = _import(client, s, bad_total).json()["result"]["files"][0]
    assert res["status"] == "imported_with_errors"
    found = client.get(f"{s['base']}/assessments", headers=s["h"], params={"document_id": res["document_id"]}).json()
    assert found == []  # documentos inválidos não geram oportunidades nas regras de exemplo


def test_async_import_via_worker(client, setup):
    s = setup
    r = _import(client, s, build_nfe(SUPPLIER, s["company"]["cnpj"], number=300), async_=True)
    assert r.status_code == 202 and r.json()["status"] == "queued"
    job_id = r.json()["id"]
    while jobs.run_next("test-worker"):
        pass
    job = client.get(f"{s['base']}/jobs/{job_id}", headers=s["h"]).json()
    assert job["status"] == "succeeded", job
    assert job["result"]["summary"] == {"imported": 1}
    # O worker atua em nome do usuário (RLS aplicada): auditoria registra o autor.
    with service_connection() as conn:
        actor = fetch_value(conn, """select actor_id from audit_events where entity_type = 'fiscal_documents'
                                      and action = 'insert' and after->>'import_job_id' = :j""", {"j": job_id})
    assert str(actor) == s["admin"].id


def test_suppliers_csv_compliance_and_alerts(client, setup):
    s = setup
    sup_a, sup_b = make_cnpj("880000000001"), make_cnpj("880000000002")
    csv = (f"cnpj;razao_social;uf;regime;empresas\n"
           f"{sup_a};Fornecedor A;SP;lucro real;{s['company']['cnpj']}\n"
           f"{sup_b};Fornecedor B;RJ;simples;\n"
           f"123;Inválido;XX;;\n").encode()
    r = client.post(f"{s['base']}/suppliers/import", headers=s["h"], files={"file": ("f.csv", csv, "text/csv")})
    assert r.status_code == 200, r.text
    rep = r.json()
    assert (rep["created"], rep["rejected"], rep["linked"]) == (2, 1, 1)
    again = client.post(f"{s['base']}/suppliers/import", headers=s["h"], files={"file": ("f.csv", csv, "text/csv")}).json()
    assert (again["created"], again["updated"]) == (0, 2)

    supplier = next(x for x in client.get(f"{s['base']}/suppliers", headers=s["h"]).json() if x["cnpj"] == sup_a)
    sid = supplier["id"]
    today = date.today()
    checks = [
        {"check_type": "cadastro_cnpj", "result": "regular", "source": "Receita Federal - comprovante"},
        {"check_type": "cnd_federal", "result": "regular", "source": "RFB/PGFN",
         "issued_at": str(today - timedelta(days=170)), "valid_until": str(today + timedelta(days=10))},
        {"check_type": "crf_fgts", "result": "regular", "source": "Caixa - CRF"},
        {"check_type": "cndt", "result": "regular", "source": "TST - CNDT"},
    ]
    for c in checks:
        assert client.post(f"{s['base']}/suppliers/{sid}/checks", headers=s["h"], json=c).status_code == 201
    detail = client.get(f"{s['base']}/suppliers/{sid}", headers=s["h"]).json()
    assert detail["supplier"]["compliance_status"] == "regular"
    alerts = client.get(f"{s['base']}/alerts", headers=s["h"]).json()
    assert any(a["kind"] == "compliance_expiring" and a["supplier_id"] == sid for a in alerts)

    # Certidão trabalhista irregular → status irregular e alerta crítico; regra de risco dispara.
    client.post(f"{s['base']}/suppliers/{sid}/checks", headers=s["h"],
                json={"check_type": "cndt", "result": "irregular", "source": "TST - CNDT"})
    detail = client.get(f"{s['base']}/suppliers/{sid}", headers=s["h"]).json()
    assert detail["supplier"]["compliance_status"] == "irregular"
    critical = client.get(f"{s['base']}/alerts", headers=s["h"], params={"severity": "critical"}).json()
    assert any("CNDT" in a["title"] for a in critical)

    res = _import(client, s, build_nfe(sup_a, s["company"]["cnpj"], number=77)).json()["result"]["files"][0]
    risks = client.get(f"{s['base']}/assessments", headers=s["h"],
                       params={"document_id": res["document_id"], "tax": "RISCO"}).json()
    assert len(risks) == 1 and risks[0]["item_id"] is None

    # Regularização resolve o alerta crítico (scan sincroniza).
    client.post(f"{s['base']}/suppliers/{sid}/checks", headers=s["h"],
                json={"check_type": "cndt", "result": "regular", "source": "TST - CNDT"})
    critical = client.get(f"{s['base']}/alerts", headers=s["h"], params={"severity": "critical"}).json()
    assert not any(a["supplier_id"] == sid for a in critical)

    report = client.get(f"{s['base']}/compliance/report", headers=s["h"], params={"format": "csv"})
    assert report.status_code == 200 and sup_a in report.text

    # Evidência: upload privado e download pela API.
    ev = client.post(f"{s['base']}/suppliers/{sid}/evidence", headers=s["h"],
                     files={"file": ("cnd.pdf", b"%PDF-1.4 teste", "application/pdf")}, data={"kind": "cnd_federal"})
    assert ev.status_code == 201, ev.text
    dl = client.get(f"{s['base']}/evidence/{ev.json()['id']}/download", headers=s["h"])
    assert dl.status_code == 200 and dl.content.startswith(b"%PDF")
    bad = client.post(f"{s['base']}/suppliers/{sid}/evidence", headers=s["h"],
                      files={"file": ("x.html", b"<script>", "text/html")})
    assert bad.status_code == 422


def test_rule_versioning(client, setup):
    s = setup
    rules = client.get(f"{s['base']}/tax-rules", headers=s["h"], params={"code": "EX.IPI_CREDITO_INDUSTRIAL"}).json()
    global_rule = rules[0]
    assert global_rule["organization_id"] is None and global_rule["status"] == "published"

    # Nova versão da organização, com critério mais restrito.
    conditions = {"all": [{"fact": "document.direction", "op": "eq", "value": "inbound"},
                          {"fact": "company.is_industrial", "op": "is_true"},
                          {"fact": "item.ipi_value", "op": "gt", "value": 500}]}
    r = client.post(f"{s['base']}/tax-rules/{global_rule['id']}/versions", headers=s["h"],
                    json={"conditions": conditions, "valid_from": "2026-01-01"})
    assert r.status_code == 201, r.text
    draft = r.json()
    assert draft["version"] == 2 and draft["status"] == "draft"

    bad = client.patch(f"{s['base']}/tax-rules/{draft['id']}", headers=s["h"],
                       json={"conditions": {"fact": "item.ipi_value", "op": "nope", "value": 1}})
    assert bad.status_code == 422

    assert client.post(f"{s['base']}/tax-rules/{draft['id']}/publish", headers=s["h"], json={}).status_code == 422
    pub = client.post(f"{s['base']}/tax-rules/{draft['id']}/publish", headers=s["h"],
                      json={"validated_by_specialist": "Maria Contadora — CRC SP-000000"})
    assert pub.status_code == 200 and pub.json()["status"] == "published"

    # Regra publicada é imutável — inclusive direto no banco.
    assert client.patch(f"{s['base']}/tax-rules/{draft['id']}", headers=s["h"], json={"name": "x"}).status_code == 409
    with pytest.raises(Exception):
        with service_connection() as conn:
            conn.execute(text("update tax_rules set conditions = '{}' where id = :id"), {"id": draft["id"]})

    # A versão da organização substitui a global: IPI de 100 não gera mais oportunidade.
    xml = build_nfe(SUPPLIER, s["company"]["cnpj"], number=900, items=[nfe_item(1, "1000.00", ipi="100.00")])
    doc = _import(client, s, xml).json()["result"]["files"][0]["document_id"]
    found = client.get(f"{s['base']}/assessments", headers=s["h"], params={"document_id": doc}).json()
    assert not any(a["rule_code"] == "EX.IPI_CREDITO_INDUSTRIAL" for a in found)

    test = client.post(f"{s['base']}/tax-rules/{draft['id']}/test", headers=s["h"], json={"facts": {
        "document": {"direction": "inbound"}, "company": {"is_industrial": True}, "item": {"ipi_value": 600}}})
    assert test.json()["matched"] is True and test.json()["estimated_amount"] == "600.00"


def test_dashboard(client, setup):
    s = setup
    _import(client, s, build_nfe(SUPPLIER, s["company"]["cnpj"], number=1000))
    d = client.get(f"{s['base']}/dashboard", headers=s["h"]).json()
    assert d["companies"]["total"] == 1 and d["documents"]["total"] == 1
    assert d["opportunities"]
