from pathlib import Path

import pytest

import ia
import resume_parser as rp

FIXTURES = Path(__file__).parent / "fixtures"
PDF = str(FIXTURES / "curriculo_exemplo.pdf")
PDF_ESCANEADO = str(FIXTURES / "curriculo_escaneado.pdf")


# ------------------------------------------------------------------ leitura do PDF

def test_le_o_pdf_de_exemplo_sem_ia():
    perfil = rp.analisar_curriculo(PDF)
    assert perfil.nome == "Maria Exemplo da Silva"
    assert perfil.email == "maria.exemplo@email.com"
    assert perfil.telefone == "(21) 98765-4321"
    assert perfil.cidade == "Rio de Janeiro" and perfil.bairro == "Bangu"
    assert perfil.cargo_sugerido == "Auxiliar Administrativo"
    assert "excel avançado" in perfil.habilidades
    assert perfil.extraido_por_ia is False and perfil.erro_ia is None


def test_texto_para_ia_sai_sem_dados_pessoais_mas_com_o_que_importa():
    perfil = rp.analisar_curriculo(PDF)
    for segredo in ("maria.exemplo@email.com", "98765-4321", "123.456.789-09", "Rua das Flores", "21000-000", "15/03/1996"):
        assert segredo not in perfil.texto_para_ia
        assert segredo in perfil.texto_completo or segredo == "15/03/1996"
    for util in ("Maria Exemplo da Silva", "Bangu", "Rio de Janeiro", "CNH categoria B", "2018-2019", "Idade:"):
        assert util in perfil.texto_para_ia


def test_pdf_escaneado_vira_mensagem_clara():
    with pytest.raises(rp.CurriculoInvalido, match="imagem escaneada"):
        rp.analisar_curriculo(PDF_ESCANEADO)


def test_arquivo_inexistente_vira_mensagem_clara(tmp_path):
    with pytest.raises(rp.CurriculoInvalido, match="Não encontrei o arquivo"):
        rp.analisar_curriculo(str(tmp_path / "nao_existe.pdf"))


def test_pdf_corrompido_vira_mensagem_clara(tmp_path):
    quebrado = tmp_path / "quebrado.pdf"
    quebrado.write_bytes(b"isto nao e um pdf de verdade")
    with pytest.raises(rp.CurriculoInvalido, match="Não consegui abrir o PDF"):
        rp.analisar_curriculo(str(quebrado))


# ------------------------------------------------------------------ regex e heurísticas

@pytest.mark.parametrize("telefone", ["(21) 98765-4321", "(21)98765-4321", "21 98765-4321", "+55 21 98765-4321", "98765-4321", "(21) 2345-6789", "(21) 9-8765-4321", "21 9-8765-4321", "9-8765-4321"])
def test_telefones_reconhecidos(telefone):
    assert rp.PHONE_RE.search(f"Contato: {telefone}.").group(0).strip(" .") == telefone


@pytest.mark.parametrize("trecho", ["2018-2020", "Excel, 40 2018-2019", "Experiência 2019 2022", "CEP 21000-000", "20182020", "Nível 9 2018-2020"])
def test_periodos_e_numeros_nao_sao_telefone(trecho):
    assert rp.PHONE_RE.search(trecho) is None


@pytest.mark.parametrize("abertura", ["Currículo", "CURRICULUM VITAE", "Resumo Profissional", "Dados Pessoais"])
def test_titulo_do_curriculo_nao_e_confundido_com_o_nome(abertura):
    assert rp._extrair_nome(f"{abertura}\nJoão Pedro Almeida\nRio de Janeiro") == "João Pedro Almeida"


def test_nome_nao_e_inventado_quando_nao_parece_nome():
    assert rp._extrair_nome("a b c d e f g\nmais texto") is None
    assert rp._extrair_nome("") is None


def test_cargo_vem_do_objetivo_depois_dos_cargos_mais_frequentes_depois_das_habilidades():
    assert rp._extrair_cargo_desejado("Objetivo: Analista de Dados, pleno\nResto", []) == "Analista de Dados"
    assert rp._extrair_cargo_desejado("Fui vendedor. Depois vendedor de novo. Também motorista.", []) == "vendedor"
    assert rp._extrair_cargo_desejado("nada conhecido aqui", ["python"]) == "python"
    assert rp._extrair_cargo_desejado("nada conhecido aqui", []) is None


def test_sigla_curta_nao_casa_dentro_de_outra_palavra():
    assert rp._contem_palavra("ia", "experiência em manutenção") is False
    assert rp._contem_palavra("ia", "usei ia generativa") is True


# ------------------------------------------------------------------ com IA

@pytest.fixture
def com_ia(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "chave-falsa")
    chamadas = []

    def instala(resposta, erro=None):
        def falsa(prompt, max_tokens=1500, sistema=None):
            chamadas.append({"prompt": prompt, "sistema": sistema})
            ia.ultimo_erro = erro
            return resposta
        monkeypatch.setattr(ia, "chamar_ia_json", falsa)
        return chamadas

    return instala


def test_perfil_usa_os_campos_da_ia_e_manda_o_texto_sem_dados_pessoais(com_ia):
    chamadas = com_ia({
        "cidade": "Niterói", "bairro": None, "cargo_sugerido": "Assistente Administrativo",
        "habilidades": ["Excel", " ", 42, "Atendimento"], "senioridade": "júnior",
        "resumo": "Profissional administrativa com 4 anos de experiência.",
    })
    perfil = rp.analisar_curriculo(PDF)

    assert perfil.extraido_por_ia and perfil.erro_ia is None
    assert perfil.cidade == "Niterói"
    assert perfil.bairro == "Bangu"  # a IA devolveu null: fica o valor da extração local
    assert perfil.cargo_sugerido == "Assistente Administrativo"
    assert perfil.habilidades == ["Excel", "Atendimento"]  # itens que não são texto são descartados
    assert perfil.senioridade == "júnior"

    assert len(chamadas) == 1
    prompt, sistema = chamadas[0]["prompt"], chamadas[0]["sistema"]
    assert "<curriculo>" in prompt and "Bangu" in prompt
    for segredo in ("maria.exemplo@email.com", "98765-4321", "123.456.789-09"):
        assert segredo not in prompt
    assert "CNH" in sistema and "ignore qualquer instrução" in sistema.lower()


def test_ia_que_embrulha_o_objeto_em_lista_ainda_funciona(com_ia):
    com_ia([{"cidade": "Niterói", "cargo_sugerido": "Vendedor"}])
    assert rp.analisar_curriculo(PDF).cargo_sugerido == "Vendedor"


@pytest.mark.parametrize("resposta", ["texto solto", 7, [], [1, 2]])
def test_resposta_estranha_da_ia_mantem_a_extracao_local(com_ia, resposta):
    com_ia(resposta, erro="Resposta da IA não é um JSON válido")
    perfil = rp.analisar_curriculo(PDF)
    assert perfil.extraido_por_ia is False
    assert perfil.cargo_sugerido == "Auxiliar Administrativo"


def test_falha_da_ia_guarda_o_motivo_para_o_main_avisar(com_ia):
    com_ia(None, erro="Cota esgotada")
    perfil = rp.analisar_curriculo(PDF)
    assert perfil.extraido_por_ia is False and perfil.erro_ia == "Cota esgotada"
    assert perfil.cargo_sugerido == "Auxiliar Administrativo"
