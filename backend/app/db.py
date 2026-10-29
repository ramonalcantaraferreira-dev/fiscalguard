"""Acesso ao banco.

Toda requisição de usuário roda numa transação com `SET LOCAL ROLE authenticated`
e as claims do JWT em `request.jwt.claims`, exatamente como o PostgREST do
Supabase. Assim as políticas RLS valem também para a API Python: um bug de
filtro no backend não consegue vazar dados de outra organização.

A sessão de serviço (sem troca de role) é reservada ao worker e à CLI.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from functools import lru_cache
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, Engine, create_engine, text

from app.config import get_settings


@lru_cache
def get_engine() -> Engine:
    settings = get_settings()
    return create_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_size=settings.db_pool_size,
        future=True,
    )


def _apply_user_context(conn: Connection, user_id: UUID | str, claims: Mapping[str, Any] | None) -> None:
    payload = dict(claims or {})
    payload["sub"] = str(user_id)
    payload.setdefault("role", "authenticated")
    conn.execute(text("select set_config('request.jwt.claims', :c, true)"), {"c": json.dumps(payload)})
    conn.execute(text("set local role authenticated"))


@contextmanager
def user_connection(user_id: UUID | str, claims: Mapping[str, Any] | None = None) -> Iterator[Connection]:
    """Transação sujeita a RLS em nome do usuário."""
    with get_engine().begin() as conn:
        _apply_user_context(conn, user_id, claims)
        yield conn


@contextmanager
def service_connection() -> Iterator[Connection]:
    """Transação privilegiada (ignora RLS). Use somente em processos internos."""
    with get_engine().begin() as conn:
        yield conn


def impersonate(conn: Connection, user_id: UUID | str) -> None:
    """Rebaixa uma conexão de serviço para o contexto de um usuário (worker)."""
    _apply_user_context(conn, user_id, None)


def fetch_one(conn: Connection, sql: str, params: Mapping[str, Any] | None = None) -> dict | None:
    row = conn.execute(text(sql), params or {}).mappings().first()
    return dict(row) if row else None


def fetch_all(conn: Connection, sql: str, params: Mapping[str, Any] | None = None) -> list[dict]:
    return [dict(r) for r in conn.execute(text(sql), params or {}).mappings().all()]


def fetch_value(conn: Connection, sql: str, params: Mapping[str, Any] | None = None) -> Any:
    return conn.execute(text(sql), params or {}).scalar()
