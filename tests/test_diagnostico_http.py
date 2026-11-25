from scrapers import diagnostico


def test_http_403_e_acesso_negado_mesmo_quando_requests_informa_erro():
    diagnostico.limpar_todos()
    diagnostico.registrar_http(
        "https://api.example/vagas?token=nao-salvar", 403,
        erro="HTTPError: 403 Client Error: Forbidden",
        fonte="Empregare",
    )
    estado = diagnostico.obter("Empregare")
    assert estado["status"] == "acesso_negado"
    assert estado["http_status"] == 403
    assert "timeout" not in estado["detalhe"].lower()
    assert "token" not in estado["url"]


def test_http_429_e_limite_de_requisicoes():
    diagnostico.limpar_todos()
    diagnostico.registrar_http("https://api.example/vagas", 429, fonte="Jooble")
    assert diagnostico.obter("Jooble")["status"] == "limite_requisicoes"


def test_parser_nao_apaga_diagnostico_de_bloqueio():
    diagnostico.limpar_todos()
    diagnostico.registrar_http("https://api.example/vagas", 403, fonte="Empregare")
    diagnostico.registrar_parser("https://api.example/vagas", 0, "API REST", "", "Empregare")
    assert diagnostico.obter("Empregare")["status"] == "acesso_negado"


def test_falha_em_um_termo_nao_e_apagada_pelo_sucesso_de_outro():
    diagnostico.limpar_todos()
    diagnostico.registrar_http("https://api.example/jobs?q=CPD", 200, fonte="Fonte")
    diagnostico.registrar_parser("https://api.example/jobs", 0, "API REST", "", "Fonte")
    diagnostico.registrar_http("https://api.example/jobs?q=Motorista", 403, fonte="Fonte")
    diagnostico.registrar_parser("https://api.example/jobs", 0, "API REST", "", "Fonte")
    estado = diagnostico.obter("Fonte")
    assert estado["status"] == "parcial"
    assert "HTTP 403" in estado["detalhe"]


def test_diagnostico_reconhece_pagina_wordpress_search_no_results(tmp_path, monkeypatch):
    from scrapers import diagnostico

    monkeypatch.setattr(diagnostico, "_PASTA_DIAGNOSTICOS", tmp_path)
    diagnostico.limpar_todos()
    html = '''<html><body class="search search-no-results">
    <main><section class="no-results not-found"><h1>Nothing Found</h1></section></main>
    </body></html>'''
    diagnostico.registrar_http(
        "https://www.vagasrio.com.br/?s=CPD", 200, html,
        fonte="VagasRio", content_type="text/html; charset=UTF-8",
    )
    diagnostico.registrar_parser(
        "https://www.vagasrio.com.br/?s=CPD", 0,
        "busca WordPress sem cartões reconhecidos", html, "VagasRio",
        content_type="text/html; charset=UTF-8",
    )
    estado = diagnostico.obter("VagasRio")
    assert estado["status"] == "sem_resultados"
    assert not estado.get("snapshot")


def test_diagnostico_xml_nao_gera_xml_parsed_as_html_warning():
    import warnings
    from bs4 import XMLParsedAsHTMLWarning
    from scrapers import diagnostico

    diagnostico.limpar_todos()
    xml = '<?xml version="1.0"?><rss><channel><title>Feed</title><item><title>Vaga</title></item></channel></rss>'
    with warnings.catch_warnings(record=True) as capturados:
        warnings.simplefilter("always")
        diagnostico.registrar_http(
            "https://feed.example/jobs.xml", 200, xml,
            fonte="Feed XML", content_type="application/rss+xml",
        )
    assert not any(issubclass(w.category, XMLParsedAsHTMLWarning) for w in capturados)


def test_diagnostico_guarda_url_solicitada_e_final_sem_query_ou_token():
    from scrapers import diagnostico

    diagnostico.limpar_todos()
    diagnostico.registrar_http(
        "https://vagasrio.com.br/?s=CPD&token=segredo", 200,
        fonte="VagasRio", content_type="text/html",
        url_final="https://www.vagasrio.com.br/?s=CPD&token=segredo",
    )
    estado = diagnostico.obter("VagasRio")
    assert estado["url_solicitada"] == "https://vagasrio.com.br/"
    assert estado["url_final"] == "https://www.vagasrio.com.br/"
    assert "token" not in str(estado)


def test_feed_xml_sem_resultados_nao_dispara_warning_de_parser_html():
    import warnings
    from bs4 import XMLParsedAsHTMLWarning
    from scrapers import diagnostico

    diagnostico.limpar_todos()
    xml = '<?xml version="1.0"?><jobs><total>0</total><items /></jobs>'
    with warnings.catch_warnings(record=True) as capturados:
        warnings.simplefilter("always")
        diagnostico.registrar_http(
            "https://feed.example/jobs.xml", 200, xml,
            fonte="Feed Vazio", content_type="application/xml",
        )
        diagnostico.registrar_parser(
            "https://feed.example/jobs.xml", 0, "feed XML parceiro", xml,
            "Feed Vazio", content_type="application/xml",
        )
    assert diagnostico.obter("Feed Vazio")["status"] == "sem_resultados"
    assert not any(issubclass(w.category, XMLParsedAsHTMLWarning) for w in capturados)


def test_buscar_url_nao_conta_http_403_duas_vezes():
    import requests
    from scrapers.base import buscar_url

    class Resposta403:
        status_code = 403
        text = "Forbidden"
        url = "https://portal.example/jobs?token=private"
        headers = {"Content-Type": "text/plain"}
        def raise_for_status(self):
            raise requests.HTTPError("403 Forbidden", response=self)

    class Sessao:
        def get(self, *args, **kwargs):
            return Resposta403()

    diagnostico.limpar_todos()
    assert buscar_url(Sessao(), "https://portal.example/jobs?token=private", "Portal 403") is None
    estado = diagnostico.obter("Portal 403")
    assert estado["status"] == "acesso_negado"
    assert estado["tentativas"] == 1
    assert "private" not in str(estado)
