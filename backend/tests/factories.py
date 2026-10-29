"""Geradores de dados de teste: CNPJs válidos e XMLs de NF-e consistentes."""

from __future__ import annotations

from decimal import Decimal

from app.domain.documents import _mod11_dv, access_key_dv


def make_cnpj(base12: str) -> str:
    w1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    dv1 = _mod11_dv(base12, w1)
    dv2 = _mod11_dv(base12 + str(dv1), [6] + w1)
    return f"{base12}{dv1}{dv2}"


def make_access_key(cnpj: str, number: int, series: int = 1, uf: str = "35", aamm: str = "2610") -> str:
    first43 = f"{uf}{aamm}{cnpj}55{series:03d}{number:09d}1{number:08d}"
    return first43 + str(access_key_dv(first43))


def nfe_item(
    n: int,
    value: str = "1000.00",
    cfop: str = "5102",
    icms: str | None = "180.00",
    ipi: str | None = None,
    pis_cst: str = "01",
    ncm: str = "84713012",
    description: str | None = None,
) -> dict:
    return {"n": n, "value": value, "cfop": cfop, "icms": icms, "ipi": ipi, "pis_cst": pis_cst,
            "ncm": ncm, "description": description or f"Produto {n}"}


def build_nfe(
    issuer_cnpj: str,
    recipient_cnpj: str,
    number: int = 1,
    items: list[dict] | None = None,
    issuer_name: str = "Fornecedor Exemplo Ltda",
    with_protocol: bool = True,
    total_override: str | None = None,
    issue_date: str = "2026-10-15T10:00:00-03:00",
) -> bytes:
    items = items or [nfe_item(1)]
    key = make_access_key(issuer_cnpj, number)
    dets = []
    for it in items:
        icms = (
            f"<ICMS><ICMS00><orig>0</orig><CST>00</CST><modBC>3</modBC><vBC>{it['value']}</vBC>"
            f"<pICMS>18.00</pICMS><vICMS>{it['icms']}</vICMS></ICMS00></ICMS>"
            if it["icms"] else
            "<ICMS><ICMS40><orig>0</orig><CST>40</CST></ICMS40></ICMS>"
        )
        ipi = (
            f"<IPI><cEnq>999</cEnq><IPITrib><CST>50</CST><vBC>{it['value']}</vBC><pIPI>10.00</pIPI>"
            f"<vIPI>{it['ipi']}</vIPI></IPITrib></IPI>" if it["ipi"] else ""
        )
        pis_v = (Decimal(it["value"]) * Decimal("0.0165")).quantize(Decimal("0.01"))
        cof_v = (Decimal(it["value"]) * Decimal("0.076")).quantize(Decimal("0.01"))
        dets.append(f"""
      <det nItem="{it['n']}">
        <prod><cProd>P{it['n']}</cProd><cEAN>SEM GTIN</cEAN><xProd>{it['description']}</xProd>
          <NCM>{it['ncm']}</NCM><CFOP>{it['cfop']}</CFOP><uCom>UN</uCom><qCom>1.0000</qCom>
          <vUnCom>{it['value']}</vUnCom><vProd>{it['value']}</vProd></prod>
        <imposto>{icms}{ipi}
          <PIS><PISAliq><CST>{it['pis_cst']}</CST><vBC>{it['value']}</vBC><pPIS>1.65</pPIS><vPIS>{pis_v}</vPIS></PISAliq></PIS>
          <COFINS><COFINSAliq><CST>{it['pis_cst']}</CST><vBC>{it['value']}</vBC><pCOFINS>7.60</pCOFINS><vCOFINS>{cof_v}</vCOFINS></COFINSAliq></COFINS>
        </imposto>
      </det>""")
    v_prod = sum(Decimal(i["value"]) for i in items)
    v_icms = sum(Decimal(i["icms"] or 0) for i in items)
    v_ipi = sum(Decimal(i["ipi"] or 0) for i in items)
    v_nf = total_override or str(v_prod + v_ipi)
    prot = (f"<protNFe versao=\"4.00\"><infProt><tpAmb>1</tpAmb><chNFe>{key}</chNFe>"
            f"<nProt>135260000000{number:03d}</nProt><cStat>100</cStat></infProt></protNFe>") if with_protocol else ""
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<nfeProc xmlns="http://www.portalfiscal.inf.br/nfe" versao="4.00">
  <NFe>
    <infNFe Id="NFe{key}" versao="4.00">
      <ide><cUF>35</cUF><natOp>VENDA</natOp><mod>55</mod><serie>1</serie><nNF>{number}</nNF>
        <dhEmi>{issue_date}</dhEmi><tpNF>1</tpNF></ide>
      <emit><CNPJ>{issuer_cnpj}</CNPJ><xNome>{issuer_name}</xNome>
        <enderEmit><UF>SP</UF></enderEmit><CRT>3</CRT></emit>
      <dest><CNPJ>{recipient_cnpj}</CNPJ><xNome>Cliente Destinatário SA</xNome>
        <enderDest><UF>SP</UF></enderDest></dest>
      {''.join(dets)}
      <total><ICMSTot><vBC>{v_prod}</vBC><vICMS>{v_icms}</vICMS><vST>0.00</vST><vProd>{v_prod}</vProd>
        <vDesc>0.00</vDesc><vIPI>{v_ipi}</vIPI><vPIS>0</vPIS><vCOFINS>0</vCOFINS><vNF>{v_nf}</vNF></ICMSTot></total>
    </infNFe>
  </NFe>
  {prot}
</nfeProc>"""
    return xml.encode()
