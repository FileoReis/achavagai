import pytest

import config
import privacidade
from privacidade import anonimizar_curriculo, preparar_para_ia


@pytest.mark.parametrize("texto", [
    "maria.exemplo@email.com",
    "contato: joao_silva+vagas@empresa.com.br",
])
def test_remove_email(texto):
    assert "@" not in anonimizar_curriculo(texto)
    assert "[e-mail removido]" in anonimizar_curriculo(texto)


@pytest.mark.parametrize("cpf", ["123.456.789-09", "12345678909", "123.456.78909"])
def test_remove_cpf(cpf):
    resultado = anonimizar_curriculo(f"CPF: {cpf}")
    assert "789" not in resultado
    assert "[CPF removido]" in resultado


def test_remove_rg_e_numero_da_cnh_mas_mantem_a_categoria():
    resultado = anonimizar_curriculo("RG: 12.345.678-9 | CNH nº 01234567890 | CNH categoria B")
    assert "12.345.678" not in resultado
    assert "01234567890" not in resultado
    assert "CNH categoria B" in resultado


@pytest.mark.parametrize("telefone", [
    "(21) 98765-4321",
    "(21)98765-4321",
    "21 98765-4321",
    "+55 21 98765-4321",
    "98765-4321",
    "(21) 2345-6789",
    "21 2345-6789",
    "(21) 9-8765-4321",   # hífen depois do 9: formato real encontrado em um currículo
    "(21) 9 8765-4321",
    "( 21 ) 98765-4321",
    "21 9-8765-4321",
    "9-8765-4321",
])
def test_remove_telefones_em_varios_formatos(telefone):
    resultado = anonimizar_curriculo(f"Contato {telefone} fim")
    assert "[telefone removido]" in resultado
    assert "4321" not in resultado and "6789" not in resultado


@pytest.mark.parametrize("trecho", [
    "Auxiliar administrativo (2019-2023)",
    "Curso de Excel avançado, 40 horas, 2018-2019",
    "Carga horária 40 2018-2019",
    "Operador de caixa 2017 2020",
    "Python 3.12 e Excel 365",
    "Nível 9 2018-2020",
    "Treinamento 9 2019-2021",
])
def test_nao_confunde_periodos_e_numeros_com_telefone(trecho):
    assert anonimizar_curriculo(trecho) == trecho


def test_remove_cep_links_e_endereco_mas_mantem_bairro_e_cidade():
    texto = "Rua das Flores, 123 - Bangu, Rio de Janeiro - RJ, CEP 21000-000 linkedin.com/in/maria-exemplo"
    resultado = anonimizar_curriculo(texto)
    assert "Flores" not in resultado and "21000" not in resultado and "maria-exemplo" not in resultado
    assert "Bangu" in resultado and "Rio de Janeiro" in resultado


def test_endereco_com_avenida_e_complemento():
    resultado = anonimizar_curriculo("Av. Brasil, 4500, apto 301 - Penha, Rio de Janeiro")
    assert "Brasil" not in resultado and "4500" not in resultado
    assert "Penha" in resultado


def test_frase_comum_com_a_palavra_rua_nao_e_apagada():
    texto = "Trabalhei na rua 3 anos como vendedor ambulante, depois em loja."
    assert anonimizar_curriculo(texto) == texto


def test_nascimento_vira_idade_e_data_invalida_e_removida():
    resultado = anonimizar_curriculo("Nascimento: 15/03/1996")
    assert "1996" not in resultado
    assert resultado.startswith("Idade: ") and resultado.endswith(" anos")
    assert anonimizar_curriculo("Data de nascimento: 31/02/1990") == "[nascimento removido]"


def test_texto_vazio_passa_direto():
    assert anonimizar_curriculo("") == ""
    assert anonimizar_curriculo(None) is None


def test_preparar_para_ia_respeita_a_configuracao(monkeypatch):
    texto = "fale comigo em maria@email.com"
    monkeypatch.setattr(config, "ANONIMIZAR_CURRICULO", True)
    assert "@" not in preparar_para_ia(texto)
    monkeypatch.setattr(config, "ANONIMIZAR_CURRICULO", False)
    assert preparar_para_ia(texto) == texto
    assert privacidade.anonimizar_curriculo(texto) != texto
