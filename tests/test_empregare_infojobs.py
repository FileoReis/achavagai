import config
from scrapers.empregare import _UF_ESTADO, _normalizar_local
from scrapers.infojobs import _montar_url


def test_infojobs_usa_uf_configurada_e_nao_fixa_rj(monkeypatch):
    monkeypatch.setattr(config, "UF_ALVO", "SP")
    assert _montar_url("Auxiliar Administrativo", "São Paulo").endswith(",-sp.aspx")


def test_infojobs_sem_uf_nao_inventa_estado(monkeypatch):
    monkeypatch.setattr(config, "UF_ALVO", "")
    assert _montar_url("Analista", "Curitiba").endswith("-curitiba.aspx")


def test_empregare_mapeia_todos_os_estados():
    assert len(_UF_ESTADO) == 27
    assert _UF_ESTADO["RJ"] == "Rio de Janeiro"
    assert _UF_ESTADO["AC"] == "Acre"


def test_empregare_nao_inventa_uf_a_partir_do_filtro():
    # A API retorna apenas cidade. O estado usado como filtro não prova a UF
    # de um item individual; a localização deve permanecer como foi informada.
    assert _normalizar_local({"cidades": ["Nova Iguaçu"]}) == "Nova Iguaçu"


def test_empregare_preserva_uf_quando_a_api_a_retorna():
    item = {"cidades": [{"cidade": "Nova Iguaçu", "uf": "RJ"}]}
    assert _normalizar_local(item) == "Nova Iguaçu / RJ"
