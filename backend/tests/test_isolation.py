"""Isolamento multi-tenant e RBAC — validados na API *e* diretamente no banco (RLS)."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.db import fetch_all, service_connection, user_connection
from tests.factories import build_nfe, make_cnpj, nfe_item


def _org(client, user, name):
    r = client.post("/api/v1/organizations", json={"name": name}, headers=user.headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _company(client, user, org, base12, **extra):
    body = {"legal_name": f"Empresa {base12}", "cnpj": make_cnpj(base12), "tax_regime": "lucro_real", **extra}
    r = client.post(f"/api/v1/organizations/{org}/companies", json=body, headers=user.headers)
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
def two_tenants(client, make_user):
    alice, bob = make_user("alice"), make_user("bob")
    org_a, org_b = _org(client, alice, "Escritório A"), _org(client, bob, "Escritório B")
    comp_a = _company(client, alice, org_a, "100000000001")
    comp_b = _company(client, bob, org_b, "200000000001")
    xml = build_nfe(make_cnpj("900000000001"), comp_b["cnpj"], number=501, items=[nfe_item(1)])
    r = client.post(f"/api/v1/organizations/{org_b}/companies/{comp_b['id']}/fiscal-documents/import",
                    files=[("files", ("b.xml", xml, "application/xml"))], headers=bob.headers)
    assert r.status_code == 200, r.text
    return dict(alice=alice, bob=bob, org_a=org_a, org_b=org_b, comp_a=comp_a, comp_b=comp_b)


def test_api_hides_other_tenant(client, two_tenants):
    t = two_tenants
    h = t["alice"].headers
    assert client.get(f"/api/v1/organizations/{t['org_b']}/companies", headers=h).status_code == 404
    assert client.get(f"/api/v1/organizations/{t['org_b']}/fiscal-documents", headers=h).status_code == 404
    # Mesmo usando a própria organização, IDs de outro tenant não são encontrados.
    r = client.get(f"/api/v1/organizations/{t['org_a']}/companies/{t['comp_b']['id']}", headers=h)
    assert r.status_code == 404
    orgs = client.get("/api/v1/organizations", headers=h).json()
    assert [o["id"] for o in orgs] == [t["org_a"]]


def test_rls_blocks_direct_sql(two_tenants):
    """Mesmo uma consulta SQL sem filtro, no contexto de Alice, não vê dados de B."""
    t = two_tenants
    with user_connection(t["alice"].id) as conn:
        for table in ("organizations", "client_companies", "suppliers", "fiscal_documents",
                      "fiscal_document_items", "tax_assessments", "integration_jobs", "audit_events"):
            rows = fetch_all(conn, f"select * from {table}")
            org_ids = {str(r.get("organization_id") or r.get("id")) for r in rows}
            assert t["org_b"] not in org_ids, table
    with user_connection(t["bob"].id) as conn:
        assert fetch_all(conn, "select id from fiscal_documents")


def test_rls_blocks_cross_tenant_writes(two_tenants):
    t = two_tenants
    # Inserir em organização alheia: violação de RLS.
    with pytest.raises(DBAPIError):
        with user_connection(t["alice"].id) as conn:
            conn.execute(text("insert into suppliers (organization_id, cnpj, legal_name) values (:o, :c, 'X')"),
                         {"o": t["org_b"], "c": make_cnpj("300000000001")})
    # Referenciar empresa de outro tenant a partir do próprio: FK composta impede.
    with pytest.raises(DBAPIError):
        with user_connection(t["alice"].id) as conn:
            sid = conn.execute(text("""insert into suppliers (organization_id, cnpj, legal_name)
                                       values (:o, :c, 'Y') returning id"""),
                               {"o": t["org_a"], "c": make_cnpj("300000000002")}).scalar()
            conn.execute(text("""insert into supplier_company_links (organization_id, supplier_id, company_id)
                                 values (:o, :s, :c)"""),
                         {"o": t["org_a"], "s": sid, "c": t["comp_b"]["id"]})
    # Updates em linhas invisíveis não afetam nada.
    with user_connection(t["alice"].id) as conn:
        n = conn.execute(text("update client_companies set legal_name = 'hack' where id = :id"),
                         {"id": t["comp_b"]["id"]}).rowcount
        assert n == 0


def test_roles(client, make_user, two_tenants):
    t = two_tenants
    alice, org = t["alice"], t["org_a"]
    operator, viewer = make_user("operator"), make_user("viewer")
    for u, role in ((operator, "operator"), (viewer, "viewer")):
        r = client.post(f"/api/v1/organizations/{org}/members", json={"email": u.email, "role": role},
                        headers=alice.headers)
        assert r.status_code == 201, r.text
    comp2 = _company(client, alice, org, "100000000002")

    # Sem vínculo de empresa, operador/visualizador não veem empresas.
    assert client.get(f"/api/v1/organizations/{org}/companies", headers=operator.headers).json() == []
    for u in (operator, viewer):
        r = client.post(f"/api/v1/organizations/{org}/companies/{t['comp_a']['id']}/members",
                        json={"user_id": u.id}, headers=alice.headers)
        assert r.status_code == 201
    ids = [c["id"] for c in client.get(f"/api/v1/organizations/{org}/companies", headers=operator.headers).json()]
    assert ids == [t["comp_a"]["id"]] and comp2["id"] not in ids

    # Operador escreve na empresa vinculada, mas não em outra.
    xml = build_nfe(make_cnpj("900000000002"), t["comp_a"]["cnpj"], number=601)
    url = f"/api/v1/organizations/{org}/companies/{{}}/fiscal-documents/import"
    files = [("files", ("a.xml", xml, "application/xml"))]
    assert client.post(url.format(t["comp_a"]["id"]), files=files, headers=operator.headers).status_code == 200
    assert client.post(url.format(comp2["id"]), files=files, headers=operator.headers).status_code == 404

    # Visualizador: somente leitura.
    assert client.post(url.format(t["comp_a"]["id"]), files=files, headers=viewer.headers).status_code == 403
    r = client.post(f"/api/v1/organizations/{org}/suppliers",
                    json={"cnpj": make_cnpj("400000000001"), "legal_name": "Fornecedor V"}, headers=viewer.headers)
    assert r.status_code == 403
    assert client.get(f"/api/v1/organizations/{org}/fiscal-documents", headers=viewer.headers).status_code == 200

    # Apenas administradores: empresas, membros e auditoria.
    assert client.post(f"/api/v1/organizations/{org}/companies",
                       json={"legal_name": "Empresa X", "cnpj": make_cnpj("100000000003")},
                       headers=operator.headers).status_code == 403
    assert client.get(f"/api/v1/organizations/{org}/audit-events", headers=operator.headers).status_code == 403
    assert client.get(f"/api/v1/organizations/{org}/audit-events", headers=alice.headers).status_code == 200


def test_last_admin_cannot_be_removed(client, two_tenants):
    t = two_tenants
    r = client.patch(f"/api/v1/organizations/{t['org_a']}/members/{t['alice'].id}",
                     json={"role": "viewer"}, headers=t["alice"].headers)
    assert r.status_code == 422


def test_audit_is_append_only(two_tenants):
    with pytest.raises(DBAPIError):
        with service_connection() as conn:
            conn.execute(text("delete from audit_events"))
    with pytest.raises(DBAPIError):
        with user_connection(two_tenants["alice"].id) as conn:
            conn.execute(text("insert into audit_events (action, entity_type) values ('x', 'y')"))


def test_unauthenticated_and_bad_token(client):
    assert client.get("/api/v1/organizations").status_code == 401
    r = client.get("/api/v1/organizations", headers={"Authorization": "Bearer abc.def.ghi"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthorized"
