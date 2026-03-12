# -*- coding: utf-8 -*-
import base64
import glpi_client

TICKET_ID = 454  # troque para um ticket de teste seu

conteudo = b"Teste de anexo vindo da CAIXA"
b64 = base64.b64encode(conteudo).decode("ascii")

try:
    glpi_client.init_session()

    followup_id = glpi_client.adicionar_followup_com_anexo(
        ticket_id=TICKET_ID,
        texto="Arquivo recebido da CAIXA",
        filename="teste_caixa.txt",
        base64_file=b64,
    )

    print(f"OK - followup criado: {followup_id}")

finally:
    glpi_client.kill_session()
