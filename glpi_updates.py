import hashlib
import json
import os
from typing import Dict, Any, Optional

# Para produção, deixe STATE_FILE=state.json ou STATE_FILE=state_prod.json no .env.
# Para homologação, use outro arquivo. Ex.: STATE_FILE=state_hmp.json.
STATE_FILE = os.getenv("STATE_FILE", "state.json")


def _default_state() -> Dict[str, Any]:
    return {
        "mapeamentos": {},
        "reiteracoes_processadas": [],
        "followups_enviados": {},
        "status_enviados": {},
        "caixa_cancelados": {},
        "req_wo_bloqueados": {},
        "documentos_enviados": {}
    }


def _load_state() -> Dict[str, Any]:
    if not os.path.exists(STATE_FILE):
        return _default_state()

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            base = _default_state()
            if isinstance(data, dict):
                base.update(data)
            return base
    except Exception:
        return _default_state()


def _save_state(state: Dict[str, Any]) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def _chave_reiteracao(no_req: str, no_wo: str, id_arquivo: str = "", descricao: str = "") -> str:
    no_req = (no_req or "").strip()
    no_wo = (no_wo or "").strip()
    id_arquivo = (id_arquivo or "").strip()

    if id_arquivo:
        return f"{no_req}|{no_wo}|{id_arquivo}"

    resumo = hashlib.sha1((descricao or "").strip().encode("utf-8")).hexdigest()[:20]
    return f"{no_req}|{no_wo}|{resumo}"


# ============================
# MAPEAMENTO REQ/WO
# ============================

def registrar_mapeamento_req_wo(no_req: str, no_wo: str, ticket_id: int):
    state = _load_state()
    key = f"{(no_req or '').strip()}|{(no_wo or '').strip()}"
    state["mapeamentos"][key] = int(ticket_id)
    _save_state(state)


def buscar_ticket_por_req_wo(no_req: str, no_wo: str) -> Optional[int]:
    state = _load_state()
    valor = state["mapeamentos"].get(f"{(no_req or '').strip()}|{(no_wo or '').strip()}")
    try:
        return int(valor) if valor is not None else None
    except Exception:
        return None


def buscar_req_wo_por_ticket(ticket_id: int):
    state = _load_state()
    ticket_id_int = int(ticket_id)
    for k, v in state["mapeamentos"].items():
        try:
            if int(v) == ticket_id_int:
                no_req, no_wo = k.split("|", 1)
                return {"no_req": no_req, "no_wo": no_wo}
        except Exception:
            continue
    return None


# ============================
# BLOQUEIO REQ/WO
# ============================

def bloquear_req_wo(no_req: str, no_wo: str, ticket_id: int, motivo: str):
    state = _load_state()
    key = f"{(no_req or '').strip()}|{(no_wo or '').strip()}"
    state["req_wo_bloqueados"][key] = {
        "ticket_id": int(ticket_id),
        "motivo": str(motivo or "")[:1000]
    }
    _save_state(state)


def remover_bloqueio_req_wo(no_req: str, no_wo: str):
    state = _load_state()
    key = f"{(no_req or '').strip()}|{(no_wo or '').strip()}"
    if key in state.get("req_wo_bloqueados", {}):
        del state["req_wo_bloqueados"][key]
        _save_state(state)


def req_wo_esta_bloqueado(no_req: str, no_wo: str) -> bool:
    state = _load_state()
    return f"{(no_req or '').strip()}|{(no_wo or '').strip()}" in state.get("req_wo_bloqueados", {})


# ============================
# REITERAÇÕES
# ============================

def reiteracao_ja_processada(no_req: str, no_wo: str, id_arquivo: str = "", descricao: str = "") -> bool:
    state = _load_state()
    chave = _chave_reiteracao(no_req, no_wo, id_arquivo, descricao)
    return chave in state["reiteracoes_processadas"]


def marcar_reiteracao_processada(no_req: str, no_wo: str, id_arquivo: str = "", descricao: str = ""):
    state = _load_state()
    chave = _chave_reiteracao(no_req, no_wo, id_arquivo, descricao)
    if chave not in state["reiteracoes_processadas"]:
        state["reiteracoes_processadas"].append(chave)
    _save_state(state)


# ============================
# FOLLOWUPS
# ============================

def followup_ja_enviado(ticket_id: int, followup_id: int) -> bool:
    state = _load_state()
    enviados = state["followups_enviados"].get(str(ticket_id), [])
    return int(followup_id) in enviados


def marcar_followup_enviado(ticket_id: int, followup_id: int):
    state = _load_state()
    tid = str(ticket_id)
    state["followups_enviados"].setdefault(tid, [])
    followup_id_int = int(followup_id)
    if followup_id_int not in state["followups_enviados"][tid]:
        state["followups_enviados"][tid].append(followup_id_int)
    _save_state(state)


# ============================
# STATUS
# ============================

def status_ja_enviado(ticket_id: int, status: str) -> bool:
    state = _load_state()
    return state["status_enviados"].get(str(ticket_id)) == status


def marcar_status_enviado(ticket_id: int, status: str):
    state = _load_state()
    state["status_enviados"][str(ticket_id)] = status
    _save_state(state)


# ============================
# DOCUMENTOS
# ============================

def documento_ja_enviado(ticket_id: int, doc_id: int) -> bool:
    state = _load_state()
    enviados = state["documentos_enviados"].get(str(ticket_id), [])
    return int(doc_id) in enviados


def marcar_documento_enviado(ticket_id: int, doc_id: int):
    state = _load_state()
    tid = str(ticket_id)
    state["documentos_enviados"].setdefault(tid, [])
    doc_id_int = int(doc_id)
    if doc_id_int not in state["documentos_enviados"][tid]:
        state["documentos_enviados"][tid].append(doc_id_int)
    _save_state(state)
