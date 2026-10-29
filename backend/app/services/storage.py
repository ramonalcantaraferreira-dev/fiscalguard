"""Armazenamento privado de arquivos (XML, PDFs, evidências, relatórios).

Nenhum arquivo é público: o acesso é feito pela API (após checagem de
permissão) ou por URLs assinadas de curta duração.
"""

from __future__ import annotations

import hashlib
import re
from functools import lru_cache
from pathlib import Path
from typing import Protocol
from urllib.parse import quote

import httpx

from app.config import get_settings

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def safe_filename(name: str) -> str:
    cleaned = _SAFE_NAME.sub("_", Path(name or "arquivo").name).strip("._")
    return (cleaned or "arquivo")[:120]


def content_path(org_id: str, category: str, content: bytes, filename: str) -> str:
    """Caminho determinístico por conteúdo: reenvios do mesmo arquivo não duplicam objetos."""
    digest = hashlib.sha256(content).hexdigest()
    return f"{org_id}/{category}/{digest[:2]}/{digest}/{safe_filename(filename)}"


class Storage(Protocol):
    def put(self, path: str, content: bytes, content_type: str) -> None: ...
    def get(self, path: str) -> bytes: ...
    def signed_url(self, path: str, expires_in: int) -> str | None: ...


class LocalStorage:
    def __init__(self, root: str):
        self.root = Path(root).resolve()

    def _full(self, path: str) -> Path:
        full = (self.root / path).resolve()
        if self.root not in full.parents:
            raise ValueError("caminho fora do diretório de armazenamento")
        return full

    def put(self, path: str, content: bytes, content_type: str) -> None:
        full = self._full(path)
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_bytes(content)

    def get(self, path: str) -> bytes:
        return self._full(path).read_bytes()

    def signed_url(self, path: str, expires_in: int) -> str | None:
        return None  # servido via endpoint de download da API


class SupabaseStorage:
    def __init__(self, url: str, service_key: str, bucket: str):
        self.base = f"{url.rstrip('/')}/storage/v1"
        self.bucket = bucket
        self.client = httpx.Client(
            headers={"Authorization": f"Bearer {service_key}", "apikey": service_key},
            timeout=30,
        )

    def put(self, path: str, content: bytes, content_type: str) -> None:
        r = self.client.post(
            f"{self.base}/object/{self.bucket}/{quote(path)}",
            content=content,
            headers={"Content-Type": content_type, "x-upsert": "true"},
        )
        r.raise_for_status()

    def get(self, path: str) -> bytes:
        r = self.client.get(f"{self.base}/object/{self.bucket}/{quote(path)}")
        r.raise_for_status()
        return r.content

    def signed_url(self, path: str, expires_in: int) -> str | None:
        r = self.client.post(
            f"{self.base}/object/sign/{self.bucket}/{quote(path)}", json={"expiresIn": expires_in}
        )
        r.raise_for_status()
        signed = r.json().get("signedURL") or r.json().get("signedUrl")
        return f"{self.base}{signed}" if signed else None


@lru_cache
def get_storage() -> Storage:
    s = get_settings()
    if s.storage_backend == "supabase":
        if not (s.supabase_url and s.supabase_service_role_key):
            raise RuntimeError("SUPABASE_URL e SUPABASE_SERVICE_ROLE_KEY são obrigatórios")
        return SupabaseStorage(s.supabase_url, s.supabase_service_role_key, s.storage_bucket)
    return LocalStorage(s.local_storage_dir)
