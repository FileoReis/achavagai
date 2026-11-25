from scrapers import diagnostico
from scrapers.base import Vaga
from scrapers.generic_wordpress import _buscar_rest_vagasrio, buscar_vagas_wordpress


class FakeResponse:
    def __init__(self, payload=None, text="", url="https://www.vagasrio.com.br/"):
        self._payload = payload
        self.text = text
        self.url = url
        self.status_code = 200
        self.headers = {"Content-Type": "application/json; charset=UTF-8"}

    def json(self):
        return self._payload


def test_vagasrio_rest_fallback_extrai_posts_publicos(monkeypatch):
    import scrapers.generic_wordpress as modulo
    chamadas = []
    resposta = FakeResponse([{
        "title": {"rendered": "Auxiliar de CPD - Rio de Janeiro"},
        "link": "https://www.vagasrio.com.br/vaga-auxiliar-cpd/",
        "date": "2026-11-24T10:00:00",
        "excerpt": {"rendered": "Atividades de Central de Processamento de Dados."},
    }])

    def fake_buscar_url(sessao, url, diagnostico_nome=None, **kwargs):
        chamadas.append((url, diagnostico_nome, kwargs))
        return resposta

    monkeypatch.setattr(modulo, "buscar_url", fake_buscar_url)
    diagnostico.limpar_todos()
    vagas = _buscar_rest_vagasrio(object(), "https://www.vagasrio.com.br", "CPD")
    assert len(vagas) == 1
    assert vagas[0].titulo == "Auxiliar de CPD - Rio de Janeiro"
    assert chamadas[0][0].endswith("/wp-json/wp/v2/posts")
    assert chamadas[0][2]["params"]["search"] == "CPD"


def test_vagasrio_tenta_rest_quando_pesquisa_wordpress_nao_tem_resultados(monkeypatch):
    import scrapers.generic_wordpress as modulo

    class Sessao:
        pass

    html = '''<html><body class="search search-no-results">
    <section class="no-results not-found"><h1>Nada encontrado</h1></section>
    </body></html>'''
    chamadas = []
    post = [{
        "title": {"rendered": "Motorista B - Rio de Janeiro"},
        "link": "https://www.vagasrio.com.br/motorista-b/",
        "date": "2026-11-24T10:00:00",
        "excerpt": {"rendered": "CNH categoria B; transporte de veículos leves."},
    }]
    respostas = [FakeResponse(text=html, url="https://www.vagasrio.com.br/?s=Motorista"), FakeResponse(payload=post)]

    monkeypatch.setattr(modulo, "nova_sessao", lambda: Sessao())
    def fake_buscar_url(sessao, url, diagnostico_nome=None, **kwargs):
        chamadas.append(url)
        return respostas.pop(0)
    monkeypatch.setattr(modulo, "buscar_url", fake_buscar_url)
    diagnostico.limpar_todos()
    vagas = buscar_vagas_wordpress("VagasRio", "https://www.vagasrio.com.br", "Motorista")
    assert len(vagas) == 1
    assert vagas[0].titulo == "Motorista B - Rio de Janeiro"
    assert "?s=Motorista" in chamadas[0]
    assert chamadas[1].endswith("/wp-json/wp/v2/posts")


def test_vagasrio_url_de_busca_codifica_acento_e_espaco(monkeypatch):
    import scrapers.generic_wordpress as modulo
    class Sessao: pass
    resposta = FakeResponse(text='<html><body class="search search-no-results"><section class="no-results"></section></body></html>')
    chamadas = []
    def fake_buscar_url(sessao, url, diagnostico_nome=None, **kwargs):
        chamadas.append(url)
        # impede uma segunda chamada neste teste, sinalizando que o fallback está desativado
        import config
        monkeypatch.setattr(config, "VAGASRIO_USAR_REST_FALLBACK", False)
        return resposta
    monkeypatch.setattr(modulo, "nova_sessao", lambda: Sessao())
    monkeypatch.setattr(modulo, "buscar_url", fake_buscar_url)
    diagnostico.limpar_todos()
    buscar_vagas_wordpress("VagasRio", "https://www.vagasrio.com.br", "Técnico de Informática")
    assert chamadas[0].endswith("?s=T%C3%A9cnico+de+Inform%C3%A1tica")
