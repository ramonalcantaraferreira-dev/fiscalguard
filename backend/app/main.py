from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.config import get_settings
from app.db import get_engine
from app.errors import install_error_handlers
from app.routers import assessments, fiscal, operations, organizations, rules, suppliers

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description=(
            "API do FiscalGuard: gestão multi-tenant de escritórios contábeis, compliance de "
            "fornecedores e identificação de **potenciais** oportunidades tributárias. "
            "Nenhum resultado representa crédito definitivamente aproveitável sem revisão humana."
        ),
        docs_url="/docs",
        openapi_url="/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["Authorization", "Content-Type"],
    )
    install_error_handlers(app)
    for module in (organizations, suppliers, fiscal, rules, assessments, operations):
        app.include_router(module.router)

    @app.get("/health", tags=["infra"])
    def health():
        with get_engine().connect() as conn:
            conn.execute(text("select 1"))
        return {"status": "ok", "environment": settings.environment}

    return app


app = create_app()
