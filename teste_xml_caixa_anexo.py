# -*- coding: utf-8 -*-
import base64

import glpi_client
import processors
from anexos import extrair_anexos_do_xml

TICKET_ID = 454  # troque para um ticket de teste

conteudo = b"Arquivo fake vindo da CAIXA"
b64 = base64.b64encode(conteudo).decode("ascii")

xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
                  xmlns:urn="urn:GSC_RF010_FornecedorExterno_V401_WS">
  <soapenv:Body>
    <urn:GetList_ReiteracaoResponse>
      <urn:getListValues>
        <urn:info_arquivo>
          <urn:idarquivo>TESTE123</urn:idarquivo>
        </urn:info_arquivo>

        <urn:info_fornecedor>
          <urn:chamado_fornecedor>GLPI-{TICKET_ID}</urn:chamado_fornecedor>
        </urn:info_fornecedor>

        <urn:complemento>
          <urn:chamado_caixa>
            <urn:no_req>REQTESTE123</urn:no_req>
            <urn:no_wo>WOTESTE123</urn:no_wo>
          </urn:chamado_caixa>
          <urn:descricao>Teste de reiteracao com anexo</urn:descricao>
        </urn:complemento>

        <urn:anexos>
          <urn:nome_arquivo1>arquivo_caixa.txt</urn:nome_arquivo1>
          <urn:anexo1>{b64}</urn:anexo1>
        </urn:anexos>

        <urn:tiporequisicao>
          <urn:idreq>1</urn:idreq>
          <urn:nomereq>Teste</urn:nomereq>
        </urn:tiporequisicao>
      </urn:getListValues>
    </urn:GetList_ReiteracaoResponse>
  </soapenv:Body>
</soapenv:Envelope>
"""

reiteracoes = processors.extrair_reiteracoes(xml)
print("Reiteracoes extraidas:", reiteracoes)

if not reiteracoes:
    raise Exception("Nenhuma reiteracao foi extraida do XML")

anexos = extrair_anexos_do_xml(reiteracoes[0]) or []
print("Anexos extraidos:", anexos)

if not anexos:
    raise Exception("Nenhum anexo foi extraido do XML")

try:
    glpi_client.init_session()

    glpi_client.adicionar_followup_publico(
        TICKET_ID,
        "Reiteracao recebida da CAIXA\n\nTeste de reiteracao com anexo"
    )

    for ax in anexos:
        glpi_client.adicionar_followup_com_anexo(
            ticket_id=TICKET_ID,
            texto="Arquivo recebido da CAIXA",
            filename=ax["filename"],
            base64_file=ax["base64"],
        )

    print("OK - followup e anexo enviados ao GLPI")

finally:
    glpi_client.kill_session()
