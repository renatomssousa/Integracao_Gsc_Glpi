# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import time

import caixa_client
import glpi_client
import glpi_updates
import processors
from anexos import extrair_anexos_do_xml
from utils import html_para_texto

POLL_INTERVAL_SECONDS = 30
ENABLE_GLPI_ANEXOS_PARA_CAIXA = os.getenv("ENABLE_GLPI_ANEXOS_PARA_CAIXA", "0").strip() in ("1", "true", "True")

PREFIXOS_INTERNOS = (
    "Reiteracao recebida da CAIXA",
    "Arquivo recebido da CAIXA",
    "Arquivo anexado automaticamente (origem: CAIXA)",
    "Integracao:",
)


def _detectar_finalizacao_caixa(texto: str) -> str | None:
    s = (texto or "").lower()

    if "cancel" in s or "cancelado" in s or "cancelada" in s:
        return "CANCELADO"

    if "conclu" in s or "finaliz" in s or "encerr" in s or "fechad" in s:
        return "CONCLUIDO"

    return None


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


def executar_loop() -> None:
    glpi_client.init_session()
    print("Integração CAIXA <-> GLPI iniciada")

    while True:
        try:
            # 1) ABERTURAS (CAIXA -> GLPI)
            print("Buscando aberturas na CAIXA...")
            xml_aberturas = caixa_client.buscar_aberturas(capturado=True)
            aberturas = processors.extrair_chamados_abertura(xml_aberturas)
            print(f"Aberturas retornadas pela CAIXA: {len(aberturas)}")

            for ch in aberturas:
                req = (ch.get("no_req") or "").strip()
                wo = (ch.get("no_wo") or "").strip()

                if not req or not wo:
                    continue

                ticket_existente = glpi_updates.buscar_ticket_por_req_wo(req, wo)
                if ticket_existente:
                    print(f"REQ/WO já mapeada no GLPI. Ticket existente: {ticket_existente}")
                    continue

                ticket_id = glpi_client.criar_ticket(ch["titulo"], ch["descricao"], itilcategories_id=7)
                print(f"Ticket criado no GLPI: {ticket_id}")

                glpi_updates.registrar_mapeamento_req_wo(req, wo, ticket_id)

                try:
                    caixa_client.set_aceite_recusa(
                        no_req=req,
                        no_wo=wo,
                        aceite=True,
                        chamado_fornecedor=f"GLPI-{ticket_id}",
                        descricao="Chamado aceito. Vamos atender em breve.",
                    )
                    print(f"Aceite automático enviado para REQ={req} WO={wo}")
                except Exception as e:
                    print(f"WARN: Falha ao enviar aceite automático REQ={req} WO={wo}: {e}")

                for ax in ch.get("anexos", []):
                    nome = (ax.get("nome") or "").strip()
                    b64 = (ax.get("base64") or "").strip()
                    if not nome or not b64:
                        continue

                    _adicionar_followup_com_anexo_interno(
                        ticket_id=ticket_id,
                        texto="Arquivo anexado automaticamente (origem: CAIXA)",
                        filename=nome,
                        base64_file=b64,
                    )

            # 2) REITERAÇÕES (CAIXA -> GLPI)
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

                if not req or not wo:
                    continue

                if glpi_updates.reiteracao_ja_processada(req, wo, id_arquivo=id_arquivo, descricao=desc):
                    continue

                ticket_id = None

                if chamado_fornecedor.startswith("GLPI-"):
                    try:
                        ticket_id = int(chamado_fornecedor.replace("GLPI-", "").strip())
                    except Exception:
                        ticket_id = None

                if not ticket_id:
                    ticket_id = glpi_updates.buscar_ticket_por_req_wo(req, wo)

                if not ticket_id:
                    print(f"WARN: Ticket não encontrado no GLPI para REQ={req} WO={wo}.")
                    continue

                _adicionar_followup_publico_interno(
                    ticket_id,
                    f"Reiteração recebida da CAIXA\n\n{desc or '(sem descrição)'}",
                )

                anexos = extrair_anexos_do_xml(r) or []
                for ax in anexos:
                    filename = (ax.get("filename") or "").strip()
                    b64 = (ax.get("base64") or "").strip()
                    if not filename or not b64:
                        continue

                    _adicionar_followup_com_anexo_interno(
                        ticket_id=ticket_id,
                        texto="Arquivo recebido da CAIXA",
                        filename=filename,
                        base64_file=b64,
                    )

                final = _detectar_finalizacao_caixa(desc)
                if final:
                    glpi_updates.bloquear_req_wo(req, wo, ticket_id, f"CAIXA informou {final}: {desc[:200]}")
                    try:
                        if final == "CONCLUIDO":
                            glpi_client.atualizar_status_ticket(ticket_id, 5)
                        else:
                            glpi_client.atualizar_status_ticket(ticket_id, 6)
                    except Exception:
                        pass

                    _adicionar_followup_publico_interno(
                        ticket_id,
                        f"Integração: REQ/WO bloqueada porque a CAIXA informou {final}. A partir de agora não enviaremos mais atualizações para a CAIXA.",
                    )

                glpi_updates.marcar_reiteracao_processada(req, wo, id_arquivo=id_arquivo, descricao=desc)
                print("Reiteração aplicada no GLPI.")

            # 3) GLPI -> CAIXA (FOLLOWUPS + STATUS + ANEXOS)
            print("Buscando tickets CAIXA no GLPI para enviar atualizações...")
            tickets = glpi_client.buscar_tickets_caixa_por_categoria(7)
            print(f"{len(tickets)} ticket(s) encontrados")

            for t in tickets:
                ticket_id = int(t["2"])

                mapeamento = glpi_updates.buscar_req_wo_por_ticket(ticket_id)
                if not mapeamento:
                    continue

                no_req = mapeamento["no_req"]
                no_wo = mapeamento["no_wo"]

                if glpi_updates.req_wo_esta_bloqueado(no_req, no_wo):
                    continue

                # FOLLOWUPS (GLPI -> CAIXA)
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

                    print(f"Enviando followup {fid} do ticket {ticket_id} para CAIXA")

                    try:
                        caixa_client.enviar_atualizacao(
                            no_req=no_req,
                            no_wo=no_wo,
                            descricao=texto,
                            chamado_fornecedor=f"GLPI-{ticket_id}",
                            tipo_retorno="1",
                        )
                        glpi_updates.marcar_followup_enviado(ticket_id, fid)

                    except caixa_client.CaixaFinalError as e:
                        print(f"FINAL: {e}")
                        glpi_updates.marcar_followup_enviado(ticket_id, fid)
                        glpi_updates.bloquear_req_wo(no_req, no_wo, ticket_id, str(e))
                        try:
                            glpi_client.atualizar_status_ticket(ticket_id, 5)
                        except Exception:
                            pass
                        _adicionar_followup_publico_interno(
                            ticket_id,
                            "Integração: CAIXA retornou erro FINAL (ex.: cancelado/finalizado). REQ/WO bloqueada; não enviaremos mais atualizações.",
                        )
                        break

                    except Exception as e:
                        print(f"Erro enviando followup {fid} do ticket {ticket_id}: {e}")

                if glpi_updates.req_wo_esta_bloqueado(no_req, no_wo):
                    continue

                # ANEXOS (GLPI -> CAIXA)
                if ENABLE_GLPI_ANEXOS_PARA_CAIXA:
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

                            caixa_client.enviar_atualizacao(
                                no_req=no_req,
                                no_wo=no_wo,
                                descricao=f"Anexo enviado pelo GLPI: {filename}",
                                chamado_fornecedor=f"GLPI-{ticket_id}",
                                tipo_retorno="1",
                                anexos=[{"nome": filename, "base64": b64}],
                            )
                            glpi_updates.marcar_documento_enviado(ticket_id, doc_id)

                        except caixa_client.CaixaFinalError as e:
                            print(f"FINAL: {e}")
                            glpi_updates.marcar_documento_enviado(ticket_id, doc_id)
                            glpi_updates.bloquear_req_wo(no_req, no_wo, ticket_id, str(e))
                            try:
                                glpi_client.atualizar_status_ticket(ticket_id, 5)
                            except Exception:
                                pass
                            _adicionar_followup_publico_interno(
                                ticket_id,
                                "Integração: CAIXA retornou erro FINAL ao enviar anexo. REQ/WO bloqueada; não enviaremos mais atualizações.",
                            )
                            break
                        except Exception as e:
                            print(f"Erro enviando anexo Document/{doc_id} do ticket {ticket_id}: {e}")

                if glpi_updates.req_wo_esta_bloqueado(no_req, no_wo):
                    continue

                # STATUS (GLPI -> CAIXA)
                status_glpi = glpi_client.buscar_status_ticket(ticket_id)
                if not status_glpi:
                    continue

                mapa_status = {
                    "solucionado": "CONCLUIDO",
                    "fechado": "CONCLUIDO",
                    "pendente": "PENDENTE",
                }

                status_caixa = mapa_status.get(status_glpi.lower())
                if not status_caixa:
                    continue

                if glpi_updates.status_ja_enviado(ticket_id, status_caixa):
                    continue

                print(f"Enviando status {status_caixa} do ticket {ticket_id} para CAIXA")

                if status_caixa == "CONCLUIDO":
                    tipo_retorno = "5"
                    status_fornecedor = "CONCLUIDO"
                else:
                    tipo_retorno = "1"
                    status_fornecedor = None

                try:
                    caixa_client.enviar_atualizacao(
                        no_req=no_req,
                        no_wo=no_wo,
                        descricao=f"Status alterado para {status_caixa} no GLPI",
                        chamado_fornecedor=f"GLPI-{ticket_id}",
                        status_fornecedor=status_fornecedor,
                        tipo_retorno=tipo_retorno,
                    )
                    glpi_updates.marcar_status_enviado(ticket_id, status_caixa)

                except caixa_client.CaixaFinalError as e:
                    print(f"FINAL: {e}")
                    glpi_updates.marcar_status_enviado(ticket_id, status_caixa)
                    glpi_updates.bloquear_req_wo(no_req, no_wo, ticket_id, str(e))
                    try:
                        glpi_client.atualizar_status_ticket(ticket_id, 5)
                    except Exception:
                        pass
                    _adicionar_followup_publico_interno(
                        ticket_id,
                        "Integração: CAIXA retornou erro FINAL no envio de status. REQ/WO bloqueada; não enviaremos mais atualizações.",
                    )

                except Exception as e:
                    print(f"Erro enviando status do ticket {ticket_id}: {e}")

            print("Ciclo finalizado. Aguardando...")
            time.sleep(POLL_INTERVAL_SECONDS)

        except KeyboardInterrupt:
            print("Interrompido pelo usuário.")
            break
        except Exception as e:
            print(f"Erro no loop: {e}")
            time.sleep(POLL_INTERVAL_SECONDS)

    glpi_client.kill_session()