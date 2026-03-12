from __future__ import annotations

from typing import Any, Dict, List, Optional


def extrair_anexos_do_xml(reiteracao: Dict[str, Any]) -> Optional[List[Dict[str, str]]]:
    """
    Mantido como estava no seu fluxo: processors preenche 'anexos' no dict quando existir.
    Aqui só normaliza caso venha em outro formato.
    """
    anexos = reiteracao.get("anexos")
    if not anexos:
        return None

    saida: List[Dict[str, str]] = []
    for ax in anexos:
        filename = ax.get("filename") or ax.get("nome") or "anexo.bin"
        b64 = ax.get("base64") or ""
        if b64:
            saida.append({"filename": filename, "base64": b64})
    return saida or None
