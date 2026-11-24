"""A nota (e o motivo) da IA tem que cair na vaga certa. Relato real: o motivo de uma vaga de
estoque apareceu na vaga "Motorista de Ônibus Urbano", que ficou com nota 75."""

import re

import pytest

import ia
import matcher
from matcher import _normalizar_e_alinhar, ranquear_detalhado

TITULOS = ["Motorista de Ônibus Urbano", "Auxiliar de Estoque", "Relacionamento com o Cliente - Recreio"]


def _lote(vaga, *titulos):
    return [(vaga(titulo=t), 0.0, "") for t in titulos]


def _zeros():
    return {"realinhadas": 0, "sem_correspondencia": 0}


def test_resposta_certa_passa_direto(vaga):
    dados = [
        {"indice": 0, "vaga": "Motorista de Ônibus Urbano", "nota": 10, "motivo": "a"},
        {"indice": 1, "vaga": "Auxiliar de Estoque", "nota": 80, "motivo": "b"},
        {"indice": 2, "vaga": "Relacionamento com o Cliente", "nota": 70, "motivo": "c"},
    ]
    estat = _zeros()
    assert _normalizar_e_alinhar(dados, _lote(vaga, *TITULOS), estat) == {0: (10.0, "a"), 1: (80.0, "b"), 2: (70.0, "c")}
    assert estat == _zeros()


def test_nota_na_vaga_errada_e_movida_pelo_titulo(vaga):
    dados = [  # a IA trocou os índices das duas primeiras
        {"indice": 0, "vaga": "Auxiliar de Estoque", "nota": 80, "motivo": "estoque"},
        {"indice": 1, "vaga": "Motorista de Ônibus Urbano", "nota": 5, "motivo": "exige CNH D"},
        {"indice": 2, "vaga": "Relacionamento com o Cliente", "nota": 70, "motivo": "clientes"},
    ]
    estat = _zeros()
    r = _normalizar_e_alinhar(dados, _lote(vaga, *TITULOS), estat)
    assert r[0] == (5.0, "exige CNH D") and r[1] == (80.0, "estoque") and r[2] == (70.0, "clientes")
    assert estat["realinhadas"] == 2


def test_indices_comecando_em_1_sao_corrigidos(vaga):
    dados = [{"indice": i + 1, "vaga": t, "nota": 10 * (i + 1), "motivo": f"m{i}"} for i, t in enumerate(TITULOS)]
    estat = _zeros()
    r = _normalizar_e_alinhar(dados, _lote(vaga, *TITULOS), estat)
    assert r == {0: (10.0, "m0"), 1: (20.0, "m1"), 2: (30.0, "m2")}    # o índice 3 estava fora do lote
    assert estat["realinhadas"] == 2


def test_titulo_que_nao_e_de_nenhuma_vaga_e_descartado(vaga):
    estat = _zeros()
    assert _normalizar_e_alinhar([{"indice": 0, "vaga": "Cozinheiro de Navio", "nota": 90, "motivo": "x"}],
                                 _lote(vaga, *TITULOS), estat) == {}
    assert estat["sem_correspondencia"] == 1


def test_titulos_repetidos_valem_pelo_indice_informado(vaga):
    lote = _lote(vaga, "Auxiliar de Vendas", "Auxiliar de Vendas")
    assert _normalizar_e_alinhar([{"indice": 1, "vaga": "Auxiliar de Vendas", "nota": 60, "motivo": "b"}], lote) == {1: (60.0, "b")}


def test_titulos_iguais_com_indice_invalido_sao_ambiguos_e_descartados(vaga):
    lote = _lote(vaga, "Auxiliar de Vendas", "Auxiliar de Vendas")
    assert _normalizar_e_alinhar([{"indice": 7, "vaga": "Auxiliar de Vendas", "nota": 60, "motivo": "b"}], lote) == {}


def test_sem_o_campo_vaga_aceita_o_indice_como_veio(vaga):
    dados = [{"indice": 1, "nota": "85%", "motivo": "ok"}, {"indice": 9, "nota": 50, "motivo": "fora"}]
    assert _normalizar_e_alinhar(dados, _lote(vaga, *TITULOS)) == {1: (85.0, "ok")}


def test_duas_respostas_para_a_mesma_vaga_fica_a_numerada_certo(vaga):
    certa = {"indice": 1, "vaga": "Auxiliar de Estoque", "nota": 80, "motivo": "certa"}
    errada = {"indice": 0, "vaga": "Auxiliar de Estoque", "nota": 99, "motivo": "errada"}
    lote = _lote(vaga, *TITULOS)
    assert _normalizar_e_alinhar([certa, errada], lote)[1] == (80.0, "certa")
    assert _normalizar_e_alinhar([errada, certa], lote)[1] == (80.0, "certa")   # a ordem não importa


def test_aceita_resposta_embrulhada_em_objeto(vaga):
    dados = {"avaliacoes": [{"indice": 0, "vaga": "Motorista de Ônibus", "nota": 5, "motivo": "m"}]}
    assert _normalizar_e_alinhar(dados, _lote(vaga, *TITULOS)) == {0: (5.0, "m")}


# ------------------------------------------------------------------ fluxo completo do matcher

def _ia_com_indices_rotacionados(monkeypatch, notas):
    """IA que erra a numeração de todas as vagas (cada nota cai na vaga seguinte), mas cita o título certo."""
    monkeypatch.setenv("GEMINI_API_KEY", "chave-falsa")

    def falsa(prompt, max_tokens=1500, sistema=None):
        itens = re.findall(r"^(\d+)\. Título: (.*?) \|", prompt, flags=re.MULTILINE)
        return [{"indice": (int(i) + 1) % len(itens), "vaga": t, "nota": notas[t], "motivo": f"motivo de {t}"} for i, t in itens]

    monkeypatch.setattr(ia, "chamar_ia_json", falsa)


def test_ranquear_detalhado_entrega_cada_nota_na_vaga_certa(vaga, monkeypatch):
    notas = {"Motorista de Onibus Urbano": 5, "Auxiliar de Estoque": 80, "Recepcionista de Hotel": 60}
    _ia_com_indices_rotacionados(monkeypatch, notas)
    vagas = [vaga(titulo=t, descricao="Rotina de trabalho.") for t in notas]
    resultado = ranquear_detalhado("curriculo", vagas)
    por_titulo = {v.titulo: (nota, motivo) for v, nota, motivo in resultado.ranking}
    for titulo, nota in notas.items():
        assert por_titulo[titulo] == (float(nota), f"motivo de {titulo}")
    assert resultado.realinhadas == 3 and resultado.avaliadas_ia == 3


def test_resposta_que_nao_bate_com_nenhuma_vaga_e_pedida_de_novo(vaga, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "chave-falsa")
    chamadas = []

    def falsa(prompt, max_tokens=1500, sistema=None):
        itens = re.findall(r"^(\d+)\. Título: (.*?) \|", prompt, flags=re.MULTILINE)
        chamadas.append([t for _, t in itens])
        if len(chamadas) == 1:    # a 1ª tentativa avalia uma vaga que não existe no lote
            return [{"indice": 0, "vaga": itens[0][1], "nota": 70, "motivo": "boa"},
                    {"indice": 1, "vaga": "Cozinheiro de Navio", "nota": 99, "motivo": "inventada"}]
        return [{"indice": i, "vaga": t, "nota": 40, "motivo": "refeita"} for i, t in [(int(i), t) for i, t in itens]]

    monkeypatch.setattr(ia, "chamar_ia_json", falsa)
    vagas = [vaga(titulo="Auxiliar de Estoque", descricao="d"), vaga(titulo="Recepcionista de Hotel", descricao="d")]
    resultado = ranquear_detalhado("curriculo", vagas)
    assert len(chamadas) == 2 and len(chamadas[1]) == 1        # só a vaga que ficou sem nota foi pedida de novo
    assert resultado.sem_correspondencia == 1
    assert sorted(m for _, _, m in resultado.ranking) == ["boa", "refeita"]


def test_instrucoes_pedem_o_titulo_de_volta_e_proibem_inventar():
    regra = matcher._SISTEMA_RANKING
    assert '"vaga"' in regra and "primeiras palavras do TÍTULO" in regra
    assert "SOMENTE fatos" in regra and "vaga temporária" in regra


def test_versao_do_prompt_invalida_as_notas_antigas_do_cache():
    # notas guardadas antes podiam estar na vaga errada
    assert matcher.PROMPT_VERSAO not in ("2026-11-a", "2026-11-b", "2026-11-c")
