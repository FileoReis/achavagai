import requests
from pathlib import Path

from scrapers import diagnostico
from scrapers.empregare import API_URL, buscar_vagas_empregare


class FakeResponse:
    def __init__(self, data=None, status_code=200, text="{}"):
        self._data = data or {}
        self.status_code = status_code
        self.text = text
        self.headers = {"Content-Type": "application/json"}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)

    def json(self):
        return self._data


def test_empregare_usa_cabecalhos_padrao_e_extrai_vaga(monkeypatch):
    import scrapers.empregare as modulo
    chamadas = {}

    def fake_get(url, params, timeout, headers):
        chamadas.update(url=url, params=params, timeout=timeout, headers=headers)
        return FakeResponse({"model": {"dados": [{
            "id": 123,
            "titulo": "Auxiliar de CPD",
            "empresa": "Empresa Exemplo",
            "url": "/v123",
            "cidades": ["Rio de Janeiro, RJ"],
            "data": "2026-11-24",
            "chamada": "Rotinas de CPD e suporte",
        }]}})

    monkeypatch.setattr(modulo.requests, "get", fake_get)
    diagnostico.limpar_todos()
    vagas = buscar_vagas_empregare("CPD", "Rio de Janeiro")

    assert len(vagas) == 1
    assert vagas[0].titulo == "Auxiliar de CPD"
    assert chamadas["url"] == API_URL
    assert "User-Agent" in chamadas["headers"]
    assert chamadas["headers"]["Referer"] == "https://www.empregare.com/"
    assert ("Estado", "Rio de Janeiro") in chamadas["params"]
    assert diagnostico.obter("Empregare")["status"] == "ok"


def test_empregare_403_e_exibido_como_acesso_negado(monkeypatch):
    import scrapers.empregare as modulo

    def fake_get(url, params, timeout, headers):
        return FakeResponse(status_code=403, text="Forbidden")

    monkeypatch.setattr(modulo.requests, "get", fake_get)
    diagnostico.limpar_todos()
    assert buscar_vagas_empregare("Informática", "Rio de Janeiro") == []
    estado = diagnostico.obter("Empregare")
    assert estado["status"] == "acesso_negado"
    assert estado["http_status"] == 403
    assert "timeout" not in estado["detalhe"].lower()


def test_empregare_json_invalido_e_diagnostico_de_schema(monkeypatch, tmp_path):
    import scrapers.empregare as modulo
    from scrapers import diagnostico

    class InvalidJsonResponse(FakeResponse):
        def json(self):
            raise requests.exceptions.JSONDecodeError("JSON inválido", "{", 0)

    monkeypatch.setattr(modulo.requests, "get", lambda *args, **kwargs: InvalidJsonResponse())
    monkeypatch.setattr(diagnostico, "_PASTA_DIAGNOSTICOS", tmp_path)
    diagnostico.limpar_todos()

    assert buscar_vagas_empregare("CPD", "Rio de Janeiro") == []
    assert diagnostico.obter("Empregare")["status"] == "estrutura_alterada"


def test_empregare_model_dados_vazio_e_resultado_valido_sem_vagas(monkeypatch):
    import scrapers.empregare as modulo

    monkeypatch.setattr(
        modulo.requests, "get",
        lambda *args, **kwargs: FakeResponse({"sucesso": True, "model": {"totalVagas": 0, "totalRegistro": 0, "dados": []}}),
    )
    diagnostico.limpar_todos()
    assert buscar_vagas_empregare("CPD", "Rio de Janeiro") == []
    estado = diagnostico.obter("Empregare")
    assert estado["status"] == "sem_resultados"
    assert "JSON" not in estado["detalhe"]


def test_empregare_aceita_wrapper_data_e_aliases(monkeypatch):
    import scrapers.empregare as modulo

    payload = {"data": [{
        "title": "Técnico de Informática",
        "company": "Empresa Exemplo",
        "location": "Niterói / RJ",
        "datePosted": "2026-11-24",
        "description": "Suporte e manutenção de computadores",
        "applicationUrl": "https://empresa.example/candidatar/1",
    }]}
    monkeypatch.setattr(modulo.requests, "get", lambda *args, **kwargs: FakeResponse(payload))
    diagnostico.limpar_todos()
    vagas = buscar_vagas_empregare("Informática", "Rio de Janeiro")
    assert len(vagas) == 1
    assert vagas[0].titulo == "Técnico de Informática"
    assert vagas[0].empresa == "Empresa Exemplo"
    assert vagas[0].link.endswith("/candidatar/1")


def test_empregare_schema_desconhecido_salva_apenas_chaves_e_tipos(monkeypatch, tmp_path):
    import json
    import scrapers.empregare as modulo

    payload = {
        "novaEstrutura": {
            "anuncios": [{
                "nomeCargo": "VALOR PRIVADO - NÃO SALVAR",
                "emailRecrutador": "pessoa@example.com",
                "telefone": "21999999999",
            }]
        }
    }
    monkeypatch.setattr(modulo.requests, "get", lambda *args, **kwargs: FakeResponse(payload))
    monkeypatch.setattr(diagnostico, "_PASTA_DIAGNOSTICOS", tmp_path)
    diagnostico.limpar_todos()
    assert buscar_vagas_empregare("CPD", "Rio de Janeiro") == []
    estado = diagnostico.obter("Empregare")
    assert estado["status"] == "estrutura_alterada"
    documento = json.loads((tmp_path / "json" / Path(estado["snapshot"]).name).read_text(encoding="utf-8"))
    serializado = json.dumps(documento, ensure_ascii=False)
    assert "nomeCargo" in serializado
    assert "emailRecrutador" in serializado
    assert "VALOR PRIVADO" not in serializado
    assert "pessoa@example.com" not in serializado
    assert "21999999999" not in serializado


def test_empregare_html_de_bloqueio_gera_snapshot_dom_nao_comentario_vazio(monkeypatch, tmp_path):
    import scrapers.empregare as modulo

    class HtmlResponse(FakeResponse):
        def __init__(self):
            super().__init__(status_code=200, text='<html><body class="app-shell"><main class="new-job-layout"><section class="vacancy-results"><h1>Oportunidades</h1><div class="job-result-card">Conteúdo de exemplo que não deve ser gravado no snapshot estrutural.' + (' texto adicional para preencher o corpo e representar uma página HTML razoável.' * 8) + '</div></section></main></body></html>')
            self.headers = {"Content-Type": "text/html; charset=utf-8"}
        def json(self):
            raise ValueError("not json")

    monkeypatch.setattr(modulo.requests, "get", lambda *args, **kwargs: HtmlResponse())
    monkeypatch.setattr(diagnostico, "_PASTA_DIAGNOSTICOS", tmp_path)
    diagnostico.limpar_todos()
    assert buscar_vagas_empregare("CPD", "Rio de Janeiro") == []
    estado = diagnostico.obter("Empregare")
    assert estado["snapshot"]
    conteudo = Path(estado["snapshot"]).read_text(encoding="utf-8")
    assert "app-shell" in conteudo
    assert "new-job-layout" in conteudo
    assert "job-result-card" in conteudo
    assert "Conteúdo de exemplo" not in conteudo
