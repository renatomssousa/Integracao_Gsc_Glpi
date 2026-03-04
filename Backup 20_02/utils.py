from __future__ import annotations

import re


def limpar_texto_xml(texto: str) -> str:
    if texto is None:
        return ""

    # Remove caracteres de controle proibidos em XML 1.0 (exceto tab, CR, LF)
    texto = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F]", " ", str(texto))

    # Escapes básicos
    texto = (
        texto.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )

    # Evita strings gigantes acidentais
    return texto.strip()