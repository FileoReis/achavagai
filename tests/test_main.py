"""Testes do fluxo completo (main.py) com scrapers e IA falsos: nada aqui acessa a internet."""

import copy
import io
import re
from pathlib import Path

import pytest
import requests
from openpyxl import load_workbook
from rich.console import Console

import config
import descricoes
import ia
import main
import matcher
import mensagem

FIXTURES = Path(__file__).parent / "fixtures"
PDF = str(FIXTURES / "curriculo_exemplo.pdf")
PDF_ESCANEADO = str(FIXTURES / "curriculo_escaneado.pdf")


@pytest.fixture(autouse=True)
def sem_internet(monkeypatch):
    def bloqueado(*args, **kwargs):
        raise AssertionError("os testes não podem acessar a internet")
    monkeypatch.setattr(requests.sessions.Session, "request", bloqueado)


class App:
    """Monta um main.py isolado: tela capturada, pasta do projeto temporária e
    scrapers falsos. `fontes[...]` recebe a lista de vagas (ou uma exceção) que cada site devolve."""

    def __init__(self, monkeypatch, tmp_path, vaga):
        self.tmp, self.vaga = tmp_path, vaga
        self.tela = io.StringIO()
        self.termos_pedidos: list[str] = []
        self.fontes = {nome: [] for nome in ("linkedin", "indeed", "vagas_com", "infojobs", "wordpress")}

        monkeypatch.setattr(main, "console", Console(file=self.tela, width=240, color_system=None))
        monkeypatch.setattr(main, "BASE_DIR", tmp_path)
        monkeypatch.setattr(main, "ERRO_SCRAPERS", None)
        monkeypatch.setattr(main, "SITES_ATIVOS", {
            "linkedin": True, "indeed": True, "vagas_com": True, "infojobs": True,
            "riovagas": False, "rioemprega": False, "rioempregos": False, "vagasrio": False,
            "empregare": False, "empregando_brasil": False, "jooble": False, "gupy": False,
        })
        monkeypatch.setattr(config, "DESCRICAO_DELAY_SECONDS", 0)
        for modulo in (descricoes, matcher, mensagem):
            monkeypatch.setattr(modulo, "_dormir", lambda segundos: None)
        for nome in ("linkedin", "indeed", "vagas_com", "infojobs"):
            monkeypatch.setattr(main, f"buscar_vagas_{nome}", self._site(nome))
        monkeypatch.setattr(main, "buscar_vagas_todos_wordpress", self._site("wordpress", dois_argumentos=False))

    def _site(self, nome, dois_argumentos=True):
        def busca(termo, segundo):
            self.termos_pedidos.append(f"{nome}:{termo}")
            conteudo = self.fontes[nome]
            if isinstance(conteudo, Exception):
                raise conteudo
            return [copy.copy(v) for v in conteudo]
        return busca

    def v(self, **campos):
        return self.vaga(**campos)

    def rodar(self, *flags, pdf=PDF, cargo="auxiliar administrativo, recepcionista", dias="30"):
        argumentos = [pdf, "--sim", "--cidade", "Rio de Janeiro", "--cargo", cargo, "--dias", dias,
                      "--saida", str(self.tmp / "saida"), *flags]
        main.main(argumentos)

    @property
    def texto(self) -> str:
        return self.tela.getvalue()

    def planilha(self):
        arquivos = sorted((self.tmp / "saida").glob("vagas_encontradas_*.xlsx"), key=lambda p: p.stat().st_mtime)
        assert arquivos, "nenhuma planilha foi gerada\n" + self.texto
        return load_workbook(arquivos[-1])

    def linhas(self):
        aba = self.planilha()["Vagas"]
        cabecalho = [c.value for c in aba[1]]
        return [dict(zip(cabecalho, [c.value for c in linha])) for linha in aba.iter_rows(min_row=2)]

    def titulos(self):
        return {linha["Cargo / Título"] for linha in self.linhas()}


@pytest.fixture
def app(monkeypatch, tmp_path, vaga):
    return App(monkeypatch, tmp_path, vaga)


@pytest.fixture
def cenario(app):
    """Um dia típico: duplicadas entre sites, vaga antiga, vaga de outro estado, título com
    símbolos que quebrariam a tela, um site fora do ar e outro sem resultado."""
    app.fontes["linkedin"] = [
        app.v(titulo="Auxiliar Administrativo Alta", empresa="Empresa A", cidade="Rio de Janeiro, RJ",
              link="https://vagas.example/1?trackingId=abc", data_publicacao="há 2 dias",
              descricao="Atendimento ao cliente e planilhas de Excel.", fonte="LinkedIn"),
        app.v(titulo="Auxiliar Administrativo SP", empresa="Empresa SP", cidade="São Paulo / SP",
              link="https://vagas.example/sp", data_publicacao="hoje", fonte="LinkedIn"),
    ]
    app.fontes["indeed"] = [
        app.v(titulo="Auxiliar Administrativo Alta", empresa="Empresa A", cidade="Rio de Janeiro, RJ",
              link="https://vagas.example/1?trackingId=zzz", data_publicacao="há 2 dias", fonte="Indeed"),
        app.v(titulo="Auxiliar Administrativo Antigo", empresa="Loja B", cidade="Niterói - RJ",
              link="https://vagas.example/antiga", data_publicacao="há 45 dias", fonte="Indeed"),
    ]
    app.fontes["vagas_com"] = [
        app.v(titulo="Recepcionista [urgente] [/oops]", empresa="Hotel C", cidade="Rio de Janeiro / RJ",
              link="https://vagas.example/3", data_publicacao="ontem", descricao="Receber hóspedes.", fonte="Vagas.com"),
    ]
    app.fontes["infojobs"] = RuntimeError("o site mudou o HTML")
    app.fontes["wordpress"] = []
    return app


@pytest.fixture
def ia_falsa(monkeypatch):
    """IA falsa: nota 90 para títulos com 'Alta', 50 para o resto. Registra o que recebeu."""
    monkeypatch.setenv("GEMINI_API_KEY", "chave-falsa")
    registro = {"ranking": [], "perfil": 0, "mensagens": 0}

    def json_falso(prompt, max_tokens=1500, sistema=None):
        if sistema and "recrutador" in sistema:
            registro["ranking"].append(prompt)
            itens = re.findall(r"^(\d+)\. Título: (.*?) \|", prompt, flags=re.MULTILINE)
            return [{"indice": int(i), "nota": 90 if "Alta" in t else 50, "motivo": f"Experiência concreta {i}"}
                    for i, t in itens]
        registro["perfil"] += 1
        return {"cidade": "Rio de Janeiro", "bairro": "Bangu", "cargo_sugerido": "Auxiliar Administrativo",
                "habilidades": ["Excel", "Atendimento"], "senioridade": "júnior", "resumo": "Auxiliar administrativa."}

    def texto_falso(prompt, max_tokens=1500, json_mode=False, sistema=None):
        registro["mensagens"] += 1
        return "Olá! Tenho experiência na área e gostaria de conversar sobre a vaga."

    monkeypatch.setattr(ia, "chamar_ia_json", json_falso)
    monkeypatch.setattr(ia, "chamar_ia", texto_falso)
    return registro


# ------------------------------------------------------------------ sem IA

def test_fluxo_sem_ia_filtra_deduplica_e_gera_a_planilha(cenario):
    cenario.rodar("--sem-ia", "--sem-analise-profunda")

    assert cenario.titulos() == {"Auxiliar Administrativo Alta", "Recepcionista [urgente] [/oops]"}
    tela = cenario.texto
    assert "LinkedIn: 2 vaga(s)" in tela and "Indeed: 2 vaga(s)" in tela
    assert "InfoJobs: falhou" in tela and "o site mudou o HTML" in tela      # um site quebrado não derruba os outros
    assert "Portais regionais: 0 vaga(s)" in tela and "nenhum anúncio foi extraído" in tela
    assert "1 repetida(s) removida(s)" in tela
    assert "publicada(s) há mais de 30 dias" in tela
    assert "1 vaga(s) de fora do estado RJ" in tela
    assert "Recepcionista [urgente] [/oops]" in tela                          # símbolos aparecem como texto, não somem
    assert "a nota mínima não foi aplicada" in tela


def test_planilha_traz_nota_motivo_vazio_e_link_clicavel(cenario):
    cenario.rodar("--sem-ia", "--sem-analise-profunda")
    linhas = {l["Cargo / Título"]: l for l in cenario.linhas()}
    admin = linhas["Auxiliar Administrativo Alta"]
    assert admin["Empresa"] == "Empresa A" and admin["Fonte"] == "LinkedIn"
    assert admin["Link"].startswith("https://vagas.example/1")
    assert not admin["Motivo (IA)"]
    assert admin["Pontuação (%)"] >= linhas["Recepcionista [urgente] [/oops]"]["Pontuação (%)"]


def test_busca_com_varios_cargos_pede_cada_termo_a_cada_site(cenario):
    cenario.fontes["infojobs"] = []
    cenario.rodar("--sem-ia", "--sem-analise-profunda", cargo="auxiliar administrativo, recepcionista")
    pedidos = set(cenario.termos_pedidos)
    for site in ("linkedin", "indeed", "vagas_com", "infojobs", "wordpress"):
        assert {f"{site}:auxiliar administrativo", f"{site}:recepcionista"} <= pedidos
    assert "auxiliar administrativo: " in cenario.texto  # detalhe por termo no resumo de cada site


def test_busca_sequencial_da_o_mesmo_resultado(cenario, monkeypatch):
    monkeypatch.setattr(config, "BUSCA_PARALELA", False)
    cenario.rodar("--sem-ia", "--sem-analise-profunda")
    assert cenario.titulos() == {"Auxiliar Administrativo Alta", "Recepcionista [urgente] [/oops]"}


def test_nenhuma_vaga_na_busca_termina_sem_erro(app):
    with pytest.raises(SystemExit) as saida:
        app.rodar("--sem-ia", cargo="CPD")
    assert saida.value.code == 0 and "Nenhuma vaga encontrada" in app.texto


def test_nota_minima_alta_ainda_salva_tudo_o_que_foi_avaliado(cenario):
    with pytest.raises(SystemExit) as saida:
        cenario.rodar("--sem-ia", "--sem-analise-profunda", "--nota-minima", "99")
    assert saida.value.code == 0
    assert "Nenhuma vaga passou do filtro de nota mínima" in cenario.texto
    assert len(cenario.linhas()) == 2


# ------------------------------------------------------------------ com IA

def test_fluxo_com_ia_usa_notas_e_motivos_da_ia(cenario, ia_falsa):
    cenario.rodar("--sem-analise-profunda")
    linhas = cenario.linhas()
    assert [l["Cargo / Título"] for l in linhas][0] == "Auxiliar Administrativo Alta"
    assert linhas[0]["Pontuação (%)"] == 90 and linhas[1]["Pontuação (%)"] == 50
    assert str(linhas[0]["Motivo (IA)"]).startswith("Experiência concreta")
    assert ia_falsa["perfil"] == 1 and len(ia_falsa["ranking"]) == 1
    assert "2 vaga(s) avaliada(s) agora" in cenario.texto


def test_prompt_de_ranking_leva_o_contexto_e_nunca_dados_pessoais(cenario, ia_falsa):
    cenario.rodar("--sem-analise-profunda")
    prompt = ia_falsa["ranking"][0]
    assert "Cidade de busca do candidato: Rio de Janeiro" in prompt and "Estado (UF) de interesse: RJ" in prompt
    assert "Auxiliar Administrativo Alta" in prompt and "<curriculo>" in prompt
    for segredo in ("maria.exemplo@email.com", "98765-4321", "123.456.789-09", "Rua das Flores"):
        assert segredo not in prompt


def test_segunda_execucao_reaproveita_notas_e_marca_vaga_nova(cenario, ia_falsa):
    cenario.rodar("--sem-analise-profunda")
    assert len(ia_falsa["ranking"]) == 1
    assert (cenario.tmp / config.HISTORICO_ARQUIVO).is_file()

    cenario.fontes["wordpress"] = [
        cenario.v(titulo="Assistente Administrativo Alta", empresa="Empresa D", cidade="Rio de Janeiro - RJ",
                  link="https://vagas.example/novinha", data_publicacao="hoje", fonte="RioVagas"),
    ]
    cenario.tela.truncate(0), cenario.tela.seek(0)
    cenario.rodar("--sem-analise-profunda")

    assert len(ia_falsa["ranking"]) == 2                          # só uma chamada nova...
    assert ia_falsa["ranking"][1].count(". Título:") == 1         # ...e só com a vaga nova
    assert "2 reaproveitada(s) do histórico" in cenario.texto
    por_titulo = {l["Cargo / Título"]: l for l in cenario.linhas()}
    assert por_titulo["Assistente Administrativo Alta"]["Nova"] == "sim"
    assert not por_titulo["Auxiliar Administrativo Alta"]["Nova"]
    assert "NOVA" in cenario.texto


def test_sem_cache_pede_tudo_de_novo_a_ia(cenario, ia_falsa):
    cenario.rodar("--sem-analise-profunda")
    cenario.rodar("--sem-analise-profunda", "--sem-cache")
    assert len(ia_falsa["ranking"]) == 2 and ia_falsa["ranking"][1].count(". Título:") == 2


def test_ia_que_falha_cai_para_o_ranking_local_e_explica(cenario, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "chave-falsa")

    def falha(prompt, max_tokens=1500, sistema=None):
        ia.ultimo_erro = "Cota do Gemini esgotada"
        return None

    monkeypatch.setattr(ia, "chamar_ia_json", falha)
    cenario.rodar("--sem-analise-profunda")

    assert len(cenario.linhas()) == 2                                   # nada se perde
    assert "falhou nesta execução" in cenario.texto and "Cota do Gemini esgotada" in cenario.texto
    assert "a nota mínima não foi aplicada" in cenario.texto


def test_analise_profunda_le_a_descricao_completa_menos_no_linkedin(cenario, ia_falsa, monkeypatch):
    cenario.fontes["indeed"] = cenario.fontes["vagas_com"] = []  # só as duas vagas abaixo entram na conta
    cenario.fontes["linkedin"] = [
        cenario.v(titulo="Auxiliar Administrativo Alta", empresa="Empresa A", cidade="Rio de Janeiro, RJ",
                  link="https://emprego.example/vaga/9", data_publicacao="hoje", descricao="curta"),
        cenario.v(titulo="Assistente Administrativo Alta", empresa="Empresa L", cidade="Rio de Janeiro, RJ",
                  link="https://www.linkedin.com/jobs/view/1", data_publicacao="hoje", descricao="curta"),
    ]
    baixadas = []

    def baixa(url, sessao=None):
        baixadas.append(url)
        return "DESCRICAO COMPLETA com muitos detalhes sobre a rotina, requisitos e benefícios da vaga."

    monkeypatch.setattr(descricoes, "buscar_pagina", baixa)
    cenario.rodar()

    assert baixadas == ["https://emprego.example/vaga/9"]
    assert "DESCRICAO COMPLETA" in ia_falsa["ranking"][0]
    assert "Descrição completa obtida para 1 de 1 vaga(s) tentadas, 1 de sites pulados" in cenario.texto


def test_sem_analise_profunda_nao_baixa_pagina_nenhuma(cenario, ia_falsa, monkeypatch):
    monkeypatch.setattr(descricoes, "buscar_pagina", lambda *a, **k: pytest.fail("não devia baixar nada"))
    cenario.rodar("--sem-analise-profunda")


def test_com_mensagens_gera_painel_e_segunda_aba(cenario, ia_falsa):
    cenario.rodar("--sem-analise-profunda", "--com-mensagens", "--top-mensagens", "2")
    assert ia_falsa["mensagens"] == 2
    assert "Mensagens de candidatura sugeridas" in cenario.texto
    assert "Mensagens de Candidatura" in cenario.planilha().sheetnames


# ------------------------------------------------------------------ problemas de ambiente

def test_pasta_scrapers_ausente_explica_o_que_fazer(app, monkeypatch):
    monkeypatch.setattr(main, "ERRO_SCRAPERS", ModuleNotFoundError("No module named 'scrapers'", name="scrapers"))
    with pytest.raises(SystemExit) as saida:
        app.rodar("--sem-ia")
    assert saida.value.code == 1
    assert "Falta a pasta scrapers" in app.texto and "reenvie o" in app.texto


def test_erro_dentro_dos_scrapers_mostra_o_pacote_que_falta(app, monkeypatch):
    monkeypatch.setattr(main, "ERRO_SCRAPERS", ModuleNotFoundError("No module named 'lxml'", name="lxml"))
    with pytest.raises(SystemExit) as saida:
        app.rodar("--sem-ia")
    assert saida.value.code == 1
    assert "lxml" in app.texto and "pip install -r requirements.txt" in app.texto


def test_curriculo_escaneado_para_com_mensagem_clara(app):
    with pytest.raises(SystemExit) as saida:
        app.rodar("--sem-ia", pdf=PDF_ESCANEADO)
    assert saida.value.code == 1 and "imagem escaneada" in app.texto


def test_ctrl_c_sai_com_codigo_130(app, monkeypatch):
    def interrompe(*args, **kwargs):
        raise KeyboardInterrupt
    monkeypatch.setattr(main, "buscar_todas_vagas", interrompe)
    with pytest.raises(SystemExit) as saida:
        app.rodar("--sem-ia")
    assert saida.value.code == 130 and "Interrompido" in app.texto


# ------------------------------------------------------------------ utilitários

def test_salvar_env_preserva_comentarios_e_outras_variaveis(app):
    env = app.tmp / ".env"
    env.write_text("# minhas chaves\nGEMINI_API_KEY=antiga\nOUTRA=1\n\n# fim\n", encoding="utf-8")
    main._salvar_env({"GEMINI_API_KEY": "nova", "ANTHROPIC_API_KEY": "sk-teste"})
    linhas = env.read_text(encoding="utf-8").splitlines()
    assert linhas[0] == "# minhas chaves" and "GEMINI_API_KEY=nova" in linhas and "OUTRA=1" in linhas
    assert linhas[-1] == "ANTHROPIC_API_KEY=sk-teste" and "# fim" in linhas
    assert "antiga" not in env.read_text(encoding="utf-8")


def test_salvar_env_cria_o_arquivo_quando_nao_existe(app):
    main._salvar_env({"GEMINI_API_KEY": "abc"})
    assert (app.tmp / ".env").read_text(encoding="utf-8") == "GEMINI_API_KEY=abc\n"


def test_resolver_caminho_usa_o_unico_pdf_da_pasta_no_modo_automatico(app, monkeypatch, tmp_path):
    pasta = tmp_path / "cv"
    pasta.mkdir()
    (pasta / "meu_curriculo.pdf").write_bytes(Path(PDF).read_bytes())
    monkeypatch.chdir(pasta)
    assert main.resolver_caminho_pdf(None, automatico=True) == "meu_curriculo.pdf"
    assert main.resolver_caminho_pdf('"meu_curriculo.pdf"') == "meu_curriculo.pdf"  # aspas do Explorador são ignoradas


def test_parser_tem_todas_as_opcoes_antigas_e_as_novas():
    args = main.criar_parser().parse_args([])
    assert args.top == 15 and args.top_mensagens == 5 and args.nota_minima is None
    assert not (args.sem_ia or args.com_mensagens or args.sim or args.sem_cache or args.sem_analise_profunda)


# ---------------------------------------------------------------------------
# Vagas de comparecimento com a data já vencida (caso real: "Comparecer no dia 24/08" em novembro)
# ---------------------------------------------------------------------------

def _vagas_de_comparecimento(app):
    from datetime import date, timedelta
    hoje = date.today()
    passada, futura = hoje - timedelta(days=40), hoje + timedelta(days=5)
    return [
        app.v(titulo=f"Auxiliar de CPD – Princesa Supermercados – Penha Circular RJ – Comparecer no dia {passada:%d/%m}",
              link="https://portal.exemplo/1"),
        app.v(titulo=f"Operador de CPD – Real Supermercados – São Francisco, Niterói RJ – Comparecer em {passada:%d/%m}",
              link="https://portal.exemplo/2"),
        app.v(titulo=f"Auxiliar de CPD – Loja Nova – Centro, Rio de Janeiro RJ – Comparecer em {futura:%d/%m}",
              link="https://portal.exemplo/3"),
    ]


def test_vagas_de_comparecimento_com_data_passada_sao_descartadas(app):
    app.fontes["wordpress"] = _vagas_de_comparecimento(app)
    app.rodar("--sem-ia", cargo="CPD")
    titulos = app.titulos()
    assert any("Loja Nova" in t for t in titulos)
    assert not any("Princesa" in t or "Real Supermercados" in t for t in titulos)
    assert "2 vaga(s) já encerrada(s)" in app.texto
    assert "Princesa Supermercados" in app.texto          # aparece como exemplo do que foi descartado


def test_filtro_de_vagas_encerradas_pode_ser_desligado(app, monkeypatch):
    monkeypatch.setattr(config, "FILTRAR_VAGAS_ENCERRADAS", False)
    app.fontes["wordpress"] = _vagas_de_comparecimento(app)
    app.rodar("--sem-ia", cargo="CPD")
    assert len(app.titulos()) == 3
    assert "já encerrada(s)" not in app.texto


def test_se_todas_as_vagas_estao_encerradas_o_programa_avisa_e_para(app):
    app.fontes["wordpress"] = _vagas_de_comparecimento(app)[:2]
    with pytest.raises(SystemExit) as saida:
        app.rodar("--sem-ia", cargo="CPD")
    assert saida.value.code == 0
    assert "Todas as vagas encontradas já estavam encerradas" in app.texto
    assert not list((app.tmp / "saida").glob("*.xlsx"))


def test_main_lembra_o_modelo_da_ia_na_pasta_do_projeto(app):
    app.fontes["linkedin"] = [app.v(titulo="Auxiliar Administrativo – Empresa A – Rio de Janeiro RJ", link="https://x.exemplo/1")]
    app.rodar("--sem-ia")
    assert ia.arquivo_preferencia == app.tmp / ".achavagai_modelo.json"


# ---------------------------------------------------------------------------
# Relato com imagens: "Motorista de Ônibus Urbano – Queimados – RJ" (exige CNH D) apareceu com nota 75
# para um currículo com CNH B, com o motivo de OUTRA vaga, e a página era de abril.
# ---------------------------------------------------------------------------

def test_onibus_urbano_nao_aparece_para_cnh_b_e_nem_gasta_a_ia(app, ia_falsa):
    app.fontes["wordpress"] = [
        app.v(titulo="Motorista de Ônibus Urbano - Queimados - RJ", link="https://portal.exemplo/onibus", fonte="VagasRio"),
        app.v(titulo="Motorista Sênior (ônibus urbano) – Rio de Janeiro – RJ", link="https://portal.exemplo/onibus2", fonte="VagasRio"),
        app.v(titulo="Motorista - Hab B", empresa="Empresa M", cidade="Rio de Janeiro, RJ", link="https://portal.exemplo/b"),
        app.v(titulo="Auxiliar Administrativo Alta – Empresa X – Rio de Janeiro RJ", link="https://portal.exemplo/adm"),
    ]
    app.rodar("--sem-analise-profunda", cargo="motorista, auxiliar administrativo")
    titulos = app.titulos()
    assert any("Hab B" in t for t in titulos) and any("Administrativo Alta" in t for t in titulos)
    assert not any("nibus" in t for t in titulos)
    assert all("nibus" not in prompt for prompt in ia_falsa["ranking"])       # nem chegaram à IA
    assert "2 vaga(s) descartada(s) por exigirem uma CNH" in app.texto


def test_vaga_sem_data_com_data_antiga_na_pagina_e_descartada_antes_da_ia(app, ia_falsa, monkeypatch):
    from datetime import date
    app.fontes["wordpress"] = [
        app.v(titulo="Auxiliar Administrativo Alta – Empresa Velha – Rio de Janeiro RJ", link="https://portal.exemplo/antiga",
              descricao="curta", data_publicacao="", fonte="VagasRio"),
        app.v(titulo="Auxiliar Administrativo Alta Recente – Empresa Nova – Rio de Janeiro RJ", link="https://portal.exemplo/nova",
              descricao="curta", data_publicacao="", fonte="VagasRio"),
    ]
    paginas = {"https://portal.exemplo/antiga": ("Rotinas administrativas e atendimento. " * 8, "2026-04-09"),
               "https://portal.exemplo/nova": ("Rotinas administrativas e atendimento. " * 8, date.today().isoformat())}
    monkeypatch.setattr(descricoes, "buscar_pagina", lambda url, sessao=None: paginas[url])
    app.rodar()
    titulos = app.titulos()
    assert any("Recente" in t for t in titulos) and not any("Velha" in t for t in titulos)
    assert all("Empresa Velha" not in prompt for prompt in ia_falsa["ranking"])        # não gastou a IA com ela
    assert "descartada(s) depois de ler a página da vaga" in app.texto and "publicada há" in app.texto
    # a data lida da página aparece na planilha
    datas = {linha["Cargo / Título"]: linha["Publicada em"] for linha in app.linhas()}
    assert any(v == date.today().isoformat() for v in datas.values())


def test_prazo_vencido_que_so_aparece_na_descricao_completa_tambem_descarta(app, ia_falsa, monkeypatch):
    app.fontes["wordpress"] = [
        app.v(titulo="Auxiliar Administrativo Alta – Loja A – Rio de Janeiro RJ", link="https://portal.exemplo/a", descricao="curta"),
        app.v(titulo="Assistente Administrativo Alta – Loja B – Rio de Janeiro RJ", link="https://portal.exemplo/b", descricao="curta"),
    ]
    paginas = {"https://portal.exemplo/a": ("Comparecer na loja no dia 05/01/2020 com documentos. " + "Rotina administrativa. " * 10, ""),
               "https://portal.exemplo/b": ("Rotina administrativa e atendimento ao público. " * 8, "")}
    monkeypatch.setattr(descricoes, "buscar_pagina", lambda url, sessao=None: paginas[url])
    app.rodar(cargo="auxiliar administrativo")
    assert app.titulos() == {"Assistente Administrativo Alta – Loja B – Rio de Janeiro RJ"}
    assert "a data de comparecimento ou prazo (05/01/2020) já passou" in app.texto


def test_ia_que_troca_as_notas_de_lugar_e_corrigida_no_fluxo_completo(app, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "chave-falsa")
    notas = {"Auxiliar Administrativo": 80, "Recepcionista": 60, "Vendedor de Loja": 40}

    def ia_trocada(prompt, max_tokens=1500, sistema=None):
        if sistema and "recrutador" in sistema:
            itens = re.findall(r"^(\d+)\. Título: (.*?) \|", prompt, flags=re.MULTILINE)
            return [{"indice": (int(i) + 1) % len(itens), "vaga": t, "nota": notas[t], "motivo": f"motivo de {t}"} for i, t in itens]
        return {"cidade": "Rio de Janeiro", "bairro": "Bangu", "cargo_sugerido": "Auxiliar Administrativo",
                "habilidades": ["Excel"], "senioridade": "júnior", "resumo": "Auxiliar."}

    monkeypatch.setattr(ia, "chamar_ia_json", ia_trocada)
    app.fontes["wordpress"] = [app.v(titulo=t, empresa="Empresa", cidade="Rio de Janeiro, RJ", link=f"https://portal.exemplo/{i}", descricao="Rotina de trabalho.")
                               for i, t in enumerate(notas)]
    app.rodar("--sem-analise-profunda", cargo="auxiliar administrativo, recepcionista, vendedor")
    for linha in app.linhas():
        assert linha["Motivo (IA)"] == f"motivo de {linha['Cargo / Título']}"
        assert linha["Pontuação (%)"] == notas[linha["Cargo / Título"]]
    assert "A IA colocou 3 nota(s) na vaga errada; corrigi conferindo o título." in app.texto
