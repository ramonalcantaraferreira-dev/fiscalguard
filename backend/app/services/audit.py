from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, text


def log_event(
    conn: Connection,
    org_id: UUID | str,
    action: str,
    entity_type: str,
    entity_id: UUID | str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Registra um evento de aplicação. Alterações de linhas já são auditadas por trigger."""
    conn.execute(
        text("select app.log_event(:org, :action, :etype, :eid, cast(:meta as jsonb))"),
        {
            "org": str(org_id),
            "action": action,
            "etype": entity_type,
            "eid": str(entity_id) if entity_id else None,
            "meta": json.dumps(metadata or {}, default=str),
        },
    )
