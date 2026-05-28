# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import time
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

import requests

from config import (
    CAIXA_ENDPOINT,
    CAIXA_USER,
    CAIXA_PASSWORD,
    CAIXA_TOKEN,
    CAIXA_QUALIFICATION,
    CAIXA_TIMEOUT_SECONDS,
)

from utils import (
    limpar_texto_xml,
    limitar_texto_caixa,
    limpar_base64,
    tamanho_base64_em_bytes,
)

MAX_RETRIES = int(os.getenv("CAIXA_MAX_RETRIES", "3"))
BACKOFF_SECONDS = [5, 15, 45]
LOG_DIR = os.getenv("CAIXA_LOG_DIR", "logs")
os.makedirs(LOG_DIR, exist_ok=True)

try:
    from config import CAIXA_ID_FORNECEDOR as CONFIG_CAIXA_ID_FORNECEDOR
except Exception:
    CONFIG_CAIXA_ID_FORNECEDOR = "SGP000000170811"

CAIXA_ID_FORNECEDOR = os.getenv("CAIXA_ID_FORNECEDOR", CONFIG_CAIXA_ID_FORNECEDOR)
try:
    from config import CAIXA_NOME_FORNECEDOR as CONFIG_CAIXA_NOME_FORNECEDOR
except Exception:
    CONFIG_CAIXA_NOME_FORNECEDOR = "PETACORP"

CAIXA_NOME_FORNECEDOR = os.getenv("CAIXA_NOME_FORNECEDOR", CONFIG_CAIXA_NOME_FORNECEDOR)
MAX_ANEXOS_CAIXA = 3
MAX_ANEXO_CAIXA_BYTES = 10 * 1024 * 1024


def bool_tf(v: bool) -> str:
    return "true" if v else "false"


SOAP_ACTION = {
    "GetList_Abertura": "urn:GSC_RF010_FornecedorExterno_V401_WS/GetList_Abertura",
    "GetList_Reiteracao": "urn:GSC_RF010_FornecedorExterno_V401_WS/GetList_Reiteracao",
    "SetAceiteRecusa": "urn:GSC_RF010_FornecedorExterno_V401_WS/SetAceiteRecusa",
    "SetAtualizacao": "urn:GSC_RF010_FornecedorExterno_V401_WS/SetAtualizacao",
}

STATUS_FORNECEDOR = {
    "EM_ANALISE": "1",
    "EM ANÁLISE": "1",
    "EM ANALISE": "1",
    "ACIONADO": "2",
    "AGENDADO": "3",
    "PENDENTE": "4",
    "CONCLUIDO": "5",
    "CONCLUÍDO": "5",
}


class CaixaSoapFault(Exception):
    def __init__(self, http_status: int, fault_code: str, fault_string: str):
        self.http_status = http_status
        self.fault_code = fault_code
        self.fault_string = fault_string
        super().__init__(f"HTTP {http_status} - CAIXA rejeitou: {fault_code} - {fault_string}")


class CaixaFinalError(Exception):
    pass


class CaixaRetornoProcessamentoError(Exception):
    pass


def _empty_getlist_response(metodo: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/">
  <soapenv:Body>
    <ns1:{metodo}Response xmlns:ns1="urn:GSC_RF010_FornecedorExterno_V401_WS" />
  </soapenv:Body>
</soapenv:Envelope>"""


def _extract_fault(resp_text: str) -> Optional[tuple[str, str]]:
    try:
        root = ET.fromstring(resp_text)
    except Exception:
        return None

    fault = root.find(".//{*}Fault")
    if fault is None:
        return None

    fc_el = fault.find(".//faultcode")
    fs_el = fault.find(".//faultstring")

    fault_code = (fc_el.text or "").strip() if fc_el is not None else ""
    fault_string = (fs_el.text or "").strip() if fs_el is not None else ""

    if not fault_code and not fault_string:
        return None

    return fault_code, fault_string


def _is_no_data_fault(fault_string: str) -> bool:
    s = (fault_string or "").lower()
    return "error (302)" in s or "entrada não existe" in s or "entrada nao existe" in s or "entry does not exist" in s


def _is_final_fault(fault_string: str) -> bool:
    s = (fault_string or "").lower()

    if "error (10000)" in s:
        return True
    if "chamado esta cancelado" in s or "chamado está cancelado" in s:
        return True
    if "nao permite atualizacao" in s and "cancel" in s:
        return True
    if "não permite atualização" in s and "cancel" in s:
        return True
    if "finalizado" in s and ("nao permite" in s or "não permite" in s):
        return True

    return False


def _save_req_resp(metodo: str, req_xml: str, resp_text: str, http_status: int) -> None:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    uid = uuid.uuid4().hex[:8]
    req_path = os.path.join(LOG_DIR, f"{ts}_{metodo}_{http_status}_{uid}_req.xml")
    resp_path = os.path.join(LOG_DIR, f"{ts}_{metodo}_{http_status}_{uid}_resp.xml")

    with open(req_path, "w", encoding="utf-8") as f:
        f.write(req_xml)

    with open(resp_path, "w", encoding="utf-8") as f:
        f.write(resp_text)


def _find_text_any_namespace(root, tag_name: str) -> Optional[str]:
    if root is None:
        return None
    for el in root.iter():
        local = el.tag.split("}", 1)[-1] if "}" in el.tag else el.tag
        if local.lower() == tag_name.lower():
            return (el.text or "").strip()
    return None


def _extrair_motivos_tipo4(root) -> list[tuple[str, str]]:
    motivos = []
    for motivo in root.findall(".//{*}motivo"):
        codigo_el = motivo.find(".//{*}codigo")
        desc_el = motivo.find(".//{*}descricao")
        codigo = (codigo_el.text or "").strip() if codigo_el is not None and codigo_el.text else ""
        desc = (desc_el.text or "").strip() if desc_el is not None and desc_el.text else ""
        if codigo or desc:
            motivos.append((codigo, desc))
    return motivos


def validar_retorno_tipo4(soap_response_xml: str, obrigatorio: bool = True) -> Dict[str, Any]:
    """
    Valida o XML Tipo 4 retornado pela CAIXA.

    Pela documentação:
    - processado = 1: processado corretamente;
    - processado = 2: não processado / erro.
    Algumas respostas antigas podem usar true/false, então tratamos ambos.
    """
    try:
        root = ET.fromstring(soap_response_xml)
    except Exception:
        if obrigatorio:
            raise CaixaRetornoProcessamentoError("Retorno da CAIXA não é XML válido.")
        return {"processado": None, "ok": True, "motivos": []}

    processado = _find_text_any_namespace(root, "processado")
    motivos = _extrair_motivos_tipo4(root)

    if processado is None or processado == "":
        if obrigatorio:
            raise CaixaRetornoProcessamentoError("Retorno Tipo 4 sem tag processado.")
        return {"processado": None, "ok": True, "motivos": motivos}

    valor = processado.strip().lower()
    ok = valor in ("1", "true", "sim", "s")

    if ok:
        print(f"Retorno tipo 4 OK (processado={processado}).")
        return {"processado": processado, "ok": True, "motivos": motivos}

    msg_motivos = "; ".join(
        [f"codigo={codigo} descricao={desc}" for codigo, desc in motivos]
    ) or "sem motivo detalhado"

    print(f"Retorno tipo 4 NÃO OK (processado={processado}). {msg_motivos}")
    raise CaixaRetornoProcessamentoError(
        f"CAIXA retornou Tipo 4 não processado: processado={processado}; {msg_motivos}"
    )


def _log_retorno_tipo4(soap_response_xml: str) -> None:
    validar_retorno_tipo4(soap_response_xml, obrigatorio=False)


def _post_soap(xml: str, metodo: str) -> str:
    headers = {
        "Content-Type": "text/xml; charset=utf-8",
        "SOAPAction": SOAP_ACTION.get(metodo, metodo),
    }

    last_exc: Optional[Exception] = None

    for tentativa in range(MAX_RETRIES):
        try:
            r = requests.post(
                CAIXA_ENDPOINT,
                data=xml.encode("utf-8"),
                headers=headers,
                timeout=CAIXA_TIMEOUT_SECONDS,
                verify=False,
            )

            resp_text = r.text or ""
            _save_req_resp(metodo, xml, resp_text, r.status_code)

            fault = _extract_fault(resp_text)
            if fault:
                fault_code, fault_string = fault

                if metodo in ("GetList_Abertura", "GetList_Reiteracao") and _is_no_data_fault(fault_string):
                    print(f"CAIXA {metodo}: sem registros disponíveis (302).")
                    return _empty_getlist_response(metodo)

                if metodo in ("SetAceiteRecusa", "SetAtualizacao") and _is_no_data_fault(fault_string):
                    raise CaixaFinalError(
                        f"HTTP {r.status_code} - CAIXA não encontrou entrada para atualizar: {fault_code} - {fault_string}"
                    )

                if _is_final_fault(fault_string):
                    raise CaixaFinalError(
                        f"HTTP {r.status_code} - CAIXA final: {fault_code} - {fault_string}"
                    )

                raise CaixaSoapFault(r.status_code, fault_code, fault_string)

            if r.status_code >= 400:
                raise requests.HTTPError(f"HTTP {r.status_code}", response=r)

            return resp_text

        except CaixaFinalError:
            raise

        except Exception as e:
            last_exc = e
            print(f"CAIXA {metodo} erro ({tentativa + 1}/{MAX_RETRIES}).")

            if tentativa < MAX_RETRIES - 1:
                time.sleep(BACKOFF_SECONDS[min(tentativa, len(BACKOFF_SECONDS) - 1)])
            else:
                break

    if last_exc:
        raise last_exc
    raise Exception("Erro inesperado no _post_soap")


def buscar_aberturas(capturado: bool = False) -> str:
    xml = f"""<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
        xmlns:urn="urn:GSC_RF010_FornecedorExterno_V401_WS">
      <soapenv:Header>
        <urn:AuthenticationInfo>
          <urn:userName>{CAIXA_USER}</urn:userName>
          <urn:password>{CAIXA_PASSWORD}</urn:password>
        </urn:AuthenticationInfo>
      </soapenv:Header>
      <soapenv:Body>
        <urn:GetList_Abertura>
          <urn:Qualification>{CAIXA_QUALIFICATION}</urn:Qualification>
          <urn:Token>{CAIXA_TOKEN}</urn:Token>
          <urn:Capturado>{bool_tf(capturado)}</urn:Capturado>
          <urn:startRecord>0</urn:startRecord>
          <urn:maxLimit>100</urn:maxLimit>
        </urn:GetList_Abertura>
      </soapenv:Body>
    </soapenv:Envelope>"""

    print(f"Enviando XML para CAIXA (GetList_Abertura capturado={capturado})...")
    return _post_soap(xml, "GetList_Abertura")


def buscar_reiteracoes(capturado: bool = False) -> str:
    xml = f"""<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
        xmlns:urn="urn:GSC_RF010_FornecedorExterno_V401_WS">
      <soapenv:Header>
        <urn:AuthenticationInfo>
          <urn:userName>{CAIXA_USER}</urn:userName>
          <urn:password>{CAIXA_PASSWORD}</urn:password>
        </urn:AuthenticationInfo>
      </soapenv:Header>
      <soapenv:Body>
        <urn:GetList_Reiteracao>
          <urn:Qualification>{CAIXA_QUALIFICATION}</urn:Qualification>
          <urn:Token>{CAIXA_TOKEN}</urn:Token>
          <urn:Capturado>{bool_tf(capturado)}</urn:Capturado>
        </urn:GetList_Reiteracao>
      </soapenv:Body>
    </soapenv:Envelope>"""

    print(f"Enviando XML para CAIXA (GetList_Reiteracao capturado={capturado})...")
    return _post_soap(xml, "GetList_Reiteracao")


def set_aceite_recusa(
    no_req: str,
    no_wo: str,
    aceite: bool,
    chamado_fornecedor: str,
    descricao: str = "Chamado aceito. Vamos atender em breve.",
    previsaoatendimento: str = "",
    responsavelatendimento: str = "Equipe Triagem",
) -> str:
    agora = datetime.now().strftime("%Y%m%d%H%M%S")
    id_arquivo = uuid.uuid4().hex.upper()
    tipo_retorno = "1" if aceite else "2"

    # Layout Tipo 2: PREVISAOATENDIMENTO deve ser NUMERICO(14), formato aaaammddhhmmss.
    # Se for aceite e não vier previsão explícita, assume 48h a partir de agora.
    if aceite and not previsaoatendimento:
        previsaoatendimento = (datetime.now() + timedelta(hours=48)).strftime("%Y%m%d%H%M%S")
    elif not previsaoatendimento:
        previsaoatendimento = ""

    if aceite and not previsaoatendimento:
        previsaoatendimento = agora

    descricao = limitar_texto_caixa(descricao, limite=85)
    responsavelatendimento = limitar_texto_caixa(responsavelatendimento, limite=20)

    xml = f"""<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
        xmlns:urn="urn:GSC_RF010_FornecedorExterno_V401_WS">
      <soapenv:Header>
        <urn:AuthenticationInfo>
          <urn:userName>{CAIXA_USER}</urn:userName>
          <urn:password>{CAIXA_PASSWORD}</urn:password>
        </urn:AuthenticationInfo>
      </soapenv:Header>
      <soapenv:Body>
        <urn:SetAceiteRecusa>
          <urn:arquivoxml>

            <urn:info_arquivo>
              <urn:tipoarquivo>2</urn:tipoarquivo>
              <urn:idarquivo>{id_arquivo}</urn:idarquivo>
              <urn:datahorageracaoarquivo>{agora}</urn:datahorageracaoarquivo>
              <urn:comunicacao>2</urn:comunicacao>
            </urn:info_arquivo>

            <urn:info_fornecedor>
              <urn:idfornecedor>{CAIXA_ID_FORNECEDOR}</urn:idfornecedor>
              <urn:nomefornecedor>{CAIXA_NOME_FORNECEDOR}</urn:nomefornecedor>
            </urn:info_fornecedor>

            <urn:retorno>
              <urn:codigodobanco>104</urn:codigodobanco>

              <urn:chamado_caixa>
                <urn:no_req>{limpar_texto_xml(no_req)}</urn:no_req>
                <urn:no_wo>{limpar_texto_xml(no_wo)}</urn:no_wo>
                <urn:no_inc></urn:no_inc>
                <urn:no_crq></urn:no_crq>
              </urn:chamado_caixa>

              <urn:tipo_retorno>{tipo_retorno}</urn:tipo_retorno>
              <urn:chamado_fornecedor>{limpar_texto_xml(chamado_fornecedor)}</urn:chamado_fornecedor>
              <urn:previsaoatendimento>{limpar_texto_xml(previsaoatendimento)}</urn:previsaoatendimento>
              <urn:responsavelatendimento>{limpar_texto_xml(responsavelatendimento)}</urn:responsavelatendimento>
              <urn:descricao>{limpar_texto_xml(descricao)}</urn:descricao>
            </urn:retorno>

          </urn:arquivoxml>
        </urn:SetAceiteRecusa>
      </soapenv:Body>
    </soapenv:Envelope>"""

    print(f"Enviando XML para CAIXA (SetAceiteRecusa) aceite={aceite} idarquivo={id_arquivo}...")
    resp = _post_soap(xml, "SetAceiteRecusa")
    validar_retorno_tipo4(resp, obrigatorio=True)
    return resp


def _build_anexos_xml(anexos: Optional[List[Dict[str, str]]]) -> str:
    if not anexos:
        return ""

    anexos_validos = []
    for ax in anexos:
        nome = (ax.get("nome") or ax.get("filename") or "").strip()
        b64 = limpar_base64(ax.get("base64") or "")
        if not nome or not b64:
            continue

        tamanho = tamanho_base64_em_bytes(b64)
        if tamanho > MAX_ANEXO_CAIXA_BYTES:
            raise ValueError(
                f"Anexo {nome} possui {tamanho} bytes; limite CAIXA é {MAX_ANEXO_CAIXA_BYTES} bytes."
            )

        anexos_validos.append({"nome": nome, "base64": b64})

    if not anexos_validos:
        return ""

    anexos_validos = anexos_validos[:MAX_ANEXOS_CAIXA]

    parts = ["<urn:anexos>"]
    for i, ax in enumerate(anexos_validos, start=1):
        nome = limpar_texto_xml(ax.get("nome", f"arquivo_{i}.bin"))
        b64 = limpar_base64(ax.get("base64") or "")
        parts.append(f"<urn:nome_arquivo{i}>{nome}</urn:nome_arquivo{i}>")
        parts.append(f"<urn:anexo{i}>{b64}</urn:anexo{i}>")
    parts.append("</urn:anexos>")
    return "\n".join(parts)


def _normalizar_status_fornecedor(status_fornecedor: Optional[str]) -> Optional[str]:
    if status_fornecedor is None:
        return None

    raw = str(status_fornecedor).strip()
    if not raw:
        return None

    if raw in ("1", "2", "3", "4", "5"):
        return raw

    return STATUS_FORNECEDOR.get(raw.upper(), raw)


def enviar_atualizacao(
    no_req: str,
    no_wo: str,
    descricao: str,
    chamado_fornecedor: str,
    status_fornecedor: str | None = None,
    tipo_retorno: str | None = None,
    atendimento_inicio: str | None = None,
    atendimento_fim: str | None = None,
    agendamento_data: str | None = None,
    agendamento_contato: str | None = None,
    agendamento_telefone: str | None = None,
    tecnicoresponsavel: str | None = None,
    previsaoatendimento: str | None = None,
    anexos: Optional[List[Dict[str, str]]] = None,
) -> str:
    descricao = limpar_texto_xml(limitar_texto_caixa(descricao, limite=3900))
    agora = datetime.now().strftime("%Y%m%d%H%M%S")
    id_arquivo = uuid.uuid4().hex.upper()
    tipoarquivo = "3"

    status_fornecedor_norm = _normalizar_status_fornecedor(status_fornecedor)
    status_fornecedor_xml = ""
    if status_fornecedor_norm:
        status_fornecedor_xml = (
            f"<urn:status_fornecedor>{limpar_texto_xml(status_fornecedor_norm)}</urn:status_fornecedor>"
        )

    if tipo_retorno is None:
        tipo_retorno = "5" if status_fornecedor_norm == "5" else "1"

    if tipo_retorno == "5":
        atendimento_inicio = atendimento_inicio or agora
        atendimento_fim = atendimento_fim or agora
    else:
        atendimento_inicio = atendimento_inicio or ""
        atendimento_fim = atendimento_fim or ""

    agendamento_data = agendamento_data or ""
    agendamento_contato = limitar_texto_caixa(agendamento_contato or "", limite=20)
    agendamento_telefone = limitar_texto_caixa(agendamento_telefone or "", limite=20)
    tecnicoresponsavel = limitar_texto_caixa(tecnicoresponsavel or "", limite=20)
    previsaoatendimento = previsaoatendimento or ""

    anexos_xml = _build_anexos_xml(anexos)

    xml = f"""<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
        xmlns:urn="urn:GSC_RF010_FornecedorExterno_V401_WS">
      <soapenv:Header>
        <urn:AuthenticationInfo>
          <urn:userName>{CAIXA_USER}</urn:userName>
          <urn:password>{CAIXA_PASSWORD}</urn:password>
        </urn:AuthenticationInfo>
      </soapenv:Header>
      <soapenv:Body>
        <urn:SetAtualizacao>
          <urn:arquivoxml>

            <urn:info_arquivo>
              <urn:tipoarquivo>{tipoarquivo}</urn:tipoarquivo>
              <urn:idarquivo>{id_arquivo}</urn:idarquivo>
              <urn:datahorageracaoarquivo>{agora}</urn:datahorageracaoarquivo>
              <urn:comunicacao>2</urn:comunicacao>
            </urn:info_arquivo>

            <urn:info_fornecedor>
              <urn:idfornecedor>{CAIXA_ID_FORNECEDOR}</urn:idfornecedor>
              <urn:nomefornecedor>{CAIXA_NOME_FORNECEDOR}</urn:nomefornecedor>
            </urn:info_fornecedor>

            <urn:retorno>
              <urn:codigodobanco>104</urn:codigodobanco>

              <urn:chamado_caixa>
                <urn:no_req>{limpar_texto_xml(no_req)}</urn:no_req>
                <urn:no_wo>{limpar_texto_xml(no_wo)}</urn:no_wo>
                <urn:no_inc></urn:no_inc>
                <urn:no_crq></urn:no_crq>
              </urn:chamado_caixa>

              <urn:tipo_retorno>{limpar_texto_xml(tipo_retorno)}</urn:tipo_retorno>
              <urn:descricao>{descricao}</urn:descricao>
              <urn:chamado_fornecedor>{limpar_texto_xml(chamado_fornecedor)}</urn:chamado_fornecedor>
              {status_fornecedor_xml}
            </urn:retorno>

            <urn:agendamento>
              <urn:data>{limpar_texto_xml(agendamento_data)}</urn:data>
              <urn:contato>{limpar_texto_xml(agendamento_contato)}</urn:contato>
              <urn:telefone>{limpar_texto_xml(agendamento_telefone)}</urn:telefone>
            </urn:agendamento>

            <urn:atendimento>
              <urn:data_inicio>{limpar_texto_xml(atendimento_inicio)}</urn:data_inicio>
              <urn:data_fim>{limpar_texto_xml(atendimento_fim)}</urn:data_fim>
              <urn:rat></urn:rat>
              <urn:tecnicoresponsavel>{limpar_texto_xml(tecnicoresponsavel)}</urn:tecnicoresponsavel>
              <urn:numero_serie></urn:numero_serie>
              <urn:previsaoatendimento>{limpar_texto_xml(previsaoatendimento)}</urn:previsaoatendimento>
            </urn:atendimento>

            <urn:servicos>
              <urn:codigo1></urn:codigo1>
              <urn:descricao1></urn:descricao1>
              <urn:valor1></urn:valor1>
            </urn:servicos>

            {anexos_xml}

          </urn:arquivoxml>
        </urn:SetAtualizacao>
      </soapenv:Body>
    </soapenv:Envelope>"""

    print(
        f"Enviando XML para CAIXA (SetAtualizacao) idarquivo={id_arquivo} "
        f"tipo_retorno={tipo_retorno} status={status_fornecedor_norm or ''} anexos={len(anexos or [])}..."
    )
    resp = _post_soap(xml, "SetAtualizacao")
    validar_retorno_tipo4(resp, obrigatorio=True)
    return resp
