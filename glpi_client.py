# -*- coding: utf-8 -*-
from __future__ import annotations

import base64
import json
from io import BytesIO
from typing import Any, Dict, Optional, List

import requests

from config import (
    GLPI_API_URL,
    GLPI_APP_TOKEN,
    GLPI_USER_TOKEN,
    GLPI_ENTITIES_ID,
    GLPI_VERIFY_SSL,
)

SESSION_TOKEN: Optional[str] = None
DEFAULT_TIMEOUT = 60


def _base_headers(include_json: bool = True) -> Dict[str, str]:
    headers = {
        "App-Token": GLPI_APP_TOKEN,
        "Authorization": f"user_token {GLPI_USER_TOKEN}",
    }
    if include_json:
        headers["Content-Type"] = "application/json"
    return headers


def init_session() -> str:
    global SESSION_TOKEN
    url = f"{GLPI_API_URL}/initSession"
    r = requests.get(
        url,
        headers=_base_headers(),
        verify=GLPI_VERIFY_SSL,
        timeout=DEFAULT_TIMEOUT,
    )
    r.raise_for_status()
    SESSION_TOKEN = r.json().get("session_token")
    if not SESSION_TOKEN:
        raise Exception("Nao foi possivel obter session_token do GLPI")
    return SESSION_TOKEN


def kill_session() -> None:
    global SESSION_TOKEN
    if not SESSION_TOKEN:
        return
    try:
        requests.get(
            f"{GLPI_API_URL}/killSession",
            headers={**_base_headers(), "Session-Token": SESSION_TOKEN},
            verify=GLPI_VERIFY_SSL,
            timeout=DEFAULT_TIMEOUT,
        )
    except Exception:
        pass
    SESSION_TOKEN = None


def _auth_headers(include_json: bool = True) -> Dict[str, str]:
    if not SESSION_TOKEN:
        init_session()
    headers = _base_headers(include_json=include_json)
    headers["Session-Token"] = SESSION_TOKEN
    return headers


def _request(method: str, path: str, *, headers: Optional[Dict[str, str]] = None, **kwargs):
    global SESSION_TOKEN

    url = f"{GLPI_API_URL}{path}"
    req_headers = dict(headers) if headers is not None else _auth_headers()

    r = requests.request(
        method=method,
        url=url,
        headers=req_headers,
        verify=GLPI_VERIFY_SSL,
        timeout=DEFAULT_TIMEOUT,
        **kwargs,
    )

    if r.status_code in (401, 403):
        body = (r.text or "").lower()
        if "session" in body or "token" in body or "error_session_token_invalid" in body:
            init_session()
            req_headers = dict(headers) if headers is not None else _auth_headers()
            req_headers["Session-Token"] = SESSION_TOKEN
            r = requests.request(
                method=method,
                url=url,
                headers=req_headers,
                verify=GLPI_VERIFY_SSL,
                timeout=DEFAULT_TIMEOUT,
                **kwargs,
            )

    return r


def criar_ticket(titulo: str, descricao: str, itilcategories_id: int = 7) -> int:
    r = _request(
        "POST",
        "/Ticket",
        json={
            "input": {
                "name": titulo,
                "content": descricao,
                "entities_id": GLPI_ENTITIES_ID,
                "itilcategories_id": itilcategories_id,
            }
        },
    )
    r.raise_for_status()
    return int(r.json()["id"])


def buscar_tickets_caixa_por_categoria(itilcategories_id: int = 7) -> List[Dict[str, Any]]:
    r = _request(
        "GET",
        "/search/Ticket",
        params={
            "criteria[0][field]": 7,
            "criteria[0][searchtype]": "equals",
            "criteria[0][value]": str(itilcategories_id),
            "forcedisplay[0]": "2",
            "forcedisplay[1]": "12",
            "range": "0-200",
        },
    )
    r.raise_for_status()
    return r.json().get("data", [])


def buscar_status_ticket(ticket_id: int) -> Optional[str]:
    r = _request("GET", f"/Ticket/{ticket_id}")
    if r.status_code != 200:
        return None

    status_id = r.json().get("status")
    mapa = {
        1: "Novo",
        2: "Em atendimento",
        3: "Planejado",
        4: "Pendente",
        5: "Solucionado",
        6: "Fechado",
    }
    return mapa.get(status_id)


def atualizar_status_ticket(ticket_id: int, status_id: int) -> None:
    r = _request(
        "PUT",
        f"/Ticket/{ticket_id}",
        json={"input": {"id": ticket_id, "status": int(status_id)}},
    )
    if r.status_code not in (200, 201):
        return


def adicionar_followup_publico(ticket_id: int, texto: str) -> int:
    r = _request(
        "POST",
        f"/Ticket/{ticket_id}/ITILFollowup",
        json={
            "input": {
                "itemtype": "Ticket",
                "items_id": ticket_id,
                "content": texto,
                "is_private": 0,
            }
        },
    )
    if r.status_code >= 400:
        raise Exception(f"Erro ao criar followup: status={r.status_code} body={r.text}")
    r.raise_for_status()
    return int(r.json()["id"])


def listar_followups(ticket_id: int) -> List[Dict[str, Any]]:
    r = _request("GET", f"/Ticket/{ticket_id}/ITILFollowup")
    r.raise_for_status()
    data = r.json()
    return data if isinstance(data, list) else data.get("data", [])


def criar_documento_base64(filename: str, base64_file: str) -> int:
    if not SESSION_TOKEN:
        init_session()

    file_bytes = base64.b64decode(base64_file)

    files = {
        "uploadManifest": (
            None,
            json.dumps({
                "input": {
                    "name": filename,
                    "_filename": [filename],
                    "entities_id": GLPI_ENTITIES_ID,
                }
            }),
            "application/json",
        ),
        "filename[0]": (filename, BytesIO(file_bytes)),
    }

    r = _request(
        "POST",
        "/Document",
        headers=_auth_headers(include_json=False),
        files=files,
    )

    if r.status_code >= 400:
        raise Exception(f"Erro ao criar documento no GLPI: status={r.status_code} body={r.text}")

    r.raise_for_status()
    body = r.json()
    doc_id = body.get("id")
    if not doc_id:
        raise Exception(f"GLPI nao retornou id do documento: {body}")
    return int(doc_id)


def vincular_documento_item(doc_id: int, itemtype: str, items_id: int) -> int:
    r = _request(
        "POST",
        "/Document_Item",
        json={
            "input": {
                "documents_id": int(doc_id),
                "itemtype": itemtype,
                "items_id": int(items_id),
            }
        },
    )

    if r.status_code >= 400:
        raise Exception(
            f"Erro ao vincular documento ao item: status={r.status_code} body={r.text}"
        )

    r.raise_for_status()
    body = r.json()
    return int(body.get("id", 0) or 0)


def adicionar_followup_com_anexo(
    ticket_id: int,
    texto: str,
    filename: str,
    base64_file: str,
) -> int:
    if not SESSION_TOKEN:
        init_session()

    file_bytes = base64.b64decode(base64_file)

    files = {
        "uploadManifest": (
            None,
            json.dumps({
                "input": {
                    "itemtype": "Ticket",
                    "items_id": str(ticket_id),
                    "content": texto,
                    "is_private": 0
                }
            })
        ),
        "filename[]": (filename, BytesIO(file_bytes)),
    }

    r = _request(
        "POST",
        "/TicketFollowup",
        headers=_auth_headers(include_json=False),
        files=files,
    )

    if r.status_code >= 400:
        raise Exception(f"Erro ao criar followup com anexo: status={r.status_code} body={r.text}")

    r.raise_for_status()

    body = r.json()
    if isinstance(body, dict) and "id" in body:
        return int(body["id"])

    raise Exception(f"GLPI nao retornou id do followup: {body}")