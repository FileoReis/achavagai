from types import SimpleNamespace

from classificacao import classificar_vaga


def vaga(titulo, descricao=""):
    return SimpleNamespace(titulo=titulo, descricao=descricao)


def perfil():
    return SimpleNamespace(
        areas_atuacao=["Gestão e Operações", "Logística e Distribuição", "Suporte Técnico e TI", "Vendas e Atendimento"],
        habilidades=["Controle de estoque", "Rotinas administrativas", "Redes locais"],
        cargos_compativeis=["Gerente Operacional", "Suporte Técnico", "Consultor de Vendas"],
        cargo_sugerido="Gerente Operacional",
        experiencia_conducao_comprovada=False,
        objetivo_conducao_declarado=False,
    )


def test_classifica_cargo_pesquisado_se_titulo_corresponde():
    assert classificar_vaga(vaga("Técnico deInformaticaN1"), ["Informática"], perfil()) == "Pesquisa direta"


def test_mencao_incidental_na_descricao_nao_transforma_cargo_em_pesquisa_direta():
    assert classificar_vaga(vaga("Auxiliar Administrativo", "Atuará no Centro de Processamento de Dados"), ["CPD"], perfil()) == "Compatível com currículo"


def test_cpd_no_titulo_e_correspondencia_direta():
    assert classificar_vaga(vaga("Auxiliar Administrativo (CPD)"), ["CPD"], perfil()) == "Pesquisa direta"


def test_tecnico_de_ti_e_sinonimo_direto_de_informatica():
    assert classificar_vaga(vaga("Técnico de TI Jr."), ["Informática"], perfil()) == "Pesquisa direta"


def test_cargo_motorista_sugerido_pela_ia_nao_vira_compativel_sem_evidencia():
    p = perfil()
    p.cargos_compativeis.append("Motorista de Carga")
    assert classificar_vaga(vaga("Motorista de Carga"), ["CPD"], p) == "Alternativa"


def test_ajudante_de_motorista_pode_ser_compativel_com_experiencia_em_logistica():
    assert classificar_vaga(vaga("Ajudante de Motorista"), ["CPD"], perfil()) == "Compatível com currículo"


def test_classifica_estoque_como_compativel_sem_promover_motorista():
    p = perfil()
    assert classificar_vaga(vaga("Estoquista"), ["Motorista"], p) == "Compatível com currículo"
    assert classificar_vaga(vaga("Motorista de Carga"), ["CPD"], p) == "Alternativa"


def test_classifica_motorista_como_compativel_somente_com_evidencia_profissional():
    p = perfil()
    p.experiencia_conducao_comprovada = True
    assert classificar_vaga(vaga("Motorista Executivo"), ["CPD"], p) == "Compatível com currículo"


def test_recepcionista_e_compativel_com_perfil_de_atendimento():
    assert classificar_vaga(vaga("Recepcionista"), ["Motorista", "CPD"], perfil()) == "Compatível com currículo"


def test_operador_de_loja_sem_familia_profissional_ativa_fica_em_alternativas():
    assert classificar_vaga(vaga("Operador de Loja"), ["Motorista", "CPD"], perfil()) == "Alternativa"
