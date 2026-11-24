"""Regras de CNH (habilitacao.py). Caso real: "Motorista de Ônibus Urbano - Queimados - RJ",
que exige CNH D, apareceu com nota 75 para um candidato com CNH A e B."""

import pytest

from habilitacao import (
    categorias_do_curriculo,
    exigencias_da_vaga,
    filtrar_por_habilitacao,
    motivo_de_eliminacao,
)

AB = ("A", "B")


# ---------------------------------------------------------------- CNH do candidato

@pytest.mark.parametrize("texto, esperado", [
    ("CNH B", ("B",)),
    ("CNH: AB", ("A", "B")),
    ("CNH categoria AB", ("A", "B")),
    ("Habilitação categoria A e B", ("A", "B")),
    ("CNH A/B", ("A", "B")),
    ("Carteira de motorista categoria D", ("D",)),
    ("Carteira Nacional de Habilitação: C ou D", ("C", "D")),
    ("Hab. B", ("B",)),
    ("Dados pessoais\nCNH B\nNascimento ...\nHabilitação: D", ("B", "D")),
    ("Possuo CNH e experiência em vendas", ()),        # o "e" é a palavra, não a categoria E
    ("CNH vencida há muito tempo", ()),
    ("Auxiliar administrativo com Excel", ()),
    ("", ()),
])
def test_categorias_lidas_do_curriculo(texto, esperado):
    assert categorias_do_curriculo(texto) == esperado


# ---------------------------------------------------------------- o caso do relato

def test_onibus_urbano_e_eliminado_para_cnh_a_e_b_so_pelo_titulo(vaga):
    motivo = motivo_de_eliminacao(vaga(titulo="Motorista de Ônibus Urbano - Queimados - RJ"), AB)
    assert motivo == "exige CNH D (pelo cargo) e o currículo informa só CNH A, B"


def test_onibus_urbano_com_a_descricao_da_pagina(vaga):
    descricao = ("Requisitos: Curso de Transporte Coletivo de Passageiros (Resolução 789); Experiência como "
                 "motorista de ônibus ou caminhão; CNH categoria D válida; Contratação: CLT.")
    motivo = motivo_de_eliminacao(vaga(titulo="Motorista de Ônibus Urbano - Queimados - RJ", descricao=descricao), AB)
    assert motivo and "exige CNH D" in motivo and "no texto da vaga" in motivo


def test_o_texto_da_vaga_vale_mesmo_sem_a_palavra_onibus_no_titulo(vaga):
    assert motivo_de_eliminacao(vaga(titulo="Motorista", descricao="CNH categoria D válida"), AB)


def test_motorista_senior_com_onibus_entre_parenteses(vaga):
    assert motivo_de_eliminacao(vaga(titulo="Motorista Sênior (ônibus urbano) – Rio de Janeiro – RJ"), AB)


# ---------------------------------------------------------------- vagas que devem FICAR

@pytest.mark.parametrize("titulo, descricao", [
    ("Motorista - Hab B", ""),
    ("Motorista – AUXILIAR DE ESCRITÓRIO", "Exige CNH B e informática"),
    ("Motorista Agregado – Empresa de Transporte – Flamengo RJ", ""),
    ("Ajudante de motorista de ônibus", ""),
    ("Auxiliar de motorista de caminhão", "Ajudar na carga e descarga"),
    ("Mecânico de ônibus", ""),
    ("Cobrador de ônibus", ""),
    ("Auxiliar Administrativo", "Exige CNH D como diferencial"),       # diferencial não elimina
    ("Atendente", "CNH C desejável"),
    ("Atendente", "CNH D não obrigatória"),
    ("Vendedor", "CNH E experiência em vendas externas"),               # "E" sozinho é a palavra "e"
    ("Vendedor", "CNH A partir de 2 anos de experiência"),              # "A" sozinho é a palavra "a"
    ("Vendedor", "CNH A empresa oferece benefícios"),
    ("Vendedor", "Possuir CNH e A empresa oferece benefícios"),
    ("Auxiliar de estoque", ""),
])
def test_vagas_que_o_candidato_pode_ocupar_ficam(vaga, titulo, descricao):
    assert motivo_de_eliminacao(vaga(titulo=titulo, descricao=descricao), AB) is None


# ---------------------------------------------------------------- hierarquia das categorias

@pytest.mark.parametrize("candidato, fica", [
    (("B",), False), (("A", "B"), False), (("C",), False),
    (("D",), True), (("E",), True), (("A", "D"), True),
])
def test_onibus_exige_d_ou_mais(vaga, candidato, fica):
    assert (motivo_de_eliminacao(vaga(titulo="Motorista de ônibus"), candidato) is None) is fica


@pytest.mark.parametrize("candidato, fica", [
    (("B",), False), (("C",), True), (("D",), True), (("E",), True),
])
def test_caminhao_exige_c_ou_mais(vaga, candidato, fica):
    assert (motivo_de_eliminacao(vaga(titulo="Motorista de caminhão"), candidato) is None) is fica


@pytest.mark.parametrize("candidato, fica", [(("C",), False), (("D",), False), (("E",), True)])
def test_carreta_exige_e(vaga, candidato, fica):
    assert (motivo_de_eliminacao(vaga(titulo="Motorista de carreta"), candidato) is None) is fica


@pytest.mark.parametrize("candidato, fica", [(("B",), False), (("D",), False), (("A",), True), (("A", "B"), True)])
def test_motoboy_exige_a(vaga, candidato, fica):
    assert (motivo_de_eliminacao(vaga(titulo="Motoboy – entregas"), candidato) is None) is fica


# ---------------------------------------------------------------- como a vaga escreve a exigência

@pytest.mark.parametrize("texto, candidato, fica", [
    ("CNH C ou D", ("B",), False),
    ("CNH C ou D", ("D",), True),
    ("CNH C/D/E", ("B",), False),
    ("CNH C/D/E", ("C",), True),
    ("CNH categoria B", ("A",), False),      # só moto não serve para carro
    ("CNH B", ("C",), True),                 # C também dirige carro
    ("CNH A e B", ("B",), False),            # "e" = precisa das duas
    ("CNH A e B", ("A",), False),
    ("CNH A e B", ("A", "B"), True),
    ("CNH categoria A e B", ("B",), False),
    ("CNH categoria A e B", ("A", "B"), True),
    ("CNH A/B", ("A",), True),               # lista com "/": qualquer uma serve (moto OU carro)
    ("CNH A/B", ("B",), True),
    ("CNH A/B", ("C",), True),               # C também dirige carro
    ("CNH A, B", ("A",), True),
    ("CNH A ou B", ("A",), True),
    ("CNH B/E", ("B",), True),
    ("CNH D/E", ("B",), False),
    ("CNH B ou E", ("A",), False),           # só moto não serve para carro
    ("CNH AB", ("B",), True),                # "AB" colado é ambíguo: só descarta se nenhuma servir
    ("CNH AB", ("C",), True),
    ("CNH categoria E", ("D",), False),
    ("CNH categoria d válida", ("B",), False),   # depois de "categoria", minúscula também vale
    ("Habilitação D", ("B",), False),
    ("Hab. D", ("B",), False),
])
def test_exigencia_escrita_no_texto(vaga, texto, candidato, fica):
    v = vaga(titulo="Atendente", descricao=f"Requisitos: {texto}.")
    assert (motivo_de_eliminacao(v, candidato) is None) is fica


def test_letras_dentro_de_palavras_nao_viram_categoria(vaga):
    assert exigencias_da_vaga(vaga(titulo="Atendente", descricao="CNH Boa, CNH Disponível")) == []


def test_exigencia_vem_so_do_comeco_da_descricao(vaga):
    descricao = "Atividades de rotina. " * 120 + "CNH categoria D válida."
    assert motivo_de_eliminacao(vaga(titulo="Atendente", descricao=descricao), AB) is None


# ---------------------------------------------------------------- sem informação, sem descarte

@pytest.mark.parametrize("categorias", [(), None, []])
def test_sem_cnh_no_curriculo_nada_e_descartado(vaga, categorias):
    assert motivo_de_eliminacao(vaga(titulo="Motorista de ônibus"), categorias) is None


def test_exigencia_pelo_cargo_e_pelo_texto_juntas_basta_cumprir_uma(vaga):
    v = vaga(titulo="Motorista de caminhão", descricao="CNH B")
    assert motivo_de_eliminacao(v, ("B",)) is None          # o texto da vaga aceita B


# ---------------------------------------------------------------- lista de vagas

def test_filtrar_separa_validas_e_descartadas_com_o_motivo(vaga):
    onibus = vaga(titulo="Motorista de Ônibus Urbano - Queimados - RJ")
    hab_b = vaga(titulo="Motorista - Hab B")
    caminhao = vaga(titulo="Motorista de caminhão")
    validas, descartadas = filtrar_por_habilitacao([onibus, hab_b, caminhao], AB)
    assert validas == [hab_b]
    assert [v for v, _ in descartadas] == [onibus, caminhao]
    assert "CNH D" in descartadas[0][1] and "CNH C" in descartadas[1][1]


def test_lista_vazia(vaga):
    assert filtrar_por_habilitacao([], AB) == ([], [])
