import json
import socket

import pytest

import descricoes

TEXTO_LONGO = (
    "Estamos contratando auxiliar administrativo para atuar em rotinas de escritório, "
    "atendimento ao cliente, controle de estoque e planilhas em Excel. Requisitos: ensino médio completo "
    "e experiência anterior na função. Oferecemos vale-transporte, vale-refeição e plano de saúde. "
    "Horário comercial, de segunda a sexta, em escritório no Centro. "
)


def pagina(corpo, cabeca=""):
    return f"<html><head>{cabeca}</head><body>{corpo}</body></html>"


# --------------------------------------------------------------- extração

def test_jsonld_jobposting_e_a_fonte_preferida():
    dados = {"@context": "https://schema.org", "@type": "JobPosting", "title": "Auxiliar",
             "description": f"<p>{TEXTO_LONGO}</p><ul><li>Vale-transporte</li></ul>"}
    html = pagina("<div class='x'>menu menu menu</div>",
                  f'<script type="application/ld+json">{json.dumps(dados)}</script>')
    texto = descricoes.extrair_descricao(html)
    assert texto.startswith("Estamos contratando") and "Vale-transporte" in texto and "<p>" not in texto


def test_jsonld_com_html_escapado_e_dentro_de_graph():
    dados = {"@graph": [{"@type": "WebSite"}, {"@type": ["Thing", "JobPosting"],
                                               "description": "&lt;p&gt;" + TEXTO_LONGO + "&lt;/p&gt;"}]}
    html = pagina("", f'<script type="application/ld+json">{json.dumps(dados)}</script>')
    assert descricoes.extrair_descricao(html).startswith("Estamos contratando")


def test_jsonld_invalido_e_ignorado_e_cai_para_os_blocos():
    html = pagina(
        f"<nav>Início Vagas Contato</nav><div class='job-description'>{TEXTO_LONGO}</div><footer>rodapé</footer>",
        '<script type="application/ld+json">{quebrado</script>',
    )
    texto = descricoes.extrair_descricao(html)
    assert texto.startswith("Estamos contratando") and "rodapé" not in texto and "Início" not in texto


def test_bloco_com_classe_de_descricao_ganha_de_bloco_de_comentarios():
    html = pagina(
        f"<div class='comentarios'>{'comentário ' * 60}</div><section id='descricao-da-vaga'>{TEXTO_LONGO}</section>"
    )
    assert descricoes.extrair_descricao(html).startswith("Estamos contratando")


def test_usa_article_main_e_depois_paragrafos():
    assert descricoes.extrair_descricao(pagina(f"<article>{TEXTO_LONGO}</article>")).startswith("Estamos")
    assert descricoes.extrair_descricao(pagina(f"<main><p>{TEXTO_LONGO}</p></main>")).startswith("Estamos")
    soltos = pagina(f"<p>{TEXTO_LONGO}</p><p>Mais um parágrafo com informações da vaga.</p>")
    assert "Mais um parágrafo" in descricoes.extrair_descricao(soltos)


def test_meta_description_e_o_ultimo_recurso():
    cabeca = '<meta property="og:description" content="Vaga de auxiliar administrativo no Rio de Janeiro, com benefícios.">'
    assert descricoes.extrair_descricao(pagina("<p>oi</p>", cabeca)).startswith("Vaga de auxiliar")


@pytest.mark.parametrize("html", [
    pagina("<h1>Just a moment...</h1><p>Verify you are human by completing the captcha below to continue.</p>"),
    pagina("<p>Acesso negado. Seu acesso foi bloqueado por excesso de requisições feitas pelo seu endereço.</p>"),
    pagina("<p>curto</p>"),
    "",
    b"\xff\xfe nao e html",
])
def test_paginas_de_bloqueio_ou_vazias_devolvem_vazio(html):
    assert descricoes.extrair_descricao(html) == ""


def test_limita_o_tamanho_guardado():
    html = pagina(f"<article>{TEXTO_LONGO * 200}</article>")
    assert len(descricoes.extrair_descricao(html)) == descricoes.LIMITE_DESCRICAO


def test_aceita_bytes_com_acentos_utf8():
    html = pagina(f"<article>{TEXTO_LONGO}</article>").encode("utf-8")
    assert "médio completo" in descricoes.extrair_descricao(html)


# ------------------------------------------------------------- segurança

@pytest.mark.parametrize("url", [
    "http://127.0.0.1/admin", "http://10.0.0.5/x", "http://192.168.1.1/", "http://172.16.0.9/",
    "http://169.254.169.254/latest/meta-data/", "http://[::1]/", "http://0.0.0.0/",
    "http://[::ffff:127.0.0.1]/", "http://100.64.0.1/",
    "file:///etc/passwd", "ftp://example.com/x", "javascript:alert(1)", "", "http:///semhost",
])
def test_url_segura_recusa_rede_local_e_esquemas_estranhos(url):
    assert descricoes.url_segura(url) is False


def test_url_segura_aceita_nome_que_resolve_para_ip_publico(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda host, porta: [(2, 1, 6, "", ("93.184.216.34", 0))])
    assert descricoes.url_segura("https://vagas.exemplo.com.br/vaga/1") is True


def test_url_segura_recusa_nome_que_aponta_para_a_rede_interna_ou_nao_resolve(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda host, porta: [(2, 1, 6, "", ("10.1.2.3", 0))])
    assert descricoes.url_segura("https://interno.exemplo.com/x") is False

    def nao_resolve(host, porta):
        raise socket.gaierror("sem dns")

    monkeypatch.setattr(socket, "getaddrinfo", nao_resolve)
    assert descricoes.url_segura("https://nao-existe.exemplo.com/x") is False


class RespostaFalsa:
    def __init__(self, status=200, headers=None, corpo=b"", pedacos=None):
        self.status_code = status
        self.headers = headers or {"Content-Type": "text/html; charset=utf-8"}
        self._pedacos = pedacos if pedacos is not None else [corpo]
        self.fechada = False

    def iter_content(self, tamanho):
        yield from self._pedacos

    def close(self):
        self.fechada = True


class SessaoFalsa:
    def __init__(self, respostas):
        self.respostas = dict(respostas)
        self.pedidos = []

    def get(self, url, headers=None, timeout=None, allow_redirects=None, stream=None):
        assert allow_redirects is False  # os redirecionamentos são seguidos à mão, com checagem
        self.pedidos.append(url)
        item = self.respostas[url]
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture
def internet_publica(monkeypatch):
    """Faz todo nome de site parecer público, exceto os que começam com 'interno'."""
    def resolver(host, porta):
        ip = "10.0.0.7" if host.startswith("interno") else "93.184.216.34"
        return [(2, 1, 6, "", (ip, 0))]
    monkeypatch.setattr(socket, "getaddrinfo", resolver)


def test_baixa_pagina_normal(internet_publica):
    sessao = SessaoFalsa({"https://a.com.br/v/1": RespostaFalsa(corpo=b"<html>ok</html>")})
    assert descricoes._baixar_pagina("https://a.com.br/v/1", sessao) == b"<html>ok</html>"


def test_segue_redirecionamento_relativo(internet_publica):
    sessao = SessaoFalsa({
        "https://a.com.br/v/1": RespostaFalsa(301, {"Location": "/nova"}),
        "https://a.com.br/nova": RespostaFalsa(corpo=b"<html>destino</html>"),
    })
    assert descricoes._baixar_pagina("https://a.com.br/v/1", sessao) == b"<html>destino</html>"


def test_redirecionamento_para_rede_interna_e_bloqueado(internet_publica):
    sessao = SessaoFalsa({"https://a.com.br/v/1": RespostaFalsa(302, {"Location": "http://interno.empresa/admin"})})
    assert descricoes._baixar_pagina("https://a.com.br/v/1", sessao) is None
    assert sessao.pedidos == ["https://a.com.br/v/1"]  # nunca chegou a pedir o endereço interno


def test_redirecionamentos_demais_param(internet_publica):
    respostas = {"https://a.com.br/x": RespostaFalsa(302, {"Location": "/1"})}
    for i in range(1, 10):
        respostas[f"https://a.com.br/{i}"] = RespostaFalsa(302, {"Location": f"/{i + 1}"})
    sessao = SessaoFalsa(respostas)
    assert descricoes._baixar_pagina("https://a.com.br/x", sessao) is None
    assert len(sessao.pedidos) == descricoes.MAX_REDIRECIONAMENTOS + 1


@pytest.mark.parametrize("resposta", [
    RespostaFalsa(404),
    RespostaFalsa(403),
    RespostaFalsa(headers={"Content-Type": "application/pdf"}, corpo=b"%PDF"),
    RespostaFalsa(pedacos=[b"x" * 1_500_000, b"x" * 1_500_000]),
])
def test_respostas_inadequadas_viram_none_e_a_conexao_e_fechada(internet_publica, resposta):
    sessao = SessaoFalsa({"https://a.com.br/v/1": resposta})
    assert descricoes._baixar_pagina("https://a.com.br/v/1", sessao) is None
    assert resposta.fechada


def test_erro_de_rede_vira_none(internet_publica):
    import requests
    sessao = SessaoFalsa({"https://a.com.br/v/1": requests.ConnectionError("caiu")})
    assert descricoes._baixar_pagina("https://a.com.br/v/1", sessao) is None


def test_buscar_descricao_junta_download_e_extracao(internet_publica):
    html = pagina(f"<article>{TEXTO_LONGO}</article>").encode()
    sessao = SessaoFalsa({"https://a.com.br/v/1": RespostaFalsa(corpo=html)})
    assert descricoes.buscar_descricao("https://a.com.br/v/1", sessao).startswith("Estamos contratando")
    assert descricoes.buscar_descricao("http://127.0.0.1/x", sessao) == ""


# ------------------------------------------------------------ etapa completa

@pytest.fixture
def sem_espera(monkeypatch):
    pausas = []
    relogio = {"t": 1000.0}
    monkeypatch.setattr(descricoes, "_dormir", lambda s: (pausas.append(round(s, 2)), relogio.__setitem__("t", relogio["t"] + s)))
    monkeypatch.setattr(descricoes, "_agora", lambda: relogio["t"])
    return pausas


def vagas_com_link(vaga, *links, descricao=""):
    return [vaga(titulo=f"Vaga {i}", link=link, descricao=descricao) for i, link in enumerate(links)]


def test_enriquece_so_vagas_com_pouca_descricao_ate_o_limite(vaga, sem_espera):
    vagas = vagas_com_link(vaga, *[f"https://a{i}.com.br/v" for i in range(6)])
    vagas[1].descricao = "x" * 500  # já tem descrição boa: não gasta requisição
    abertas = []
    estatisticas = descricoes.enriquecer_descricoes(
        vagas, limite=3, minimo_caracteres=400, atraso=1.0, hosts_ignorados=(),
        baixar=lambda url: (abertas.append(url), TEXTO_LONGO)[1],
    )
    assert abertas == ["https://a0.com.br/v", "https://a2.com.br/v", "https://a3.com.br/v"]
    assert estatisticas == {"tentadas": 3, "enriquecidas": 3, "falhas": 0, "ignoradas": 0, "datas": 0}
    assert vagas[0].descricao == TEXTO_LONGO and vagas[1].descricao == "x" * 500 and vagas[4].descricao == ""


def test_pula_linkedin_e_conta_como_ignorada(vaga, sem_espera):
    vagas = vagas_com_link(vaga, "https://www.linkedin.com/jobs/view/1", "https://br.linkedin.com/jobs/view/2", "https://vagas.com.br/1")
    abertas = []
    estatisticas = descricoes.enriquecer_descricoes(
        vagas, limite=10, hosts_ignorados=("linkedin.com",), baixar=lambda url: (abertas.append(url), TEXTO_LONGO)[1],
    )
    assert abertas == ["https://vagas.com.br/1"]
    assert estatisticas["ignoradas"] == 2 and estatisticas["enriquecidas"] == 1


def test_usa_a_configuracao_do_config_por_padrao(vaga, sem_espera, monkeypatch):
    import config
    monkeypatch.setattr(config, "HOSTS_SEM_ANALISE_PROFUNDA", ("linkedin.com",))
    monkeypatch.setattr(config, "QUANTIDADE_ANALISE_PROFUNDA", 1)
    vagas = vagas_com_link(vaga, "https://www.linkedin.com/jobs/view/1", "https://b.com.br/1", "https://c.com.br/2")
    abertas = []
    descricoes.enriquecer_descricoes(vagas, baixar=lambda url: (abertas.append(url), TEXTO_LONGO)[1])
    assert abertas == ["https://b.com.br/1"]


def test_respeita_a_pausa_entre_requisicoes_do_mesmo_site_mas_nao_de_sites_diferentes(vaga, sem_espera):
    vagas = vagas_com_link(vaga, "https://a.com.br/1", "https://a.com.br/2", "https://b.com.br/1")
    descricoes.enriquecer_descricoes(vagas, limite=10, atraso=2.0, hosts_ignorados=(), baixar=lambda url: TEXTO_LONGO)
    assert sem_espera == [2.0]  # só a segunda página do mesmo site esperou


def test_falha_numa_pagina_nao_derruba_as_outras_nem_apaga_a_descricao(vaga, sem_espera):
    vagas = vagas_com_link(vaga, "https://a.com.br/1", "https://b.com.br/1", "https://c.com.br/1")
    vagas[0].descricao = "curta"

    def baixar(url):
        if "a.com" in url:
            raise RuntimeError("quebrou")
        return "" if "b.com" in url else TEXTO_LONGO

    estatisticas = descricoes.enriquecer_descricoes(vagas, limite=10, atraso=0, hosts_ignorados=(), baixar=baixar)
    assert estatisticas["falhas"] == 2 and estatisticas["enriquecidas"] == 1
    assert vagas[0].descricao == "curta" and vagas[2].descricao == TEXTO_LONGO


def test_nao_troca_por_um_texto_menor_e_ignora_vagas_sem_link(vaga, sem_espera):
    vagas = [vaga(titulo="A", link="https://a.com.br/1", descricao="d" * 300), vaga(titulo="B", link="")]
    estatisticas = descricoes.enriquecer_descricoes(
        vagas, limite=10, minimo_caracteres=400, atraso=0, hosts_ignorados=(), baixar=lambda url: "curto",
    )
    assert vagas[0].descricao == "d" * 300 and estatisticas["tentadas"] == 1 and estatisticas["enriquecidas"] == 0


def test_limite_zero_desliga_a_etapa_e_progresso_e_informado(vaga, sem_espera):
    vagas = vagas_com_link(vaga, "https://a.com.br/1", "https://b.com.br/1")
    assert descricoes.enriquecer_descricoes(vagas, limite=0, baixar=lambda url: 1 / 0)["tentadas"] == 0
    eventos = []
    descricoes.enriquecer_descricoes(vagas, limite=5, atraso=0, hosts_ignorados=(), baixar=lambda url: TEXTO_LONGO,
                                     ao_avancar=lambda feitas, total: eventos.append((feitas, total)))
    assert eventos == [(1, 2), (2, 2)]


# ---------------------------------------------------------------------------
# Data de publicação lida da página (a lista de resultados do portal não trazia)
# ---------------------------------------------------------------------------

PAGINA_VAGASRIO = """<html><head><title>Motorista de Ônibus Urbano - Queimados - RJ</title></head><body>
<header><nav>INÍCIO DENUNCIAR REGRAS DIVULGAR VAGA</nav></header>
<article class="post"><h1 class="entry-title">Motorista de Ônibus Urbano - Queimados - RJ</h1>
<div class="entry-meta"><a href="/2026/04/09/"><time class="entry-date published" datetime="2026-04-09T10:15:00-03:00">9 de abril de 2026</time></a> | vagasemprego</div>
<div class="entry-content"><p>Requisitos:</p><ul><li>Curso de Transporte Coletivo de Passageiros (Resolução 789);</li>
<li>Experiência como motorista de ônibus ou caminhão;</li><li>CNH categoria D válida;</li><li>Contratação: CLT</li></ul>
<p>Atividades:</p><ul><li>Dirigir Ônibus urbano municipal e intermunicipal</li></ul></div></article>
<aside class="sidebar widget"><time datetime="2026-11-01">1 de novembro de 2026</time></aside></body></html>"""


def test_pagina_do_relato_traz_descricao_e_data_de_publicacao():
    assert descricoes.extrair_data_publicacao(PAGINA_VAGASRIO) == "2026-04-09"
    assert "CNH categoria D" in descricoes.extrair_descricao(PAGINA_VAGASRIO)


@pytest.mark.parametrize("html, esperado", [
    ('<script type="application/ld+json">{"@context":"https://schema.org","@type":"JobPosting","datePosted":"2026-10-30","description":"x"}</script>', "2026-10-30"),
    ('<script type="application/ld+json">{"@graph":[{"@type":["Thing","JobPosting"],"datePosted":"2026-09-15T08:00:00Z"}]}</script>', "2026-09-15"),
    ('<meta property="article:published_time" content="2026-08-01T09:00:00+00:00"><p>texto</p>', "2026-08-01"),
    ('<meta itemprop="datePublished" content="2026-07-20">', "2026-07-20"),
    ('<article><span><time datetime="2026-06-02">2 jun</time></span><p>x</p></article>', "2026-06-02"),
    ('<article><p>5 de agosto de 2026 | Autor</p><p>Vaga de recepção.</p></article>', "5 de agosto de 2026"),
    ('<p>sem nenhuma data aqui</p>', ""),
    ('<aside><time datetime="2026-11-01">hoje</time></aside>', ""),                       # fora do artigo: ignora
    ('<article><div class="comments"><time datetime="2026-11-05">x</time></div></article>', ""),   # comentário: ignora
    ('<script type="application/ld+json">{ isto nao e json </script><p>x</p>', ""),
])
def test_extrair_data_publicacao(html, esperado):
    assert descricoes.extrair_data_publicacao(html) == esperado


def test_data_lida_da_pagina_e_entendida_pelo_filtro_de_idade():
    from filtros import idade_em_dias
    assert idade_em_dias(descricoes.extrair_data_publicacao(PAGINA_VAGASRIO)) > 200
    assert idade_em_dias("5 de agosto de 2026") is not None


def test_enriquecer_preenche_a_data_so_de_quem_veio_sem_data(vaga):
    sem_data = vaga(titulo="A", link="https://x.com.br/1", descricao="curta", data_publicacao="")
    com_data = vaga(titulo="B", link="https://x.com.br/2", descricao="curta", data_publicacao="2026-11-10")
    est = descricoes.enriquecer_descricoes([sem_data, com_data], baixar=lambda url: ("D" * 500, "2026-04-09"), atraso=0)
    assert sem_data.data_publicacao == "2026-04-09" and com_data.data_publicacao == "2026-11-10"
    assert est["datas"] == 1 and est["enriquecidas"] == 2


def test_enriquecer_aceita_baixar_que_devolve_so_texto(vaga):
    v = vaga(titulo="A", link="https://x.com.br/1", descricao="curta", data_publicacao="")
    est = descricoes.enriquecer_descricoes([v], baixar=lambda url: "D" * 500, atraso=0)
    assert v.data_publicacao == "" and est["datas"] == 0 and est["enriquecidas"] == 1


def test_data_e_preenchida_mesmo_quando_a_descricao_nao_melhora(vaga):
    v = vaga(titulo="A", link="https://x.com.br/1", descricao="curta", data_publicacao="")
    est = descricoes.enriquecer_descricoes([v], baixar=lambda url: ("", "2026-04-09"), atraso=0)
    assert v.data_publicacao == "2026-04-09" and est["datas"] == 1 and est["falhas"] == 1


def test_buscar_pagina_devolve_descricao_e_data(internet_publica):
    sessao = SessaoFalsa({"https://a.com.br/v/1": RespostaFalsa(corpo=PAGINA_VAGASRIO.encode("utf-8"))})
    descricao, data = descricoes.buscar_pagina("https://a.com.br/v/1", sessao)
    assert "CNH categoria D" in descricao and data == "2026-04-09"
    assert descricoes.buscar_pagina("http://127.0.0.1/x", sessao) == ("", "")     # rede interna: nunca abre
