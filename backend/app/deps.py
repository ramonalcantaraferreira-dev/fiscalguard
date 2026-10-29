"""Dependências comuns: conexão com contexto do usuário e checagens de RBAC.

As checagens aqui espelham as funções `app.*` do banco (mesma fonte de verdade),
de modo que a API retorna 403/404 claros antes mesmo de a RLS filtrar linhas.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends
from sqlalchemy import Connection

from app.auth import CurrentUser, get_current_user
from app.db import fetch_one, fetch_value, user_connection
from app.errors import Forbidden, NotFound


def get_db(user: CurrentUser = Depends(get_current_user)) -> Iterator[Connection]:
    with user_connection(user.id, user.claims) as conn:
        yield conn


@dataclass(frozen=True)
class OrgContext:
    org_id: UUID
    user: CurrentUser
    role: str
    conn: Connection

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def can_write(self) -> bool:
        return self.role in ("admin", "operator")

    def require_admin(self) -> None:
        if not self.is_admin:
            raise Forbidden("Apenas administradores do escritório podem executar esta ação")

    def require_write(self) -> None:
        if not self.can_write:
            raise Forbidden("Perfil somente leitura")

    def require_company(self, company_id: UUID, write: bool = False) -> dict:
        company = fetch_one(
            self.conn,
            "select * from client_companies where id = :id and organization_id = :org",
            {"id": company_id, "org": self.org_id},
        )
        if company is None:  # inexistente ou invisível pela RLS
            raise NotFound("Empresa")
        if write and not fetch_value(self.conn, "select app.can_write_company(:id)", {"id": company_id}):
            raise Forbidden("Sem permissão de escrita nesta empresa")
        return company


def get_org(
    org_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    conn: Connection = Depends(get_db),
) -> OrgContext:
    role = fetch_value(conn, "select app.org_role(:org)::text", {"org": org_id})
    if role is None:
        # 404 em vez de 403 para não revelar a existência de outros tenants.
        raise NotFound("Organização")
    return OrgContext(org_id=org_id, user=user, role=role, conn=conn)
