# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import time
from datetime import datetime, timedelta

from . import caixa_client
from . import glpi_client
from . import glpi_updates
from . import processors
from . import config
from .anexos import extrair_anexos_do_xml
from .utils import html_para_texto, limitar_texto_caixa, tamanho_base64_em_bytes

POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", str(getattr(config, "POLL_INTERVAL_SECONDS", 60))))
ENABLE_GLPI_ANEXOS_PARA_CAIXA = os.getenv("ENABLE_GLPI_ANEXOS_PARA_CAIXA", "1" if getattr(config, "ENABLE_GLPI_ANEXOS_PARA_CAIXA", False) else "0").strip() in ("1", "true", "True")
BUSCAR_ABERTURAS_JA_CAPTURADAS = os.getenv("BUSCAR_ABERTURAS_JA_CAPTURADAS", "1" if getattr(config, "BUSCAR_ABERTURAS_JA_CAPTURADAS", True) else "0").strip() in ("1", "true", "True")
ITILCATEGORY_CAIXA = int(os.getenv("GLPI_CAIXA_ITILCATEGORY_ID", str(getattr(config, "GLPI_CATEGORIA_ID", 874))))
MAX_ANEXO_CAIXA_BYTES = 10 * 1024 * 1024

PREFIXOS_INTERNOS = (
    "Reiteracao recebida da CAIXA",
    "Reiteração recebida da CAIXA",
    "Arquivo recebido da CAIXA",
    "Arquivo anexado automaticamente (origem: CAIXA)",
    "Integracao:",
    "Integração:",
)


def _registrar_followup_interno(ticket_id: int, followup_id: int) -> None:
    try:
        glpi_updates.marcar_followup_enviado(ticket_id, followup_id)
    except Exception:
        pass


def _adicionar_followup_publico_interno(ticket_id: int, texto: str) -> int:
    fid = glpi_client.adicionar_followup_publico(ticket_id, texto)
    _registrar_followup_interno(ticket_id, fid)
    return fid


def _adicionar_followup_com_anexo_interno(ticket_id: int, texto: str, filename: str, base64_file: str) -> int:
    fid = glpi_client.adicionar_followup_com_anexo(ticket_id, texto, filename, base64_file)
    _registrar_followup_interno(ticket_id, fid)
    return fid


def _previsao_padrao_caixa() -> str:
    # A CAIXA exige aaaammddhhmmss. Usamos 48h como previsão operacional segura.
    return (datetime.now() + timedelta(hours=48)).strftime("%Y%m%d%H%M%S")


def _resolver_ticket_id(req: str, wo: str, chamado_fornecedor: str | None = None) -> int | None:
    chamado_fornecedor = (chamado_fornecedor or "").strip()

    if chamado_fornecedor.upper().startswith("GLPI-"):
        try:
            return int(chamado_fornecedor.upper().replace("GLPI-", "").strip())
        except Exception:
            pass

    return glpi_updates.buscar_ticket_por_req_wo(req, wo)


def _anexo_dentro_limite_caixa(filename: str, b64: str) -> bool:
    try:
        tamanho = tamanho_base64_em_bytes(b64)
    except Exception:
        print(f"WARN: Anexo {filename} ignorado: base64 inválido.")
        return False

    if tamanho > MAX_ANEXO_CAIXA_BYTES:
        print(f"WARN: Anexo {filename} ignorado: {tamanho} bytes > 10MB.")
        return False

    return True


def _processar_aberturas(capturado: bool) -> None:
    print(f"Buscando aberturas na CAIXA... capturado={capturado}")
    xml_aberturas = caixa_client.buscar_aberturas(capturado=capturado)
    aberturas = processors.extrair_chamados_abertura(xml_aberturas)
    print(f"Aberturas retornadas pela CAIXA capturado={capturado}: {len(aberturas)}")

    for ch in aberturas:
        req = (ch.get("no_req") or "").strip()
        wo = (ch.get("no_wo") or "").strip()

        if not req or not wo:
            continue

        ticket_existente = glpi_updates.buscar_ticket_por_req_wo(req, wo)
        if ticket_existente:
            print(f"REQ/WO já mapeada no GLPI. REQ={req} WO={wo} Ticket={ticket_existente}")
            continue

        ticket_id = glpi_client.criar_ticket(ch["titulo"], ch["descricao"], itilcategories_id=ITILCATEGORY_CAIXA)
        print(f"Ticket criado no GLPI: {ticket_id} para REQ={req} WO={wo}")

        glpi_updates.registrar_mapeamento_req_wo(req, wo, ticket_id)

        try:
            caixa_client.set_aceite_recusa(
                no_req=req,
                no_wo=wo,
                aceite=True,
                chamado_fornecedor=f"GLPI-{ticket_id}",
                descricao="Chamado aceito. Vamos atender em breve.",
                previsaoatendimento=_previsao_padrao_caixa(),
                responsavelatendimento="Equipe Triagem",
            )
            print(f"Aceite automático enviado para REQ={req} WO={wo}")
        except caixa_client.CaixaFinalError as e:
            print(f"FINAL no aceite automático REQ={req} WO={wo}: {e}")
            _adicionar_followup_publico_interno(
                ticket_id,
                f"Integração: ticket criado a partir de abertura capturada, mas o aceite automático foi recusado pela CAIXA. Detalhe: {e}",
            )
        except Exception as e:
            print(f"WARN: Falha ao enviar aceite automático REQ={req} WO={wo}: {e}")

        for ax in ch.get("anexos", []):
            nome = (ax.get("nome") or ax.get("filename") or "").strip()
            b64 = (ax.get("base64") or "").strip()
            if not nome or not b64:
                continue

            _adicionar_followup_com_anexo_interno(
                ticket_id=ticket_id,
                texto="Arquivo anexado automaticamente (origem: CAIXA)",
                filename=nome,
                base64_file=b64,
            )


def _processar_reiteracoes() -> None:
    print("Buscando reiterações na CAIXA...")
    xml_reit = caixa_client.buscar_reiteracoes(capturado=False)
    reiteracoes = processors.extrair_reiteracoes(xml_reit)
    print(f"Reiterações retornadas pela CAIXA: {len(reiteracoes)}")

    for r in reiteracoes:
        req = (r.get("no_req") or "").strip()
        wo = (r.get("no_wo") or "").strip()
        desc = (r.get("descricao") or "").strip()
        id_arquivo = (r.get("id_arquivo") or "").strip()
        chamado_fornecedor = (r.get("chamado_fornecedor") or "").strip()
        retornocaixa = (r.get("retornocaixa") or "").strip()

        if not req or not wo:
            continue

        if glpi_updates.reiteracao_ja_processada(req, wo, id_arquivo=id_arquivo, descricao=desc):
            continue

        ticket_id = _resolver_ticket_id(req, wo, chamado_fornecedor)
        if not ticket_id:
            print(f"WARN: Ticket não encontrado no GLPI para REQ={req} WO={wo}.")
            continue

        # retornocaixa: 1=reabertura, 2=cancelamento, 3=comentário.
        if retornocaixa == "1":
            glpi_updates.remover_bloqueio_req_wo(req, wo)
            try:
                glpi_client.atualizar_status_ticket(ticket_id, 2)  # Em atendimento
            except Exception:
                pass

            _adicionar_followup_publico_interno(
                ticket_id,
                f"Reiteração recebida da CAIXA - REABERTURA\n\n{desc or '(sem descrição)'}",
            )

        elif retornocaixa == "2":
            glpi_updates.bloquear_req_wo(req, wo, ticket_id, f"CAIXA informou cancelamento: {desc[:200]}")
            try:
                glpi_client.atualizar_status_ticket(ticket_id, 6)  # Fechado
            except Exception:
                pass

            _adicionar_followup_publico_interno(
                ticket_id,
                f"Reiteração recebida da CAIXA - CANCELAMENTO\n\n{desc or '(sem descrição)'}\n\nIntegração: REQ/WO bloqueada; não enviaremos novas atualizações para a CAIXA.",
            )

        else:
            _adicionar_followup_publico_interno(
                ticket_id,
                f"Reiteração recebida da CAIXA\n\n{desc or '(sem descrição)'}",
            )

        anexos = extrair_anexos_do_xml(r) or []
        for ax in anexos:
            filename = (ax.get("filename") or ax.get("nome") or "").strip()
            b64 = (ax.get("base64") or "").strip()
            if not filename or not b64:
                continue

            _adicionar_followup_com_anexo_interno(
                ticket_id=ticket_id,
                texto="Arquivo recebido da CAIXA",
                filename=filename,
                base64_file=b64,
            )

        glpi_updates.marcar_reiteracao_processada(req, wo, id_arquivo=id_arquivo, descricao=desc)
        print("Reiteração aplicada no GLPI.")


def _enviar_followups_para_caixa(ticket_id: int, no_req: str, no_wo: str) -> None:
    followups = glpi_client.listar_followups(ticket_id)

    for f in followups:
        try:
            fid = int(f["id"])
        except Exception:
            continue

        if glpi_updates.followup_ja_enviado(ticket_id, fid):
            continue

        texto = html_para_texto(f.get("content") or "")
        if not texto:
            glpi_updates.marcar_followup_enviado(ticket_id, fid)
            continue

        if texto.startswith(PREFIXOS_INTERNOS):
            glpi_updates.marcar_followup_enviado(ticket_id, fid)
            continue

        texto_caixa = limitar_texto_caixa(texto, limite=3900)
        print(f"Enviando followup {fid} do ticket {ticket_id} para CAIXA")

        try:
            caixa_client.enviar_atualizacao(
                no_req=no_req,
                no_wo=no_wo,
                descricao=texto_caixa,
                chamado_fornecedor=f"GLPI-{ticket_id}",
                tipo_retorno="1",
                status_fornecedor="1",
            )
            glpi_updates.marcar_followup_enviado(ticket_id, fid)

        except caixa_client.CaixaFinalError as e:
            print(f"FINAL: {e}")
            glpi_updates.bloquear_req_wo(no_req, no_wo, ticket_id, str(e))
            _adicionar_followup_publico_interno(
                ticket_id,
                "Integração: CAIXA retornou erro final ao enviar nota. REQ/WO bloqueada; não enviaremos mais atualizações.",
            )
            break

        except Exception as e:
            print(f"Erro enviando followup {fid} do ticket {ticket_id}: {e}")


def _enviar_anexos_para_caixa(ticket_id: int, no_req: str, no_wo: str) -> None:
    if not ENABLE_GLPI_ANEXOS_PARA_CAIXA:
        return

    docs_link = glpi_client.listar_documentos_ticket(ticket_id)

    for link in docs_link:
        doc_id = link.get("documents_id") or link.get("id") or link.get("document_id")
        try:
            doc_id = int(doc_id)
        except Exception:
            continue

        if glpi_updates.documento_ja_enviado(ticket_id, doc_id):
            continue

        filename = f"documento_{doc_id}"
        try:
            meta = glpi_client.buscar_metadados_documento(doc_id)
            if meta and isinstance(meta, dict):
                filename = (meta.get("filename") or meta.get("name") or filename).strip()
        except Exception:
            pass

        try:
            b64 = glpi_client.baixar_documento_base64(doc_id)

            if not _anexo_dentro_limite_caixa(filename, b64):
                _adicionar_followup_publico_interno(
                    ticket_id,
                    f"Integração: anexo '{filename}' não foi enviado à CAIXA porque excede o limite de 10 MB ou está inválido.",
                )
                glpi_updates.marcar_documento_enviado(ticket_id, doc_id)
                continue

            caixa_client.enviar_atualizacao(
                no_req=no_req,
                no_wo=no_wo,
                descricao=limitar_texto_caixa(f"Anexo enviado pelo GLPI: {filename}", limite=3900),
                chamado_fornecedor=f"GLPI-{ticket_id}",
                tipo_retorno="1",
                status_fornecedor="1",
                anexos=[{"nome": filename, "base64": b64}],
            )
            glpi_updates.marcar_documento_enviado(ticket_id, doc_id)

        except caixa_client.CaixaFinalError as e:
            print(f"FINAL: {e}")
            glpi_updates.bloquear_req_wo(no_req, no_wo, ticket_id, str(e))
            _adicionar_followup_publico_interno(
                ticket_id,
                "Integração: CAIXA retornou erro final ao enviar anexo. REQ/WO bloqueada; não enviaremos mais atualizações.",
            )
            break
        except Exception as e:
            print(f"Erro enviando anexo Document/{doc_id} do ticket {ticket_id}: {e}")


def _mapear_status_glpi_para_caixa(status_glpi: str):
    status = (status_glpi or "").strip().lower()

    if status in ("solucionado", "fechado"):
        return {
            "status_caixa": "CONCLUIDO",
            "tipo_retorno": "5",
            "status_fornecedor": "5",
            "descricao": "Status alterado para concluído no GLPI.",
        }

    if status == "pendente":
        return {
            "status_caixa": "PENDENTE",
            "tipo_retorno": "3",
            "status_fornecedor": "4",
            "descricao": "Status alterado para pendente no GLPI.",
        }

    if status == "em atendimento":
        return {
            "status_caixa": "EM_ANALISE",
            "tipo_retorno": "1",
            "status_fornecedor": "1",
            "descricao": "Status alterado para em atendimento no GLPI.",
        }

    return None


def _enviar_status_para_caixa(ticket_id: int, no_req: str, no_wo: str) -> None:
    status_glpi = glpi_client.buscar_status_ticket(ticket_id)
    if not status_glpi:
        return

    status_map = _mapear_status_glpi_para_caixa(status_glpi)
    if not status_map:
        return

    status_caixa = status_map["status_caixa"]
    if glpi_updates.status_ja_enviado(ticket_id, status_caixa):
        return

    print(f"Enviando status {status_caixa} do ticket {ticket_id} para CAIXA")

    try:
        caixa_client.enviar_atualizacao(
            no_req=no_req,
            no_wo=no_wo,
            descricao=status_map["descricao"],
            chamado_fornecedor=f"GLPI-{ticket_id}",
            status_fornecedor=status_map["status_fornecedor"],
            tipo_retorno=status_map["tipo_retorno"],
        )
        glpi_updates.marcar_status_enviado(ticket_id, status_caixa)

    except caixa_client.CaixaFinalError as e:
        print(f"FINAL: {e}")
        glpi_updates.bloquear_req_wo(no_req, no_wo, ticket_id, str(e))
        _adicionar_followup_publico_interno(
            ticket_id,
            "Integração: CAIXA retornou erro final no envio de status. REQ/WO bloqueada; não enviaremos mais atualizações.",
        )

    except Exception as e:
        print(f"Erro enviando status do ticket {ticket_id}: {e}")


def _processar_glpi_para_caixa() -> None:
    print("Buscando tickets CAIXA no GLPI para enviar atualizações...")
    tickets = glpi_client.buscar_tickets_caixa_por_categoria(ITILCATEGORY_CAIXA)
    print(f"{len(tickets)} ticket(s) encontrados")

    for t in tickets:
        try:
            ticket_id = int(t["2"])
        except Exception:
            continue

        mapeamento = glpi_updates.buscar_req_wo_por_ticket(ticket_id)
        if not mapeamento:
            continue

        no_req = mapeamento["no_req"]
        no_wo = mapeamento["no_wo"]

        if glpi_updates.req_wo_esta_bloqueado(no_req, no_wo):
            continue

        _enviar_followups_para_caixa(ticket_id, no_req, no_wo)

        if glpi_updates.req_wo_esta_bloqueado(no_req, no_wo):
            continue

        _enviar_anexos_para_caixa(ticket_id, no_req, no_wo)

        if glpi_updates.req_wo_esta_bloqueado(no_req, no_wo):
            continue

        _enviar_status_para_caixa(ticket_id, no_req, no_wo)


def executar_loop() -> None:
    glpi_client.init_session()
    print("Integração CAIXA <-> GLPI iniciada")
    print(f"STATE_FILE em uso: {getattr(glpi_updates, 'STATE_FILE', 'state.json')}")
    print(f"Intervalo do loop: {POLL_INTERVAL_SECONDS}s")

    while True:
        try:
            # 1) ABERTURAS NOVAS (CAIXA -> GLPI)
            _processar_aberturas(capturado=False)

            # 1.1) ABERTURAS JÁ CAPTURADAS (recuperação)
            # Mantido porque você quer conferir se algo foi lido pela CAIXA, mas não virou ticket no GLPI.
            if BUSCAR_ABERTURAS_JA_CAPTURADAS:
                _processar_aberturas(capturado=True)

            # 2) REITERAÇÕES (CAIXA -> GLPI)
            _processar_reiteracoes()

            # 3) GLPI -> CAIXA (FOLLOWUPS + ANEXOS + STATUS)
            _processar_glpi_para_caixa()

            print("Ciclo finalizado. Aguardando...")
            time.sleep(POLL_INTERVAL_SECONDS)

        except KeyboardInterrupt:
            print("Interrompido pelo usuário.")
            break
        except Exception as e:
            print(f"Erro no loop: {e}")
            time.sleep(POLL_INTERVAL_SECONDS)

    glpi_client.kill_session()


if __name__ == "__main__":
    executar_loop()
