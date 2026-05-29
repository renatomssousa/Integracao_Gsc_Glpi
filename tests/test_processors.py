import base64

from api_gsc_glpi.processors import extrair_chamados_abertura, extrair_reiteracoes


def test_extrair_reiteracoes_com_anexo():
    b64 = base64.b64encode(b"arquivo").decode("ascii")
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
                  xmlns:urn="urn:GSC_RF010_FornecedorExterno_V401_WS">
  <soapenv:Body>
    <urn:GetList_ReiteracaoResponse>
      <urn:getListValues>
        <urn:info_arquivo><urn:idarquivo>ID1</urn:idarquivo></urn:info_arquivo>
        <urn:info_fornecedor><urn:chamado_fornecedor>GLPI-10</urn:chamado_fornecedor></urn:info_fornecedor>
        <urn:complemento>
          <urn:chamado_caixa><urn:no_req>REQ1</urn:no_req><urn:no_wo>WO1</urn:no_wo></urn:chamado_caixa>
          <urn:descricao>Comentario</urn:descricao>
          <urn:retornocaixa>3</urn:retornocaixa>
        </urn:complemento>
        <urn:anexos><urn:nome_arquivo1>a.txt</urn:nome_arquivo1><urn:anexo1>{b64}</urn:anexo1></urn:anexos>
      </urn:getListValues>
    </urn:GetList_ReiteracaoResponse>
  </soapenv:Body>
</soapenv:Envelope>"""

    [reiteracao] = extrair_reiteracoes(xml)

    assert reiteracao["id_arquivo"] == "ID1"
    assert reiteracao["no_req"] == "REQ1"
    assert reiteracao["no_wo"] == "WO1"
    assert reiteracao["chamado_fornecedor"] == "GLPI-10"
    assert reiteracao["retornocaixa"] == "3"
    assert reiteracao["anexos"] == [{"nome": "a.txt", "filename": "a.txt", "base64": b64}]


def test_extrair_chamados_abertura_xml_invalido_retorna_lista_vazia():
    assert extrair_chamados_abertura("nao e xml") == []
