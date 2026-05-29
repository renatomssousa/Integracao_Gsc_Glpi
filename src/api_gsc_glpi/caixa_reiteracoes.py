from typing import List, Dict

from .caixa_client import buscar_reiteracoes
from .processors import extrair_reiteracoes


def buscar_reiteracoes_caixa(capturado: bool = False) -> List[Dict]:
    xml = buscar_reiteracoes(capturado=capturado)
    return extrair_reiteracoes(xml)