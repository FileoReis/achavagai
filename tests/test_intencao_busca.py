from types import SimpleNamespace

import pytest

from intencao_busca import compilar_intencoes, filtrar_por_intencao, vaga_corresponde


def vaga(titulo, descricao="", cidade=""):
    return SimpleNamespace(titulo=titulo, descricao=descricao, cidade=cidade)


def test_cpd_e_reconhecido_como_sigla_exata():
    intencoes = compilar_intencoes(["CPD"])
    assert vaga_corresponde(vaga("Auxiliar de CPD"), intencoes)
    assert vaga_corresponde(vaga("Assistente", "Atuação na Central de Processamento de Dados"), intencoes)


def test_cpd_nao_e_confundido_com_pcd():
    intencoes = compilar_intencoes(["CPD"])
    assert not vaga_corresponde(vaga("Vaga exclusiva para PCD"), intencoes)
    assert not vaga_corresponde(vaga("Pessoa com deficiência", "PCD"), intencoes)


def test_metadado_de_cidade_nao_valida_termo_de_cargo():
    assert not vaga_corresponde(vaga("Supervisor de Produção", cidade="Fechamento CPD Rio de Janeiro / RJ"),
                                compilar_intencoes(["CPD"]))


def test_informatica_reconhece_sinonimos_profissionais():
    intencoes = compilar_intencoes(["Informatica"])
    assert vaga_corresponde(vaga("Técnico de Suporte", "Atendimento de help desk e redes de computadores"), intencoes)
    assert vaga_corresponde(vaga("Analista de TI N1"), intencoes)


def test_motorista_nao_confunde_vendas_ou_atendimento():
    intencoes = compilar_intencoes(["Motorista"])
    assert vaga_corresponde(vaga("Motorista de Transporte Utilitário"), intencoes)
    assert not vaga_corresponde(vaga("Vendedor", "Atendimento ao cliente e vendas"), intencoes)


def test_varios_termos_sao_uniao_or_e_preservam_os_relevantes():
    vagas = [vaga("Auxiliar de CPD"), vaga("Motorista B"), vaga("Vendedor"), vaga("Técnico de Informática")]
    mantidas, descartadas = filtrar_por_intencao(vagas, ["CPD", "Motorista", "Informática"])
    assert [x.titulo for x in mantidas] == ["Auxiliar de CPD", "Motorista B", "Técnico de Informática"]
    assert [x.titulo for x in descartadas] == ["Vendedor"]


def test_reconhece_titulo_concatenado_tecnico_deinformatica_n1():
    intencoes = compilar_intencoes(["Informática"])
    assert vaga_corresponde(vaga("Técnico deInformaticaN1"), intencoes)


def test_reconhece_titulo_concatenado_motoristacarga():
    intencoes = compilar_intencoes(["Motorista"])
    assert vaga_corresponde(vaga("MotoristaCarga"), intencoes)


def test_cpd_continua_sem_confundir_pcd_apos_flexibilidade():
    intencoes = compilar_intencoes(["CPD"])
    assert vaga_corresponde(vaga("Auxiliar de CPD"), intencoes)
    assert not vaga_corresponde(vaga("Assistente PCD"), intencoes)
