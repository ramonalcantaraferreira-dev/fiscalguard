"""Infraestrutura de testes.

Os testes de integração usam um PostgreSQL real (RLS não pode ser testada com
mocks). Configure TEST_DATABASE_ADMIN_URL apontando para um servidor onde o
usuário possa criar bancos; o banco `fiscalguard_test` é recriado a cada sessão.
Sem servidor disponível, os testes de integração são ignorados.
"""

from __future__ import annotations

import os
import time
import uuid
from pathlib import Path

import jwt
import pytest

ADMIN_URL = os.environ.get("TEST_DATABASE_ADMIN_URL", "postgresql://postgres@localhost:54329/postgres")
TEST_DB = "fiscalguard_test"
JWT_SECRET = "test-secret-with-at-least-32-bytes-of-entropy!"


def _db_url(base: str, db: str) -> str:
    return base.rsplit("/", 1)[0] + f"/{db}"


os.environ.setdefault("ENVIRONMENT", "test")
os.environ["DATABASE_URL"] = _db_url(ADMIN_URL, TEST_DB).replace("postgresql://", "postgresql+psycopg://", 1)
os.environ["SUPABASE_JWT_SECRET"] = JWT_SECRET
os.environ["STORAGE_BACKEND"] = "local"


def _server_available() -> bool:
    try:
        import psycopg
        with psycopg.connect(ADMIN_URL, connect_timeout=3):
            return True
    except Exception:
        return False


DB_AVAILABLE = _server_available()


@pytest.fixture(scope="session")
def database(tmp_path_factory):
    if not DB_AVAILABLE:
        pytest.skip("PostgreSQL de teste indisponível (defina TEST_DATABASE_ADMIN_URL)")
    import psycopg

    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f"drop database if exists {TEST_DB} with (force)")
        admin.execute(f"create database {TEST_DB}")

    os.environ["LOCAL_STORAGE_DIR"] = str(tmp_path_factory.mktemp("storage"))
    from app.cli import migrate, seed_rules
    from app.config import get_settings
    from app.services.storage import get_storage

    get_settings.cache_clear()
    get_storage.cache_clear()
    migrate(local_shim=True)
    seed_rules(publish=True)
    yield
    from app.db import get_engine
    get_engine().dispose()


@pytest.fixture(scope="session")
def client(database):
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app()) as c:
        yield c


def token_for(user_id: str, email: str) -> str:
    now = int(time.time())
    return jwt.encode(
        {"sub": user_id, "email": email, "aud": "authenticated", "role": "authenticated",
         "iat": now, "exp": now + 3600},
        JWT_SECRET, algorithm="HS256",
    )


class User:
    def __init__(self, id: str, email: str):
        self.id, self.email = id, email
        self.headers = {"Authorization": f"Bearer {token_for(id, email)}"}


@pytest.fixture
def make_user(database):
    from sqlalchemy import text

    from app.db import service_connection

    def _make(name: str = "user") -> User:
        uid = str(uuid.uuid4())
        email = f"{name}-{uid[:8]}@example.com"
        with service_connection() as conn:
            conn.execute(text("insert into auth.users (id, email) values (:id, :e)"), {"id": uid, "e": email})
            conn.execute(text("insert into public.users (id, email) values (:id, :e)"), {"id": uid, "e": email})
        return User(uid, email)

    return _make


FIXTURES = Path(__file__).parent / "fixtures"
