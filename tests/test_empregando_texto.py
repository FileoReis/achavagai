import warnings
import xml.etree.ElementTree as ET

from bs4 import MarkupResemblesLocatorWarning

from scrapers.empregando_brasil import _texto


def test_texto_puro_com_url_nao_dispara_warning_do_beautifulsoup():
    node = ET.fromstring("<url>https://empregandobrasil.com.br/vagas/123</url>")
    with warnings.catch_warnings(record=True) as capturados:
        warnings.simplefilter("always")
        valor = _texto(node)

    assert valor == "https://empregandobrasil.com.br/vagas/123"
    assert not any(issubclass(w.category, MarkupResemblesLocatorWarning) for w in capturados)


def test_texto_html_em_cdata_e_convertido_para_texto():
    node = ET.fromstring("<description><![CDATA[<p>Vaga de <strong>Motorista B</strong></p>]]></description>")
    assert _texto(node) == "Vaga de Motorista B"


def test_texto_simples_desescapa_entidades_xml():
    node = ET.fromstring("<description>Salário &amp; benefícios</description>")
    assert _texto(node) == "Salário & benefícios"
