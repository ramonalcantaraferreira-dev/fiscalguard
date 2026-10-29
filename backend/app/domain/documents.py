"""Validação de identificadores fiscais brasileiros.

Suporta o CNPJ alfanumérico (IN RFB nº 2.229/2024), em vigor a partir de julho
de 2026: as 12 primeiras posições aceitam [0-9A-Z] e os dígitos verificadores
são calculados pelo módulo 11 usando o valor ASCII do caractere menos 48.
"""

from __future__ import annotations

import re

_CNPJ_RE = re.compile(r"^[0-9A-Z]{12}[0-9]{2}$")
_MASK_CHARS = re.compile(r"[./\-\s]")


def _char_value(ch: str) -> int:
    return ord(ch) - 48


def _mod11_dv(body: str, weights: list[int]) -> int:
    total = sum(_char_value(c) * w for c, w in zip(body, weights))
    remainder = total % 11
    return 0 if remainder < 2 else 11 - remainder


def normalize_cnpj(value: str | None) -> str:
    """Remove máscara e normaliza para maiúsculas (não valida)."""
    return _MASK_CHARS.sub("", value or "").upper()


def is_valid_cnpj(value: str | None) -> bool:
    cnpj = normalize_cnpj(value)
    if not _CNPJ_RE.match(cnpj) or len(set(cnpj)) == 1:
        return False
    w1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    w2 = [6] + w1
    dv1 = _mod11_dv(cnpj[:12], w1)
    dv2 = _mod11_dv(cnpj[:12] + str(dv1), w2)
    return cnpj[12:] == f"{dv1}{dv2}"


def is_valid_cpf(value: str | None) -> bool:
    cpf = re.sub(r"\D", "", value or "")
    if len(cpf) != 11 or len(set(cpf)) == 1:
        return False
    for size in (9, 10):
        total = sum(int(cpf[i]) * (size + 1 - i) for i in range(size))
        dv = (total * 10) % 11 % 10
        if dv != int(cpf[size]):
            return False
    return True


def format_cnpj(value: str) -> str:
    c = normalize_cnpj(value)
    if len(c) != 14:
        return value
    return f"{c[:2]}.{c[2:5]}.{c[5:8]}/{c[8:12]}-{c[12:]}"


# --------------------------------------------------------------------------- NF-e

_ACCESS_KEY_RE = re.compile(r"^[0-9]{6}[0-9A-Z]{12}[0-9]{26}$")


def access_key_dv(first43: str) -> int:
    """DV da chave de acesso: módulo 11 com pesos 2..9 da direita para a esquerda."""
    total = 0
    weight = 2
    for ch in reversed(first43):
        total += _char_value(ch) * weight
        weight = 2 if weight == 9 else weight + 1
    remainder = total % 11
    return 0 if remainder < 2 else 11 - remainder


def is_valid_access_key(key: str | None) -> bool:
    if not key or not _ACCESS_KEY_RE.match(key):
        return False
    return access_key_dv(key[:43]) == int(key[43])


def split_access_key(key: str) -> dict[str, str]:
    """Decompõe a chave de acesso nos campos definidos no Manual de Orientação do Contribuinte."""
    return {
        "cUF": key[0:2],
        "AAMM": key[2:6],
        "CNPJ": key[6:20],
        "mod": key[20:22],
        "serie": key[22:25],
        "nNF": key[25:34],
        "tpEmis": key[34],
        "cNF": key[35:43],
        "cDV": key[43],
    }
