"""Leitura, normalização e validação de XML de NF-e (modelo 55).

O parser é puro (sem banco) para ser testável isoladamente. A segurança do XML
é tratada aqui: DTDs/entidades externas são recusados (proteção contra XXE e
"billion laughs").
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from lxml import etree

from app.domain.documents import (
    is_valid_access_key,
    is_valid_cnpj,
    is_valid_cpf,
    split_access_key,
)

NS = "http://www.portalfiscal.inf.br/nfe"
_N = {"n": NS}
AUTHORIZED_STATUS = {"100", "150"}  # autorizado / autorizado fora de prazo
TOLERANCE = Decimal("0.05")

_PARSER = etree.XMLParser(
    resolve_entities=False,
    no_network=True,
    load_dtd=False,
    dtd_validation=False,
    huge_tree=False,
    remove_comments=True,
)


class NFeParseError(ValueError):
    """XML ilegível ou que não é uma NF-e."""


@dataclass
class Issue:
    code: str
    message: str
    severity: str = "error"  # error | warning


@dataclass
class NFeItem:
    item_number: int
    product_code: str | None
    description: str | None
    ncm: str | None
    cest: str | None
    cfop: str | None
    unit: str | None
    quantity: Decimal
    unit_price: Decimal
    total_value: Decimal
    discount: Decimal
    icms_origin: int | None = None
    icms_cst: str | None = None
    icms_base: Decimal | None = None
    icms_rate: Decimal | None = None
    icms_value: Decimal | None = None
    icms_st_value: Decimal | None = None
    ipi_cst: str | None = None
    ipi_value: Decimal | None = None
    pis_cst: str | None = None
    pis_base: Decimal | None = None
    pis_rate: Decimal | None = None
    pis_value: Decimal | None = None
    cofins_cst: str | None = None
    cofins_base: Decimal | None = None
    cofins_rate: Decimal | None = None
    cofins_value: Decimal | None = None
    raw_taxes: dict[str, Any] = field(default_factory=dict)


@dataclass
class NFeDocument:
    access_key: str
    version: str | None
    model: str | None
    series: int | None
    number: int | None
    issue_date: datetime | None
    operation_type: int | None
    issuer_cnpj: str | None
    issuer_name: str | None
    issuer_uf: str | None
    issuer_crt: int | None
    recipient_cnpj: str | None
    recipient_name: str | None
    recipient_uf: str | None
    total_products: Decimal
    total_discount: Decimal
    total_icms: Decimal
    total_icms_st: Decimal
    total_ipi: Decimal
    total_pis: Decimal
    total_cofins: Decimal
    total_amount: Decimal
    protocol_number: str | None
    protocol_status: str | None
    items: list[NFeItem]
    sha256: str
    issues: list[Issue] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return not any(i.severity == "error" for i in self.issues)

    def issues_as_json(self) -> list[dict]:
        return [asdict(i) for i in self.issues]


# ----------------------------------------------------------------- helpers XML

def _text(node: etree._Element | None, path: str) -> str | None:
    if node is None:
        return None
    found = node.find(path, _N)
    if found is None or found.text is None:
        return None
    value = found.text.strip()
    return value or None


def _dec(node: etree._Element | None, path: str, default: Decimal | None = None) -> Decimal | None:
    raw = _text(node, path)
    if raw is None:
        return default
    try:
        return Decimal(raw)
    except InvalidOperation:
        return default


def _int(node: etree._Element | None, path: str) -> int | None:
    raw = _text(node, path)
    return int(raw) if raw and raw.isdigit() else None


def _to_dict(node: etree._Element) -> Any:
    """Converte um elemento em dict simples (para guardar grupos de tributos brutos)."""
    children = list(node)
    if not children:
        return (node.text or "").strip()
    out: dict[str, Any] = {}
    for child in children:
        key = etree.QName(child).localname
        value = _to_dict(child)
        if key in out:
            if not isinstance(out[key], list):
                out[key] = [out[key]]
            out[key].append(value)
        else:
            out[key] = value
    return out


def _first_child(node: etree._Element | None) -> etree._Element | None:
    if node is None:
        return None
    for child in node:
        if isinstance(child.tag, str):
            return child
    return None


def _parse_datetime(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


# ----------------------------------------------------------------- parsing

def _parse_item(det: etree._Element) -> NFeItem:
    prod = det.find("n:prod", _N)
    imposto = det.find("n:imposto", _N)
    item = NFeItem(
        item_number=int(det.get("nItem", "0")),
        product_code=_text(prod, "n:cProd"),
        description=_text(prod, "n:xProd"),
        ncm=_text(prod, "n:NCM"),
        cest=_text(prod, "n:CEST"),
        cfop=_text(prod, "n:CFOP"),
        unit=_text(prod, "n:uCom"),
        quantity=_dec(prod, "n:qCom", Decimal(0)),
        unit_price=_dec(prod, "n:vUnCom", Decimal(0)),
        total_value=_dec(prod, "n:vProd", Decimal(0)),
        discount=_dec(prod, "n:vDesc", Decimal(0)),
    )
    if imposto is None:
        return item

    item.raw_taxes = _to_dict(imposto) or {}

    icms = _first_child(imposto.find("n:ICMS", _N))  # ICMS00, ICMS10, ..., ICMSSN102 etc.
    if icms is not None:
        orig = _text(icms, "n:orig")
        item.icms_origin = int(orig) if orig and orig.isdigit() else None
        item.icms_cst = _text(icms, "n:CST") or _text(icms, "n:CSOSN")
        item.icms_base = _dec(icms, "n:vBC")
        item.icms_rate = _dec(icms, "n:pICMS")
        item.icms_value = _dec(icms, "n:vICMS")
        item.icms_st_value = _dec(icms, "n:vICMSST")

    ipi = imposto.find("n:IPI", _N)
    if ipi is not None:
        trib = ipi.find("n:IPITrib", _N)
        nt = ipi.find("n:IPINT", _N)
        grp = trib if trib is not None else nt
        item.ipi_cst = _text(grp, "n:CST")
        item.ipi_value = _dec(trib, "n:vIPI") if trib is not None else None

    for tax in ("PIS", "COFINS"):
        grp = _first_child(imposto.find(f"n:{tax}", _N))
        if grp is None:
            continue
        prefix = tax.lower()
        setattr(item, f"{prefix}_cst", _text(grp, "n:CST"))
        setattr(item, f"{prefix}_base", _dec(grp, "n:vBC"))
        setattr(item, f"{prefix}_rate", _dec(grp, f"n:p{tax}"))
        setattr(item, f"{prefix}_value", _dec(grp, f"n:v{tax}"))
    return item


def parse_nfe(content: bytes) -> NFeDocument:
    if b"<!DOCTYPE" in content[:2048].upper():
        raise NFeParseError("XML com DOCTYPE não é aceito")
    try:
        root = etree.fromstring(content, _PARSER)
    except etree.XMLSyntaxError as exc:
        raise NFeParseError(f"XML malformado: {exc.msg}") from exc

    if etree.QName(root).namespace != NS:
        raise NFeParseError("Namespace do Portal Fiscal (NF-e) não encontrado")

    nfe = root if etree.QName(root).localname == "NFe" else root.find("n:NFe", _N)
    inf = nfe.find("n:infNFe", _N) if nfe is not None else None
    if inf is None:
        raise NFeParseError("Elemento infNFe não encontrado")

    ide = inf.find("n:ide", _N)
    emit = inf.find("n:emit", _N)
    dest = inf.find("n:dest", _N)
    tot = inf.find("n:total/n:ICMSTot", _N)
    prot = root.find("n:protNFe/n:infProt", _N)

    access_key = (inf.get("Id") or "").removeprefix("NFe")
    zero = Decimal(0)
    doc = NFeDocument(
        access_key=access_key,
        version=inf.get("versao"),
        model=_text(ide, "n:mod"),
        series=_int(ide, "n:serie"),
        number=_int(ide, "n:nNF"),
        issue_date=_parse_datetime(_text(ide, "n:dhEmi") or _text(ide, "n:dEmi")),
        operation_type=_int(ide, "n:tpNF"),
        issuer_cnpj=_text(emit, "n:CNPJ") or _text(emit, "n:CPF"),
        issuer_name=_text(emit, "n:xNome"),
        issuer_uf=_text(emit, "n:enderEmit/n:UF"),
        issuer_crt=_int(emit, "n:CRT"),
        recipient_cnpj=_text(dest, "n:CNPJ") or _text(dest, "n:CPF"),
        recipient_name=_text(dest, "n:xNome"),
        recipient_uf=_text(dest, "n:enderDest/n:UF"),
        total_products=_dec(tot, "n:vProd", zero),
        total_discount=_dec(tot, "n:vDesc", zero),
        total_icms=_dec(tot, "n:vICMS", zero),
        total_icms_st=_dec(tot, "n:vST", zero),
        total_ipi=_dec(tot, "n:vIPI", zero),
        total_pis=_dec(tot, "n:vPIS", zero),
        total_cofins=_dec(tot, "n:vCOFINS", zero),
        total_amount=_dec(tot, "n:vNF", zero),
        protocol_number=_text(prot, "n:nProt"),
        protocol_status=_text(prot, "n:cStat"),
        items=[_parse_item(det) for det in inf.findall("n:det", _N)],
        sha256=hashlib.sha256(content).hexdigest(),
    )
    doc.issues = validate(doc)
    return doc


# ----------------------------------------------------------------- validação

def validate(doc: NFeDocument) -> list[Issue]:
    issues: list[Issue] = []
    add = issues.append

    if not is_valid_access_key(doc.access_key):
        add(Issue("access_key_invalid", "Chave de acesso inválida (formato ou dígito verificador)"))
    else:
        parts = split_access_key(doc.access_key)
        if doc.model and parts["mod"] != doc.model:
            add(Issue("access_key_mismatch", "Modelo diverge da chave de acesso"))
        if doc.series is not None and int(parts["serie"]) != doc.series:
            add(Issue("access_key_mismatch", "Série diverge da chave de acesso"))
        if doc.number is not None and int(parts["nNF"]) != doc.number:
            add(Issue("access_key_mismatch", "Número diverge da chave de acesso"))
        if doc.issuer_cnpj and len(doc.issuer_cnpj) == 14 and parts["CNPJ"] != doc.issuer_cnpj:
            add(Issue("access_key_mismatch", "CNPJ do emitente diverge da chave de acesso"))

    if doc.model != "55":
        add(Issue("unsupported_model", f"Modelo {doc.model!r} não suportado (apenas NF-e 55)"))

    if not doc.issuer_cnpj:
        add(Issue("issuer_missing", "Emitente sem CNPJ/CPF"))
    elif len(doc.issuer_cnpj) == 14 and not is_valid_cnpj(doc.issuer_cnpj):
        add(Issue("issuer_cnpj_invalid", "CNPJ do emitente inválido"))

    if doc.recipient_cnpj:
        valid = is_valid_cnpj(doc.recipient_cnpj) if len(doc.recipient_cnpj) == 14 else is_valid_cpf(doc.recipient_cnpj)
        if not valid:
            add(Issue("recipient_doc_invalid", "CNPJ/CPF do destinatário inválido"))

    if not doc.items:
        add(Issue("no_items", "Documento sem itens"))

    numbers = [i.item_number for i in doc.items]
    if len(numbers) != len(set(numbers)):
        add(Issue("duplicate_item_number", "Número de item repetido"))

    def check_sum(label: str, items_total: Decimal, header_total: Decimal) -> None:
        if abs(items_total - header_total) > TOLERANCE:
            add(Issue(
                "totals_mismatch",
                f"Soma dos itens ({label}) {items_total} difere do total informado {header_total}",
            ))

    check_sum("vProd", sum((i.total_value for i in doc.items), Decimal(0)), doc.total_products)
    check_sum("vICMS", sum((i.icms_value or 0 for i in doc.items), Decimal(0)), doc.total_icms)
    check_sum("vIPI", sum((i.ipi_value or 0 for i in doc.items), Decimal(0)), doc.total_ipi)

    if doc.protocol_status is None:
        add(Issue("no_protocol", "XML sem protocolo de autorização (protNFe)", "warning"))
    elif doc.protocol_status not in AUTHORIZED_STATUS:
        add(Issue("not_authorized", f"Protocolo com cStat {doc.protocol_status} (não autorizado)", "warning"))

    if doc.issue_date is None:
        add(Issue("issue_date_missing", "Data de emissão ausente ou inválida"))

    return issues
