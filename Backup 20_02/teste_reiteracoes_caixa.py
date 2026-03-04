# -*- coding: utf-8 -*-
import xml.etree.ElementTree as ET

import caixa_client
import processors

def resumo(xml: str):
    print("XML length:", len(xml))
    try:
        root = ET.fromstring(xml)
        vals = []
        for el in root.iter():
            tag = el.tag.split("}", 1)[-1]
            if tag == "getListValues":
                vals.append(el)
        print("getListValues:", len(vals))
    except Exception as e:
        print("ERRO parse XML:", e)

def listar(reits):
    print("Total reiteracoes parseadas:", len(reits))
    for i, r in enumerate(reits[:10], start=1):
        print(f"{i}) REQ={r.get('no_req')} WO={r.get('no_wo')} chamado_fornecedor={r.get('chamado_fornecedor')}")
        desc = (r.get("descricao") or "").strip().replace("\n", " ")
        print("   desc:", desc[:180])
        anexos = r.get("anexos") or []
        print("   anexos:", len(anexos))

print("\n=== TESTE CAIXA GetList_Reiteracao capturado=False (pendentes) ===")
xml0 = caixa_client.buscar_reiteracoes(capturado=False)
resumo(xml0)
reits0 = processors.extrair_reiteracoes(xml0)
listar(reits0)

print("\n=== TESTE CAIXA GetList_Reiteracao capturado=True (capturadas) ===")
xml1 = caixa_client.buscar_reiteracoes(capturado=True)
resumo(xml1)
reits1 = processors.extrair_reiteracoes(xml1)
listar(reits1)

print("\n=== OK ===")
