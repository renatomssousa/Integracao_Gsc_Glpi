# -*- coding: utf-8 -*-
import base64
import re
import xml.etree.ElementTree as ET

NS = {"ns": "urn:GSC_RF010_FornecedorExterno_V401_WS"}


def _local(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _clean_b64(s: str) -> str:
    return re.sub(r"\s+", "", s or "").strip()


def _find_text_any_namespace(node, tag_name: str) -> str:
    if node is None:
        return ""

    for el in node.iter():
        if _local(el.tag) == tag_name:
            return (el.text or "").strip()

    return ""


def _extrair_anexos(anexos_node):
    anexos = []

    if anexos_node is None:
        return anexos

    nomes = {}
    conteudos = {}

    for ch in list(anexos_node):
        lname = _local(ch.tag)
        txt = (ch.text or "").strip()

        m_nome = re.match(r"^nome_arquivo(\d+)$", lname)
        if m_nome:
            nomes[int(m_nome.group(1))] = txt
            continue

        m_idx = re.search(r"(\d+)$", lname)
        if m_idx:
            idx = int(m_idx.group(1))
            b64 = _clean_b64(txt)
            if not b64:
                continue

            try:
                conteudo_bytes = base64.b64decode(b64)
                if len(conteudo_bytes) == 0:
                    continue
                conteudos[idx] = b64
            except Exception:
                continue

    for idx in sorted(nomes.keys()):
        if conteudos.get(idx):
            anexos.append({
                "nome": nomes[idx],
                "base64": conteudos[idx]
            })

    return anexos


def extrair_chamados_abertura(xml: str):
    root = ET.fromstring(xml)
    chamados = []

    for item in root.findall(".//ns:getListValues", NS):
        id_arquivo = item.findtext(".//ns:info_arquivo/ns:idarquivo", "", NS).strip()

        no_req = item.findtext(".//ns:chamado_caixa/ns:no_req", "", NS).strip()
        no_wo = item.findtext(".//ns:chamado_caixa/ns:no_wo", "", NS).strip()

        if not no_req:
            no_req = _find_text_any_namespace(item, "no_req")
        if not no_wo:
            no_wo = _find_text_any_namespace(item, "no_wo")

        nomereq = item.findtext(".//ns:tiporequisicao/ns:nomereq", "", NS).strip()
        if not nomereq:
            nomereq = item.findtext(".//ns:nomereq", "Chamado CAIXA", NS).strip() or "Chamado CAIXA"

        prioridade = item.findtext(".//ns:info_fornecedor/ns:prioridade", "", NS).strip()
        if not prioridade:
            prioridade = _find_text_any_namespace(item, "prioridade")

        solicitante_nome = item.findtext(".//ns:contatonome", "", NS).strip()
        solicitante_matricula = item.findtext(".//ns:idsolicitante", "", NS).strip()
        solicitante_email = item.findtext(".//ns:contatoemail", "", NS).strip()
        solicitante_tel = item.findtext(".//ns:contatotelefone", "", NS).strip()

        cod_unidade = item.findtext(".//ns:codigounidade", "", NS).strip()
        sigla_unidade = item.findtext(".//ns:siglaunidade", "", NS).strip()
        nome_unidade = item.findtext(".//ns:nomeunidade", "", NS).strip()
        cidade = item.findtext(".//ns:cidadeunidade", "", NS).strip()
        uf = item.findtext(".//ns:ufunidade", "", NS).strip()

        solicitacao_descricao = item.findtext(".//ns:solicitacao/ns:descricao", "", NS).strip()

        detalhes = []
        detalhes_node = item.find(".//ns:solicitacao/ns:detalhes", NS)
        if detalhes_node is not None:
            for d in list(detalhes_node):
                texto = (d.text or "").strip()
                if texto:
                    detalhes.append(texto)

        anexos_node = item.find(".//ns:anexos", NS)
        anexos = _extrair_anexos(anexos_node)

        partes_solicitacao = []
        if solicitacao_descricao:
            partes_solicitacao.append(solicitacao_descricao)
        partes_solicitacao.extend(detalhes)

        texto_solicitacao = "\n".join(partes_solicitacao).strip()
        if not texto_solicitacao:
            texto_solicitacao = "Sem detalhes enviados pela CAIXA."

        titulo = f"{no_req} / {no_wo} - {nomereq}".strip(" -/")

        descricao = f"""Solicitante
Nome: {solicitante_nome}
Matrícula: {solicitante_matricula}
E-mail: {solicitante_email}
Telefone: {solicitante_tel}

Unidade
Código da unidade: {cod_unidade}
Sigla: {sigla_unidade}
Nome: {nome_unidade}
Cidade/UF: {cidade} / {uf}

Prioridade
Prioridade: {prioridade}

Detalhes da Solicitação
{texto_solicitacao}

Origem: CAIXA Econômica Federal
Fornecedor: PETACORP
""".strip()

        chamados.append({
            "id_arquivo": id_arquivo,
            "no_req": no_req,
            "no_wo": no_wo,
            "titulo": titulo,
            "descricao": descricao,
            "anexos": anexos
        })

    return chamados


def extrair_reiteracoes(xml: str):
    root = ET.fromstring(xml)
    lista = []

    for item in root.findall(".//ns:getListValues", NS):
        id_arquivo = item.findtext(".//ns:info_arquivo/ns:idarquivo", "", NS).strip()

        no_req = item.findtext(".//ns:complemento/ns:chamado_caixa/ns:no_req", "", NS).strip()
        no_wo = item.findtext(".//ns:complemento/ns:chamado_caixa/ns:no_wo", "", NS).strip()
        descricao = item.findtext(".//ns:complemento/ns:descricao", "", NS).strip()
        chamado_fornecedor = item.findtext(".//ns:info_fornecedor/ns:chamado_fornecedor", "", NS).strip()

        if not no_req:
            no_req = _find_text_any_namespace(item, "no_req")
        if not no_wo:
            no_wo = _find_text_any_namespace(item, "no_wo")
        if not descricao:
            descricao = _find_text_any_namespace(item, "descricao")
        if not chamado_fornecedor:
            chamado_fornecedor = _find_text_any_namespace(item, "chamado_fornecedor")

        if not descricao:
            descricao = "Reiteracao recebida da CAIXA (sem descricao)."

        anexos_node = item.find(".//ns:anexos", NS)
        anexos = _extrair_anexos(anexos_node)

        lista.append({
            "id_arquivo": id_arquivo,
            "no_req": no_req.strip(),
            "no_wo": no_wo.strip(),
            "descricao": descricao.strip(),
            "chamado_fornecedor": chamado_fornecedor.strip(),
            "anexos": anexos
        })

    return lista