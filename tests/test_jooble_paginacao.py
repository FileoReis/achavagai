import requests

from scrapers import diagnostico
from scrapers.jooble import buscar_vagas_jooble


class FakeResponse:
    def __init__(self, data, status_code=200):
        self._data = data
        self.status_code = status_code
        self.headers = {"Content-Type": "application/json"}
        self.text = "{}"

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Client Error", response=self)

    def json(self):
        return self._data


class FakeSession:
    def __init__(self, pages):
        self.pages = pages
        self.headers = {}
        self.calls = []

    def post(self, url, json, timeout):
        self.calls.append((url, dict(json), timeout))
        return FakeResponse(self.pages[json["page"]])


def _job(i):
    return {
        "id": i,
        "title": f"Vaga {i}",
        "company": "Empresa",
        "location": "Rio de Janeiro, RJ",
        "updated": "2026-11-24T10:00:00",
        "link": f"https://br.jooble.org/jdp/{i}",
        "snippet": "Descrição da vaga",
    }


def test_jooble_busca_paginas_ate_total_count(monkeypatch):
    import scrapers.jooble as modulo

    fake = FakeSession({
        1: {"totalCount": 65, "jobs": [_job(i) for i in range(1, 31)]},
        2: {"totalCount": 65, "jobs": [_job(i) for i in range(31, 61)]},
        3: {"totalCount": 65, "jobs": [_job(i) for i in range(61, 66)]},
    })
    monkeypatch.setenv("JOOBLE_API_KEY", "chave-de-teste")
    monkeypatch.setattr(modulo.requests, "Session", lambda: fake)
    diagnostico.limpar_todos()

    vagas = buscar_vagas_jooble("Motorista", "Rio de Janeiro", max_resultados=90, max_paginas=4)

    assert len(vagas) == 65
    assert [call[1]["page"] for call in fake.calls] == [1, 2, 3]
    assert all(call[1]["ResultOnPage"] == 30 for call in fake.calls)
    assert diagnostico.obter("Jooble")["status"] == "ok"


def test_jooble_interrompe_quando_pagina_nao_traz_vagas_novas(monkeypatch):
    import scrapers.jooble as modulo

    primeira = [_job(i) for i in range(1, 31)]
    fake = FakeSession({
        1: {"totalCount": 100, "jobs": primeira},
        2: {"totalCount": 100, "jobs": primeira},
    })
    monkeypatch.setenv("JOOBLE_API_KEY", "chave-de-teste")
    monkeypatch.setattr(modulo.requests, "Session", lambda: fake)

    vagas = buscar_vagas_jooble("CPD", "Rio de Janeiro", max_resultados=90, max_paginas=3)

    assert len(vagas) == 30
    assert len(fake.calls) == 2


def test_jooble_nao_expoe_chave_em_erro_http(monkeypatch):
    import scrapers.jooble as modulo

    class ForbiddenResponse(FakeResponse):
        def raise_for_status(self):
            raise requests.HTTPError(
                "403 Client Error: Forbidden for url: https://br.jooble.org/api/SEGREDO-TESTE",
                response=self,
            )

    fake = FakeSession({1: {"totalCount": 0, "jobs": []}})
    fake.post = lambda url, json, timeout: ForbiddenResponse({}, 403)
    monkeypatch.setenv("JOOBLE_API_KEY", "SEGREDO-TESTE")
    monkeypatch.setattr(modulo.requests, "Session", lambda: fake)
    diagnostico.limpar_todos()

    assert buscar_vagas_jooble("Informática", "Rio de Janeiro", max_paginas=1) == []
    estado = diagnostico.obter("Jooble")
    assert estado["status"] == "acesso_negado"
    assert "SEGREDO-TESTE" not in str(estado)


def test_jooble_json_invalido_e_diagnostico_de_schema(monkeypatch):
    import scrapers.jooble as modulo

    class InvalidJsonResponse(FakeResponse):
        def json(self):
            raise requests.exceptions.JSONDecodeError("JSON inválido", "{", 0)

    fake = FakeSession({1: {"totalCount": 0, "jobs": []}})
    fake.post = lambda url, json, timeout: InvalidJsonResponse({})
    monkeypatch.setenv("JOOBLE_API_KEY", "chave-de-teste")
    monkeypatch.setattr(modulo.requests, "Session", lambda: fake)
    diagnostico.limpar_todos()

    assert buscar_vagas_jooble("CPD", max_paginas=1) == []
    assert diagnostico.obter("Jooble")["status"] == "estrutura_alterada"


def test_jooble_respeita_tres_paginas_padrao_quando_api_tem_mais(monkeypatch):
    import scrapers.jooble as modulo

    fake = FakeSession({pagina: {"totalCount": 500, "jobs": [_job((pagina - 1) * 30 + i) for i in range(1, 31)]}
                        for pagina in range(1, 5)})
    monkeypatch.setenv("JOOBLE_API_KEY", "chave-de-teste")
    monkeypatch.setattr(modulo.requests, "Session", lambda: fake)

    vagas = buscar_vagas_jooble("Informática", "Rio de Janeiro")

    assert len(vagas) == 90
    assert [call[1]["page"] for call in fake.calls] == [1, 2, 3]
