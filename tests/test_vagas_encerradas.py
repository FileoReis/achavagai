"""Vagas de comparecimento cuja data já passou (ex.: "Comparecer no dia 24/08" visto em
novembro) não devem aparecer. Caso real relatado pelo usuário."""

from datetime import date

import pytest

import filtros
import matcher
from filtros import data_limite_da_vaga, enriquecer_vaga, filtrar_encerradas, vaga_encerrada

HOJE = date(2026, 11, 11)

TITULO_1 = "Auxiliar de CPD – Princesa Supermercados – Penha Circular RJ – Comparecer no dia 24/08"
TITULO_2 = "Operador de CPD – Real Supermercados – São Francisco, Niterói RJ – Comparecer em 31/07"


def test_os_dois_titulos_relatados_pelo_usuario_sao_encerrados(vaga):
    assert vaga_encerrada(vaga(titulo=TITULO_1), HOJE)
    assert vaga_encerrada(vaga(titulo=TITULO_2), HOJE)
    assert data_limite_da_vaga(vaga(titulo=TITULO_1), HOJE) == date(2026, 8, 24)
    assert data_limite_da_vaga(vaga(titulo=TITULO_2), HOJE) == date(2026, 7, 31)


@pytest.mark.parametrize("titulo, encerrada", [
    # comparecimento
    ("Auxiliar – Loja – Centro RJ – Comparecer em 12/11", False),        # amanhã
    ("Auxiliar – Loja – Centro RJ – Comparecer hoje, 11/11", False),     # hoje ainda vale
    ("Auxiliar – Loja – Centro RJ – Comparecer em 10/11", True),         # ontem
    ("Atendente – Loja X – Comparecer em 05/01", False),                 # janeiro do ano que vem
    ("Atendente – Loja X – Comparecer em 24/04", True),                  # longe demais à frente: é de abril passado
    ("Comparecer 24 de agosto", True),
    ("Comparecer no dia 24 de agosto de 2027", False),
    ("Comparecer dia 24/08/2026", True),
    ("Comparecer dia 24-08-26", True),
    ("Comparecer dia 24.08", True),
    ("Entrevistas dia 5/8", True),
    ("Seletiva presencial dia 25/11", False),
    ("Mutirão de vagas dia 02/08", True),
    # prazos
    ("Atendente – Loja X – Inscrições até 15/03", False),                # prazo longo, ainda vale
    ("Atendente – Loja X – Inscrições até 30/09", True),
    ("Trainee 2027 – inscreva-se até o dia 30/11", False),
    ("Vaga válida até 31/10", True),
    ("Encerra em 20/11", False),
    # várias datas: vale a mais tardia
    ("Entrevistas de 05/11 a 20/11", False),
    ("Comparecer em 24/08 ou 25/08", True),
    ("Comparecer em 24/08 ou 25/11", False),
    # sem data de fim, ou datas que não são prazo
    ("Programa de Estágio – inscrições abertas desde 01/09", False),     # início, não fim
    ("Inscrições a partir de 01/09", False),
    ("Auxiliar Administrativo", False),
    ("Experiência de 2018 a 2020 e CNH vencida em 10/2019", False),
    ("Vendedor – Loja Y – Comparecer às 8.30 na loja", False),
    ("Atendente – salário até R$ 2.500,00 e 12/36", False),
    ("Entrevista online, horário a combinar", False),
    ("Comparecer em 29/02", False),                                      # data inexistente nos anos considerados
    ("Comparecer em 45/13", False),
])
def test_deteccao_de_data_passada(vaga, titulo, encerrada):
    assert vaga_encerrada(vaga(titulo=titulo), HOJE) is encerrada


def test_data_na_descricao_tambem_vale(vaga):
    v = vaga(titulo="Auxiliar de CPD", descricao="Comparecer na loja no dia 05/08 com documentos.")
    assert vaga_encerrada(v, HOJE)


def test_descricao_longa_so_e_lida_no_comeco(vaga):
    descricao = "Atividades de rotina. " * 100 + "Entrevistas no dia 05/08."   # a data está bem depois do começo
    assert not vaga_encerrada(vaga(titulo="Auxiliar", descricao=descricao), HOJE)


def test_filtrar_encerradas_separa_e_informa_a_data(vaga):
    a, b, c = vaga(titulo=TITULO_1), vaga(titulo=TITULO_2), vaga(titulo="Recepcionista – Hotel X – Comparecer em 20/11")
    validas, encerradas = filtrar_encerradas([a, b, c], HOJE)
    assert validas == [c]
    assert encerradas == [(a, date(2026, 8, 24)), (b, date(2026, 7, 31))]


def test_virada_de_ano(vaga):
    dezembro = date(2026, 12, 20)
    assert not vaga_encerrada(vaga(titulo="Comparecer em 05/01"), dezembro)    # logo ali
    assert vaga_encerrada(vaga(titulo="Comparecer em 05/12"), dezembro)        # já passou
    janeiro = date(2027, 1, 10)
    assert vaga_encerrada(vaga(titulo="Comparecer em 28/12"), janeiro)         # do ano passado


def test_usa_o_hoje_do_sistema_quando_nao_informado(vaga, monkeypatch):
    monkeypatch.setattr(filtros, "_hoje", lambda: date(2026, 8, 20))
    assert not vaga_encerrada(vaga(titulo=TITULO_1))      # 24/08 ainda não chegou
    monkeypatch.setattr(filtros, "_hoje", lambda: date(2026, 9, 1))
    assert vaga_encerrada(vaga(titulo=TITULO_1))          # agora já passou


# ---------------------------------------------------------------------------
# enriquecer_vaga: o local não é mais lido do último trecho do título
# ---------------------------------------------------------------------------

def test_local_vem_do_trecho_certo_mesmo_com_aviso_de_comparecimento_no_fim(vaga):
    v = enriquecer_vaga(vaga(titulo=TITULO_1))
    assert v.empresa == "Princesa Supermercados"
    assert v.cidade == "Penha Circular RJ"
    v = enriquecer_vaga(vaga(titulo=TITULO_2))
    assert v.empresa == "Real Supermercados"
    assert v.cidade == "São Francisco, Niterói RJ"


def test_titulo_simples_com_local_no_fim_continua_funcionando(vaga):
    v = enriquecer_vaga(vaga(titulo="Vendedor – Bangu RJ"))
    assert v.cidade == "Bangu RJ"


# ---------------------------------------------------------------------------
# IA: recebe a data de hoje e a regra de vaga encerrada
# ---------------------------------------------------------------------------

def test_prompt_da_ia_traz_a_data_de_hoje(vaga):
    prompt = matcher._montar_prompt_ranking("curriculo", [(vaga(titulo="X"), 0.0, "")], {"hoje": HOJE, "cidade": "Rio de Janeiro"})
    assert "Data de hoje: 11/11/2026" in prompt
    assert "Cidade de busca do candidato: Rio de Janeiro" in prompt


def test_prompt_da_ia_usa_a_data_real_quando_nao_informada(vaga, monkeypatch):
    monkeypatch.setattr(matcher, "_hoje", lambda: date(2027, 1, 5))
    prompt = matcher._montar_prompt_ranking("curriculo", [(vaga(titulo="X"), 0.0, "")], None)
    assert "Data de hoje: 05/01/2027" in prompt


def test_regra_de_vaga_encerrada_esta_nas_instrucoes_da_ia():
    regra = matcher._SISTEMA_RANKING
    assert "Vaga encerrada" in regra and "JÁ PASSOU" in regra and "Data de hoje" in regra
    assert "nota 0" in regra


def test_versao_do_prompt_mudou_para_invalidar_notas_antigas_do_cache():
    # notas guardadas com o prompt antigo davam nota alta a vagas já encerradas
    assert matcher.PROMPT_VERSAO != "2026-11-a"


# ---------------------------------------------------------------------------
# Relato: "Motorista de Ônibus Urbano - Queimados - RJ" saía com empresa "Queimados" e cidade "RJ"
# ---------------------------------------------------------------------------

def test_cargo_cidade_uf_nao_tem_empresa(vaga):
    v = enriquecer_vaga(vaga(titulo="Motorista de Ônibus Urbano - Queimados - RJ"))
    assert v.empresa == "" and v.cidade == "Queimados, RJ"
    v = enriquecer_vaga(vaga(titulo="Motorista Sênior (ônibus urbano) – Rio de Janeiro – RJ"))
    assert v.empresa == "" and v.cidade == "Rio de Janeiro, RJ"


def test_cargo_empresa_local_continua_funcionando(vaga):
    v = enriquecer_vaga(vaga(titulo="Vendedor – Empresa X – Bangu RJ"))
    assert v.empresa == "Empresa X" and v.cidade == "Bangu RJ"


def test_nao_sobrescreve_empresa_e_cidade_que_ja_vieram(vaga):
    v = enriquecer_vaga(vaga(titulo="Motorista - Queimados - RJ", empresa="Viação Real", cidade="Queimados"))
    assert v.empresa == "Viação Real" and v.cidade == "Queimados"


def test_motivo_de_encerramento_traz_a_data(vaga):
    assert "24/08/2026" in filtros.motivo_de_encerramento(vaga(titulo=TITULO_1), HOJE)
    assert filtros.motivo_de_encerramento(vaga(titulo="Auxiliar Administrativo"), HOJE) is None
    assert filtros.motivo_de_encerramento(vaga(titulo="Recepcionista – Comparecer em 20/11"), HOJE) is None
