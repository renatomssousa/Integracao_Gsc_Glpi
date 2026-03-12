from __future__ import annotations

import html
import re
from typing import Optional


def limpar_texto_xml(texto: str) -> str:
    if texto is None:
        return ""

    texto = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F]", " ", str(texto))

    texto = (
        texto.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )

    return texto.strip()


def html_para_texto(texto: Optional[str]) -> str:
    if not texto:
        return ""

    s = html.unescape(str(texto))
    s = s.replace("\xa0", " ")

    s = re.sub(r"(?i)<br\s*/?>", "\n", s)
    s = re.sub(r"(?i)</p\s*>", "\n", s)
    s = re.sub(r"(?i)</div\s*>", "\n", s)
    s = re.sub(r"<[^>]+>", " ", s)

    s = re.sub(r"\r\n?", "\n", s)
    s = re.sub(r"[ \t\f\v]+", " ", s)
    s = re.sub(r"\n[ \t]+", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)

    return s.strip()