from datetime import datetime

import pytest

import filtros

AGORA = datetime(2026, 11, 7, 12, 0, 0)


# ------------------------------------------------------------------ datas

@pytest.mark.parametrize("texto, esperado", [
    ("hoje", 0),
    ("Publicada hoje", 0),
    ("agora", 0),
    ("ontem", 1),
    ("há 3 dias", 3),
    ("Publicada há 2 semanas", 14),
    ("Postado há 12 horas", 0),
    ("há 1 mês", 30),
    ("há 2 meses", 60),
    ("3 days ago", 3),
    ("1 week ago", 7),
    ("há mais de 30 dias", 31),
    ("Ativa há 30+ dias", 31),
    ("03/11/2026", 4),                  # dia/mês/ano (Brasil), não março
    ("05/11/2026", 2),                  # dateutil puro leria 11 de maio
    ("2026-11-03", 4),
    ("2026-11-03T10:00:00", 4),
    ("2026-03-11", (AGORA - datetime(2026, 3, 11)).days),   # ISO nunca é lida ao contrário
    ("3 de novembro de 2026", 4),
    ("3 nov", 4),
    ("25 dez", (AGORA - datetime(2025, 12, 25)).days),      # dezembro passado, não o futuro
])
def test_idade_em_dias(texto, esperado):
    assert filtros.idade_em_dias(texto, AGORA) == esperado


@pytest.mark.parametrize("texto", ["", None, "   ", "sem data", "abc 123 xyz"])
def test_data_ilegivel_vira_none(texto):
    assert filtros.idade_em_dias(texto, AGORA) is None


def test_data_com_fuso_horario_nao_quebra():
    assert filtros.idade_em_dias("2026-11-03T10:00:00Z", AGORA) is not None


def test_data_no_futuro_nao_fica_negativa():
    assert filtros.idade_em_dias("2026-12-25", AGORA) == 0


def test_filtrar_por_data(vaga):
    vagas = [
        vaga(titulo="nova", data_publicacao="há 2 dias"),
        vaga(titulo="velha", data_publicacao="há 2 meses"),
        vaga(titulo="sem data", data_publicacao=""),
        vaga(titulo="br", data_publicacao="03/11/2026"),
    ]
    mantidas, velhas, sem_data = filtros.filtrar_por_data(vagas, 30, AGORA)
    assert [v.titulo for v in mantidas] == ["nova", "sem data", "br"]
    assert (velhas, sem_data) == (1, 1)


# ----------------------------------------------------------------- região

@pytest.mark.parametrize("local, uf", [
    ("São Paulo / SP", "SP"),
    ("São Paulo/SP", "SP"),
    ("Rio de Janeiro, RJ", "RJ"),
    ("Niterói - RJ", "RJ"),
    ("Belo Horizonte (MG)", "MG"),
    ("São Paulo, São Paulo, Brasil", "SP"),
    ("Rio de Janeiro, Rio de Janeiro, Brasil", "RJ"),
    ("Home Office - TI", None),          # TI não é UF
    ("Rio de Janeiro", None),
    ("", None),
])
def test_detectar_uf(local, uf):
    assert filtros.detectar_uf(local) == uf


def test_detectar_ufs_junta_todas():
    assert filtros.detectar_ufs("Rio de Janeiro/RJ e São Paulo/SP") == {"RJ", "SP"}


def test_filtrar_por_regiao(vaga):
    vagas = [
        vaga(titulo="a", cidade="Rio de Janeiro / RJ"),
        vaga(titulo="b", cidade="São Paulo / SP"),
        vaga(titulo="c", cidade="Rio de Janeiro"),                 # sem UF: mantém
        vaga(titulo="d", cidade="Curitiba, PR", titulo_extra=None) if False else vaga(titulo="d", cidade="Curitiba, PR"),
        vaga(titulo="e remoto", cidade="São Paulo, SP"),           # remoto: mantém
        vaga(titulo="f", cidade="Rio de Janeiro/RJ e São Paulo/SP"),  # inclui o RJ: mantém
    ]
    mantidas, removidas = filtros.filtrar_por_regiao(vagas, "RJ")
    assert [v.titulo for v in mantidas] == ["a", "c", "e remoto", "f"]
    assert removidas == 2


def test_filtrar_por_regiao_sem_uf_alvo_nao_descarta(vaga):
    vagas = [vaga(cidade="São Paulo / SP")]
    assert filtros.filtrar_por_regiao(vagas, "") == (vagas, 0)


# ------------------------------------------------------------- duplicadas

def test_normalizar_link_tira_rastreamento_e_mantem_o_id_da_vaga():
    a = "https://www.indeed.com.br/viewjob?jk=abc123&utm_source=x&fbclid=zzz#topo"
    b = "http://indeed.com.br/viewjob?fbclid=outro&jk=abc123"
    c = "https://www.indeed.com.br/viewjob?jk=OUTRA"
    assert filtros.normalizar_link(a) == filtros.normalizar_link(b)
    assert filtros.normalizar_link(a) != filtros.normalizar_link(c)


def test_normalizar_link_de_linkedin_ignora_trackingid():
    a = "https://br.linkedin.com/jobs/view/vendedor-123/?trackingId=AAA&refId=BBB"
    b = "https://br.linkedin.com/jobs/view/vendedor-123"
    assert filtros.normalizar_link(a) == filtros.normalizar_link(b)


def test_remover_duplicadas_reconhece_sufixos_juridicos_da_empresa(vaga):
    vagas = [
        vaga(titulo="Auxiliar de CPD", empresa="Mercado Alfa Ltda.", cidade="Rio de Janeiro, RJ", link="https://portal-a.test/vaga/1"),
        vaga(titulo="Auxiliar de CPD", empresa="Mercado Alfa S/A", cidade="Rio de Janeiro - RJ", link="https://portal-b.test/vaga/99"),
    ]
    unicas = filtros.remover_duplicadas(vagas)
    assert len(unicas) == 1


def test_remover_duplicadas_por_link_e_por_titulo_empresa_cidade(vaga):
    vagas = [
        vaga(titulo="Vendedor", empresa="Loja X", cidade="Rio de Janeiro, RJ", link="https://a.com/1?utm_source=z"),
        vaga(titulo="Vendedor", empresa="Loja X", cidade="Rio de Janeiro, RJ", link="https://a.com/1"),
        vaga(titulo="vendedor", empresa="LOJA X", cidade="Rio de Janeiro - RJ", link="https://b.com/9", descricao="descrição longa e completa"),
        vaga(titulo="Vendedor", empresa="", link="https://c.com/3"),
        vaga(titulo="Vendedor", empresa="", link="https://c.com/4"),   # sem empresa: não junta pelo título
    ]
    unicas = filtros.remover_duplicadas(vagas)
    assert len(unicas) == 3
    assert unicas[0].descricao == "descrição longa e completa"      # aproveitou a descrição da repetida


# ------------------------------------------------------------ enriquecimento

def test_enriquecer_vaga_usa_o_padrao_cargo_empresa_local(vaga):
    v = filtros.enriquecer_vaga(vaga(titulo="Auxiliar Administrativo - Empresa Y - Niterói"))
    assert v.empresa == "Empresa Y"
    assert v.cidade == "Niterói"


def test_enriquecer_vaga_acha_cidade_no_titulo(vaga):
    v = filtros.enriquecer_vaga(vaga(titulo="Motorista em Duque de Caxias"))
    assert v.cidade == "Duque de Caxias"


def test_enriquecer_nao_sobrescreve_o_que_ja_existe(vaga):
    v = filtros.enriquecer_vaga(vaga(titulo="A - B - Niterói", empresa="Original", cidade="Outra"))
    assert (v.empresa, v.cidade) == ("Original", "Outra")


def test_dividir_palavras_chave():
    assert filtros.dividir_palavras_chave(" vendedor , , técnico em informática ") == ["vendedor", "técnico em informática"]


def test_remover_duplicadas_nao_funde_mesmo_titulo_empresa_sem_cidade(vaga):
    vagas = [
        vaga(titulo="Auxiliar Administrativo", empresa="Empresa Alfa", cidade="", link="https://a.test/1"),
        vaga(titulo="Auxiliar Administrativo", empresa="Empresa Alfa", cidade="", link="https://b.test/2"),
    ]
    assert len(filtros.remover_duplicadas(vagas)) == 2
