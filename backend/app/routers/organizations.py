from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy import Connection, text

from app.auth import CurrentUser, get_current_user
from app.db import fetch_all, fetch_one, fetch_value
from app.deps import OrgContext, get_db, get_org
from app.errors import NotFound
from app.schemas import (
    CompanyIn, CompanyMemberIn, CompanyOut, CompanyUpdate, MemberIn, MemberOut, MemberUpdate,
    OrganizationIn, OrganizationOut,
)

router = APIRouter(prefix="/api/v1", tags=["organizações e empresas"])


@router.get("/me")
def me(user: CurrentUser = Depends(get_current_user), conn: Connection = Depends(get_db)):
    profile = fetch_one(conn, "select id, email, full_name from users where id = :id", {"id": user.id})
    orgs = fetch_all(
        conn,
        """select o.id, o.name, o.cnpj, o.created_at, m.role::text as role
             from organizations o join organization_members m on m.organization_id = o.id
            where m.user_id = :uid order by o.name""",
        {"uid": user.id},
    )
    return {"user": profile or {"id": user.id, "email": user.email}, "organizations": orgs}


@router.get("/organizations", response_model=list[OrganizationOut])
def list_organizations(user: CurrentUser = Depends(get_current_user), conn: Connection = Depends(get_db)):
    return fetch_all(
        conn,
        """select o.*, m.role::text as role from organizations o
             join organization_members m on m.organization_id = o.id and m.user_id = :uid
            order by o.name""",
        {"uid": user.id},
    )


@router.post("/organizations", response_model=OrganizationOut, status_code=status.HTTP_201_CREATED)
def create_organization(body: OrganizationIn, conn: Connection = Depends(get_db)):
    org_id = fetch_value(conn, "select public.create_organization(:n, :c)", {"n": body.name, "c": body.cnpj})
    return fetch_one(conn, "select *, 'admin' as role from organizations where id = :id", {"id": org_id})


# ------------------------------------------------------------------ membros

@router.get("/organizations/{org_id}/members", response_model=list[MemberOut])
def list_members(ctx: OrgContext = Depends(get_org)):
    return fetch_all(
        ctx.conn,
        """select m.user_id, u.email, u.full_name, m.role::text as role, m.created_at
             from organization_members m join users u on u.id = m.user_id
            where m.organization_id = :org order by u.email""",
        {"org": ctx.org_id},
    )


@router.post("/organizations/{org_id}/members", response_model=MemberOut, status_code=201)
def add_member(body: MemberIn, ctx: OrgContext = Depends(get_org)):
    ctx.require_admin()
    member_id = fetch_value(
        ctx.conn, "select public.add_org_member(:org, :email, cast(:role as member_role))",
        {"org": ctx.org_id, "email": body.email, "role": body.role},
    )
    return fetch_one(
        ctx.conn,
        """select m.user_id, u.email, u.full_name, m.role::text as role, m.created_at
             from organization_members m join users u on u.id = m.user_id where m.id = :id""",
        {"id": member_id},
    )


@router.patch("/organizations/{org_id}/members/{user_id}", response_model=MemberOut)
def update_member(user_id: UUID, body: MemberUpdate, ctx: OrgContext = Depends(get_org)):
    ctx.require_admin()
    row = fetch_one(
        ctx.conn,
        """update organization_members set role = cast(:role as member_role)
            where organization_id = :org and user_id = :uid returning user_id""",
        {"org": ctx.org_id, "uid": user_id, "role": body.role},
    )
    if not row:
        raise NotFound("Membro")
    return fetch_one(
        ctx.conn,
        """select m.user_id, u.email, u.full_name, m.role::text as role, m.created_at
             from organization_members m join users u on u.id = m.user_id
            where m.organization_id = :org and m.user_id = :uid""",
        {"org": ctx.org_id, "uid": user_id},
    )


@router.delete("/organizations/{org_id}/members/{user_id}", status_code=204)
def remove_member(user_id: UUID, ctx: OrgContext = Depends(get_org)):
    ctx.require_admin()
    deleted = ctx.conn.execute(
        text("delete from organization_members where organization_id = :org and user_id = :uid"),
        {"org": ctx.org_id, "uid": user_id},
    ).rowcount
    if not deleted:
        raise NotFound("Membro")
    ctx.conn.execute(
        text("delete from company_memberships where organization_id = :org and user_id = :uid"),
        {"org": ctx.org_id, "uid": user_id},
    )


# ------------------------------------------------------------------ empresas

@router.get("/organizations/{org_id}/companies", response_model=list[CompanyOut])
def list_companies(ctx: OrgContext = Depends(get_org), include_inactive: bool = False):
    return fetch_all(
        ctx.conn,
        """select * from client_companies where organization_id = :org and (active or :inactive)
            order by legal_name""",
        {"org": ctx.org_id, "inactive": include_inactive},
    )


@router.post("/organizations/{org_id}/companies", response_model=CompanyOut, status_code=201)
def create_company(body: CompanyIn, ctx: OrgContext = Depends(get_org)):
    ctx.require_admin()
    return fetch_one(
        ctx.conn,
        """insert into client_companies (organization_id, legal_name, trade_name, cnpj, state_registration,
                                         uf, tax_regime, is_industrial)
           values (:org, :legal_name, :trade_name, :cnpj, :state_registration, :uf,
                   cast(:tax_regime as tax_regime), :is_industrial)
           returning *""",
        {"org": ctx.org_id, **body.model_dump()},
    )


@router.get("/organizations/{org_id}/companies/{company_id}", response_model=CompanyOut)
def get_company(company_id: UUID, ctx: OrgContext = Depends(get_org)):
    return ctx.require_company(company_id)


@router.patch("/organizations/{org_id}/companies/{company_id}", response_model=CompanyOut)
def update_company(company_id: UUID, body: CompanyUpdate, ctx: OrgContext = Depends(get_org)):
    ctx.require_admin()
    ctx.require_company(company_id)
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        return ctx.require_company(company_id)
    casts = {"tax_regime": "cast(:tax_regime as tax_regime)"}
    sets = ", ".join(f"{k} = {casts.get(k, ':' + k)}" for k in changes)
    return fetch_one(
        ctx.conn,
        f"update client_companies set {sets} where id = :id and organization_id = :org returning *",
        {"id": company_id, "org": ctx.org_id, **changes},
    )


@router.get("/organizations/{org_id}/companies/{company_id}/members", response_model=list[MemberOut])
def list_company_members(company_id: UUID, ctx: OrgContext = Depends(get_org)):
    ctx.require_admin()
    return fetch_all(
        ctx.conn,
        """select cm.user_id, u.email, u.full_name, m.role::text as role, cm.created_at
             from company_memberships cm
             join users u on u.id = cm.user_id
             join organization_members m on m.user_id = cm.user_id and m.organization_id = cm.organization_id
            where cm.company_id = :c order by u.email""",
        {"c": company_id},
    )


@router.post("/organizations/{org_id}/companies/{company_id}/members", status_code=201)
def add_company_member(company_id: UUID, body: CompanyMemberIn, ctx: OrgContext = Depends(get_org)):
    ctx.require_admin()
    ctx.require_company(company_id)
    is_member = fetch_value(
        ctx.conn, "select 1 from organization_members where organization_id = :org and user_id = :u",
        {"org": ctx.org_id, "u": body.user_id},
    )
    if not is_member:
        raise NotFound("Membro da organização")
    ctx.conn.execute(
        text("""insert into company_memberships (organization_id, company_id, user_id)
                values (:org, :c, :u) on conflict (company_id, user_id) do nothing"""),
        {"org": ctx.org_id, "c": company_id, "u": body.user_id},
    )
    return {"company_id": company_id, "user_id": body.user_id}


@router.delete("/organizations/{org_id}/companies/{company_id}/members/{user_id}", status_code=204)
def remove_company_member(company_id: UUID, user_id: UUID, ctx: OrgContext = Depends(get_org)):
    ctx.require_admin()
    ctx.conn.execute(
        text("delete from company_memberships where company_id = :c and user_id = :u and organization_id = :org"),
        {"c": company_id, "u": user_id, "org": ctx.org_id},
    )
