import json
from pathlib import Path

import config
from scrapers import diagnostico, gupy


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status_code = status
        self.headers = {"Content-Type": "application/json"}
        self.text = json.dumps(payload, ensure_ascii=False)

    def json(self):
        return self.payload

    def raise_for_status(self):
        return None


def test_gupy_consulta_com_cidade_uf_e_extrai_campos(monkeypatch):
    monkeypatch.setattr(config, "UF_ALVO", "RJ")
    monkeypatch.setattr(config, "REQUEST_DELAY_SECONDS", 0)
    diagnostico.limpar_todos()
    requisicoes = []
    payload = {"data": [{
        "name": "Auxiliar de CPD",
        "careerPageName": "Mercado Exemplo",
        "city": "Nova Iguaçu",
        "state": "Rio de Janeiro",
        "publishedDate": "2026-11-23T10:00:00Z",
        "applicationDeadline": "2026-12-01",
        "workplaceType": "remote",
        "description": "Atendimento técnico e controle de chamados.",
        "jobUrl": "https://portal.gupy.io/job/123",
        "badges": {"isPWD": True},
    }]}

    def fake_get(url, params, **kwargs):
        requisicoes.append((url, params, kwargs))
        return FakeResponse(payload)

    monkeypatch.setattr(gupy.requests, "get", fake_get)
    vagas = gupy.buscar_vagas_gupy("Auxiliar de CPD", "Nova Iguaçu", 20)

    assert len(vagas) == 1
    vaga = vagas[0]
    assert vaga.titulo == "Auxiliar de CPD"
    assert vaga.empresa == "Mercado Exemplo"
    assert vaga.cidade == "Nova Iguaçu / RJ"
    assert vaga.data_publicacao.startswith("2026-11-23")
    assert "Modalidade: remoto" in vaga.descricao
    assert "Prazo de candidatura: 2026-12-01" in vaga.descricao
    assert "Vaga afirmativa para PcD" in vaga.descricao
    assert vaga.link == "https://portal.gupy.io/job/123"
    assert requisicoes[0][1]["state"] == "Rio de Janeiro"
    assert requisicoes[0][1]["city"] == "Nova Iguaçu"
    assert diagnostico.obter("Gupy")["status"] == "ok"


def test_gupy_sem_vagas_e_diferente_de_schema_quebrado(monkeypatch):
    diagnostico.limpar_todos()
    monkeypatch.setattr(gupy.requests, "get", lambda *a, **k: FakeResponse({"data": []}))
    assert gupy.buscar_vagas_gupy("Auxiliar", "", 20) == []
    assert diagnostico.obter("Gupy")["status"] == "sem_resultados"


def test_gupy_registra_schema_inesperado_sem_salvar_valores_das_vagas(monkeypatch, tmp_path):
    diagnostico.limpar_todos()
    monkeypatch.setattr(diagnostico, "_PASTA_DIAGNOSTICOS", tmp_path)
    payload = {"items": [{"headline": "Título confidencial do anúncio", "body": "Descrição secreta"}]}
    monkeypatch.setattr(gupy.requests, "get", lambda *a, **k: FakeResponse(payload))

    assert gupy.buscar_vagas_gupy("Auxiliar", "", 20) == []
    estado = diagnostico.obter("Gupy")
    assert estado["status"] == "estrutura_alterada"
    snapshot = Path(estado["snapshot"]).read_text(encoding="utf-8")
    assert '"items"' in snapshot and '"headline"' in snapshot
    assert "Título confidencial" not in snapshot
    assert "Descrição secreta" not in snapshot
