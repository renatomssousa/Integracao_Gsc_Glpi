import base64

from api_gsc_glpi.utils import html_para_texto, limpar_texto_xml, tamanho_base64_em_bytes


def test_limpar_texto_xml_escapa_caracteres_especiais():
    assert limpar_texto_xml("A&B <x> \"y\" 'z'") == "A&amp;B &lt;x&gt; &quot;y&quot; &apos;z&apos;"


def test_html_para_texto_remove_tags_e_preserva_quebras():
    assert html_para_texto("<p>Oi&nbsp;mundo</p><br><div>Teste</div>") == "Oi mundo\n\nTeste"


def test_tamanho_base64_em_bytes():
    payload = b"abc123"
    b64 = base64.b64encode(payload).decode("ascii")

    assert tamanho_base64_em_bytes(b64) == len(payload)
