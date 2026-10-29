from decimal import Decimal

import pytest

from app.domain.documents import is_valid_access_key, is_valid_cnpj, is_valid_cpf, normalize_cnpj
from app.services.nfe_parser import NFeParseError, parse_nfe
from tests.factories import build_nfe, make_access_key, make_cnpj, nfe_item

SUPPLIER = make_cnpj("112223330001")
BUYER = make_cnpj("445556660001")


class TestCnpj:
    def test_numeric(self):
        assert is_valid_cnpj("11.222.333/0001-81")
        assert not is_valid_cnpj("11.222.333/0001-82")
        assert not is_valid_cnpj("00000000000000")
        assert not is_valid_cnpj("123")

    def test_alphanumeric_official_example(self):
        # Exemplo divulgado pela Receita Federal para o CNPJ alfanumérico.
        assert is_valid_cnpj("12.ABC.345/01DE-35")
        assert normalize_cnpj("12.abc.345/01de-35") == "12ABC34501DE35"
        assert not is_valid_cnpj("12ABC34501DE36")

    def test_cpf(self):
        assert is_valid_cpf("529.982.247-25")
        assert not is_valid_cpf("111.111.111-11")


class TestAccessKey:
    def test_generated_key_is_valid(self):
        key = make_access_key(SUPPLIER, 123)
        assert len(key) == 44 and is_valid_access_key(key)

    def test_wrong_dv(self):
        key = make_access_key(SUPPLIER, 123)
        bad = key[:43] + str((int(key[43]) + 1) % 10)
        assert not is_valid_access_key(bad)

    def test_alphanumeric_cnpj_key(self):
        key = make_access_key("12ABC34501DE35", 7)
        assert is_valid_access_key(key)


class TestParser:
    def test_parse_valid_nfe(self):
        xml = build_nfe(SUPPLIER, BUYER, items=[nfe_item(1, "1000.00", icms="180.00"),
                                               nfe_item(2, "500.00", icms=None, ipi="50.00")])
        doc = parse_nfe(xml)
        assert doc.is_valid, doc.issues
        assert doc.issuer_cnpj == SUPPLIER and doc.recipient_cnpj == BUYER
        assert doc.total_products == Decimal("1500.00")
        assert len(doc.items) == 2
        first, second = doc.items
        assert first.icms_cst == "00" and first.icms_value == Decimal("180.00")
        assert second.icms_cst == "40" and second.icms_value is None
        assert second.ipi_value == Decimal("50.00")
        assert first.pis_cst == "01" and first.pis_value == Decimal("16.50")
        assert "ICMS" in first.raw_taxes
        assert doc.protocol_status == "100"

    def test_totals_mismatch_is_error(self):
        xml = build_nfe(SUPPLIER, BUYER, items=[nfe_item(1, "1000.00")])
        xml = xml.replace(b"<vProd>1000.00</vProd>\n        <vDesc>", b"<vProd>999.00</vProd>\n        <vDesc>")
        doc = parse_nfe(xml)
        assert not doc.is_valid
        assert any(i.code == "totals_mismatch" for i in doc.issues)

    def test_missing_protocol_is_warning_only(self):
        doc = parse_nfe(build_nfe(SUPPLIER, BUYER, with_protocol=False))
        assert doc.is_valid
        assert [i.code for i in doc.issues] == ["no_protocol"]

    def test_key_mismatch(self):
        xml = build_nfe(SUPPLIER, BUYER, number=10).replace(b"<nNF>10</nNF>", b"<nNF>11</nNF>")
        doc = parse_nfe(xml)
        assert any(i.code == "access_key_mismatch" for i in doc.issues)

    def test_rejects_doctype_xxe(self):
        evil = b"""<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]>
                   <NFe xmlns="http://www.portalfiscal.inf.br/nfe">&e;</NFe>"""
        with pytest.raises(NFeParseError):
            parse_nfe(evil)

    def test_rejects_other_namespace_and_garbage(self):
        with pytest.raises(NFeParseError):
            parse_nfe(b"<NFe><infNFe/></NFe>")
        with pytest.raises(NFeParseError):
            parse_nfe(b"nao e xml")
