from __future__ import annotations

import base64
import binascii
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


def limitar_texto_caixa(texto: str, limite: int = 3900) -> str:
    """
    Limita texto antes de enviar para a CAIXA.

    A documentação informa limite de 4.000 caracteres por comentário e alerta que
    caracteres especiais contam de forma diferente. Por segurança, usamos 3.900.
    """
    if texto is None:
        return ""

    s = str(texto).strip()
    if len(s) <= limite:
        return s

    aviso = "\n\n[Texto truncado automaticamente pela integração para respeitar o limite da CAIXA.]"
    corte = max(0, limite - len(aviso))
    return s[:corte].rstrip() + aviso


def limpar_base64(base64_file: str) -> str:
    return re.sub(r"\s+", "", base64_file or "").strip()


def tamanho_base64_em_bytes(base64_file: str) -> int:
    b64 = limpar_base64(base64_file)
    if not b64:
        return 0

    try:
        return len(base64.b64decode(b64, validate=True))
    except binascii.Error:
        return len(base64.b64decode(b64))


def base64_menor_ou_igual(base64_file: str, limite_bytes: int) -> bool:
    try:
        return tamanho_base64_em_bytes(base64_file) <= limite_bytes
    except Exception:
        return False
