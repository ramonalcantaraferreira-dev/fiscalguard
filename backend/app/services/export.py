from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi.responses import StreamingResponse

_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, Decimal):
        return f"{value:.2f}".replace(".", ",")
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    text = str(value)
    # Proteção contra injeção de fórmulas em planilhas (CSV injection).
    if text.startswith(_FORMULA_PREFIXES):
        text = "'" + text
    return text


def csv_response(filename: str, headers: Sequence[str], rows: Iterable[Sequence[Any]]) -> StreamingResponse:
    buf = io.StringIO()
    buf.write("﻿")  # BOM para o Excel reconhecer UTF-8
    writer = csv.writer(buf, delimiter=";")
    writer.writerow(headers)
    for row in rows:
        writer.writerow([_cell(v) for v in row])
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
