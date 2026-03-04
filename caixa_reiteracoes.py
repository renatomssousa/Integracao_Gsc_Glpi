# caixa_reiteracoes.py
from typing import List, Dict

from caixa_client import buscar_reiteracoes_raw
from processors import extrair_reiteracoes


def buscar_reiteracoes_caixa(capturado: bool = True) -> List[Dict]:
    """
    Busca interações da CAIXA (GetList_Reiteracao)
    """
    xml = buscar_reiteracoes_raw(capturado=capturado)
    return extrair_reiteracoes(xml)
