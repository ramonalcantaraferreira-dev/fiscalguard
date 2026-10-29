"""Comandos administrativos.

    python -m app.cli migrate [--local-shim]   aplica supabase/migrations (e o shim local)
    python -m app.cli seed-rules [--publish]   cadastra as regras de EXEMPLO como regras globais
    python -m app.cli worker [--once]          processa a fila de integration_jobs
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path

from sqlalchemy import text

from app.db import fetch_value, service_connection
from app.rules.examples import EXAMPLE_RULES
from app.services import jobs

ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = ROOT / "supabase" / "migrations"
SHIM = ROOT / "supabase" / "local" / "00_supabase_shim.sql"
log = logging.getLogger("fiscalguard.cli")


def _run_script(conn, sql: str) -> None:
    # Cursor DBAPI sem parâmetros: permite múltiplos comandos e não interpreta '%'.
    conn.connection.dbapi_connection.cursor().execute(sql)


def migrate(local_shim: bool = False) -> list[str]:
    applied: list[str] = []
    with service_connection() as conn:
        if local_shim:
            _run_script(conn, SHIM.read_text())
        _run_script(conn, """create schema if not exists app;
            create table if not exists app.schema_migrations (
              version text primary key, applied_at timestamptz not null default now())""")
        done = {r[0] for r in conn.execute(text("select version from app.schema_migrations"))}
        for path in sorted(MIGRATIONS.glob("*.sql")):
            if path.stem in done:
                continue
            _run_script(conn, path.read_text())
            conn.execute(text("insert into app.schema_migrations (version) values (:v)"), {"v": path.stem})
            applied.append(path.stem)
    return applied


def seed_rules(publish: bool = False) -> int:
    count = 0
    with service_connection() as conn:
        for rule in EXAMPLE_RULES:
            data = rule.model_dump(mode="json")
            exists = fetch_value(conn, "select 1 from tax_rules where organization_id is null and code = :c",
                                 {"c": rule.code})
            if exists:
                continue
            conn.execute(
                text("""
                insert into tax_rules (organization_id, code, version, name, description, tax, legal_basis,
                                       scope, conditions, estimate, justification_template, valid_from,
                                       valid_to, status, content_hash, published_at)
                values (null, :code, 1, :name, :description, :tax, :legal_basis, cast(:scope as rule_scope),
                        cast(:conditions as jsonb), cast(:estimate as jsonb), :justification_template,
                        :valid_from, :valid_to, cast(:status as rule_status), :hash,
                        case when :status = 'published' then now() end)
                """),
                {**data, "conditions": json.dumps(data["conditions"]),
                 "estimate": json.dumps(data["estimate"]) if data["estimate"] else None,
                 "status": "published" if publish else "draft", "hash": rule.content_hash()},
            )
            count += 1
    return count


def worker(once: bool = False, idle_sleep: float = 2.0) -> None:
    log.info("worker iniciado")
    while True:
        job = jobs.run_next()
        if job is None:
            if once:
                return
            time.sleep(idle_sleep)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(prog="fiscalguard")
    sub = parser.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("migrate")
    m.add_argument("--local-shim", action="store_true", help="cria roles/auth do Supabase (somente local)")
    s = sub.add_parser("seed-rules")
    s.add_argument("--publish", action="store_true", help="publica as regras de exemplo (apenas dev)")
    w = sub.add_parser("worker")
    w.add_argument("--once", action="store_true", help="processa a fila até esvaziar e sai")
    args = parser.parse_args()

    if args.cmd == "migrate":
        print("aplicadas:", migrate(args.local_shim) or "nenhuma")
    elif args.cmd == "seed-rules":
        print("regras inseridas:", seed_rules(args.publish))
    elif args.cmd == "worker":
        worker(args.once)


if __name__ == "__main__":
    main()
