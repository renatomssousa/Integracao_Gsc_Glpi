# -*- coding: utf-8 -*-
from pathlib import Path

import glpi_client
import glpi_updates
import processors


MAX_ARQUIVOS_ABERTURA = 10
MAX_ARQUIVOS_REITERACAO = 10


def descobrir_ticket_id_reiteracao(r):
    chamado_fornecedor = (r.get("chamado_fornecedor") or "").strip()
    if chamado_fornecedor.startswith("GLPI-"):
        try:
            return int(chamado_fornecedor.replace("GLPI-", "").strip())
        except Exception:
            pass

    req = (r.get("no_req") or "").strip()
    wo = (r.get("no_wo") or "").strip()
    if not req or not wo:
        return None

    return glpi_updates.buscar_ticket_por_req_wo(req, wo)


def reprocessar_aberturas():
    arquivos = sorted(
        Path("logs").glob("*GetList_Abertura*_resp.xml"),
        key=lambda p: p.stat().st_mtime,
        reverse=True
    )[:MAX_ARQUIVOS_ABERTURA]

    print(f"[ABERTURA] arquivos encontrados: {len(arquivos)}")

    for arq in reversed(arquivos):
        xml = arq.read_text(encoding="utf-8", errors="ignore")
        chamados = processors.extrair_chamados_abertura(xml)

        for ch in chamados:
            anexos = ch.get("anexos") or []
            if not anexos:
                continue

            req = (ch.get("no_req") or "").strip()
            wo = (ch.get("no_wo") or "").strip()
            ticket_id = glpi_updates.buscar_ticket_por_req_wo(req, wo)

            print(f"[ABERTURA] REQ={req} WO={wo} ticket={ticket_id} anexos={len(anexos)} arquivo={arq.name}")

            if not ticket_id:
                print("  -> ticket nao encontrado no state.json")
                continue

            for ax in anexos:
                nome = (ax.get("nome") or "").strip()
                b64 = (ax.get("base64") or "").strip()
                if not nome or not b64:
                    continue

                try:
                    fid = glpi_client.adicionar_followup_com_anexo(
                        ticket_id=ticket_id,
                        texto="Arquivo anexado automaticamente (origem: CAIXA)",
                        filename=nome,
                        base64_file=b64,
                    )
                    print(f"  -> OK followup={fid} arquivo={nome}")
                except Exception as e:
                    print(f"  -> ERRO arquivo={nome}: {e}")


def reprocessar_reiteracoes():
    arquivos = sorted(
        Path("logs").glob("*GetList_Reiteracao*_resp.xml"),
        key=lambda p: p.stat().st_mtime,
        reverse=True
    )[:MAX_ARQUIVOS_REITERACAO]

    print(f"[REITERACAO] arquivos encontrados: {len(arquivos)}")

    for arq in reversed(arquivos):
        xml = arq.read_text(encoding="utf-8", errors="ignore")
        reiteracoes = processors.extrair_reiteracoes(xml)

        for r in reiteracoes:
            anexos = r.get("anexos") or []
            if not anexos:
                continue

            req = (r.get("no_req") or "").strip()
            wo = (r.get("no_wo") or "").strip()
            ticket_id = descobrir_ticket_id_reiteracao(r)

            print(f"[REITERACAO] REQ={req} WO={wo} ticket={ticket_id} anexos={len(anexos)} arquivo={arq.name}")

            if not ticket_id:
                print("  -> ticket nao encontrado")
                continue

            for ax in anexos:
                nome = (ax.get("nome") or "").strip()
                b64 = (ax.get("base64") or "").strip()
                if not nome or not b64:
                    continue

                try:
                    fid = glpi_client.adicionar_followup_com_anexo(
                        ticket_id=ticket_id,
                        texto="Arquivo recebido da CAIXA",
                        filename=nome,
                        base64_file=b64,
                    )
                    print(f"  -> OK followup={fid} arquivo={nome}")
                except Exception as e:
                    print(f"  -> ERRO arquivo={nome}: {e}")


if __name__ == "__main__":
    glpi_client.init_session()
    try:
        reprocessar_aberturas()
        reprocessar_reiteracoes()
    finally:
        glpi_client.kill_session()
