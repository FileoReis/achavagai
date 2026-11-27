from pathlib import Path

from html_report import gerar_html
from matcher import MOTIVO_SEM_IA


def test_painel_html_reune_vagas_categorias_datas_e_fontes(tmp_path, vaga):
    direta = vaga(
        titulo="Técnico de Informática N1", empresa="Empresa A", cidade="Rio de Janeiro",
        data_publicacao="hoje", link="https://example.com/ti", descricao="Suporte técnico e manutenção.",
        fonte="Portal A", termo_busca="Informática",
    )
    compat = vaga(
        titulo="Estoquista", empresa="Empresa B", cidade="Niterói",
        data_publicacao="ontem", link="https://example.com/estoque", descricao="Controle de estoque.",
        fonte="Portal B",
    )
    sem_data = vaga(
        titulo="Auxiliar de Entrega", empresa="Empresa C", cidade="Duque de Caxias",
        data_publicacao="", link="https://example.com/entrega", descricao="Distribuição de produtos.",
        fonte="Portal A",
    )
    perfil = type("Perfil", (), {
        "areas_atuacao": ["Logística e Distribuição", "Suporte Técnico e TI"],
        "habilidades": ["Controle de estoque", "Redes"],
        "cargos_compativeis": ["Estoquista"],
        "cargo_sugerido": "Gerente Operacional",
        "experiencia_conducao_comprovada": False,
        "objetivo_conducao_declarado": False,
    })()

    destino = gerar_html(
        [(direta, 91, "Suporte técnico comprovado."), (compat, 72, MOTIVO_SEM_IA), (sem_data, 38, MOTIVO_SEM_IA)],
        tmp_path / "vagas.html",
        novas={id(direta)},
        termos_busca=["Informática", "Motorista"],
        perfil=perfil,
        metadata={"cidade": "Rio de Janeiro", "uf": "RJ", "dias_maximo": 5},
    )

    texto = destino.read_text(encoding="utf-8")
    assert destino.is_file()
    assert "AchaVagAI" in texto
    assert "Técnico de Informática N1" in texto
    assert "Estoquista" in texto
    # O painel espelha a aba principal "Vagas" do Excel: anúncios sem data
    # ficam somente na aba específica do workbook e não aparecem aqui.
    assert "Auxiliar de Entrega" not in texto
    assert "Data não confirmada</button>" not in texto
    assert "Similaridade local · sem IA" in texto
    assert "Avaliação IA / cache" in texto
    assert "Pesquisa direta" in texto
    assert "Compatível com currículo" in texto
    assert "Alternativa" in texto
    assert "Portal A" in texto and "Portal B" in texto
    assert "Todas as fontes" in texto
    assert "Rio de Janeiro" in texto and "5 dias" in texto
    assert "navigator.clipboard" in texto
    assert "cdnjs" not in texto and "unpkg" not in texto and "https://fonts.googleapis.com" not in texto


def test_painel_escapa_html_e_nao_cria_link_javascript(tmp_path, vaga):
    maliciosa = vaga(
        titulo='<img src=x onerror="alert(1)">', empresa="Empresa & Filhos",
        cidade="Rio de Janeiro", data_publicacao="hoje", link="javascript:alert(1)",
        descricao="<script>alert('x')</script>", fonte="Portal <A>",
    )
    destino = gerar_html([(maliciosa, 50, "<b>texto</b>")], tmp_path / "seguro.html")
    texto = destino.read_text(encoding="utf-8")
    assert '&lt;img src=x onerror=&quot;alert(1)&quot;&gt;' in texto
    assert '<script>alert(' not in texto
    assert 'href="javascript:' not in texto
    assert 'data-link="javascript:' not in texto
    assert '&lt;script&gt;alert' in texto


def test_painel_vazio_mostra_estado_vazio(tmp_path):
    destino = gerar_html([], tmp_path / "vazio.html", metadata={"cidade": "Rio de Janeiro"})
    texto = destino.read_text(encoding="utf-8")
    assert "Nenhuma oportunidade nesta lista" in texto
    assert "Vagas na seleção" in texto
    assert "Mesmo conjunto da aba “Vagas”" in texto


def test_html_nao_inclui_dados_pessoais_do_curriculo(tmp_path, vaga):
    v = vaga(titulo="Analista", link="https://example.com/vaga", data_publicacao="hoje")
    perfil = type("Perfil", (), {
        "nome": "NOME PRIVADO TESTE", "texto_para_ia": "CPF 11122233344",
        "areas_atuacao": ["TI"], "habilidades": ["Redes"],
        "cargos_compativeis": [], "cargo_sugerido": "Analista",
    })()
    texto = gerar_html([(v, 80, "Compatibilidade." )], tmp_path / "privado.html", perfil=perfil).read_text()
    assert "NOME PRIVADO TESTE" not in texto
    assert "11122233344" not in texto


def test_helper_do_main_salva_html_ao_lado_da_planilha(tmp_path, vaga):
    import main

    v = vaga(titulo="Auxiliar de CPD", link="https://example.com/cpd", data_publicacao="hoje", fonte="RioVagas")
    caminho_xlsx = tmp_path / "vagas_encontradas_teste.xlsx"
    perfil = type("Perfil", (), {
        "areas_atuacao": ["Suporte Técnico e TI"],
        "habilidades": ["Informática"],
        "cargos_compativeis": [],
        "cargo_sugerido": "Técnico de Informática",
    })()
    salvo = main._gerar_painel_html(
        [(v, 88, "Conhecimento relacionado ao cargo.")], caminho_xlsx, {id(v)},
        ["CPD"], perfil, {"cidade": "Rio de Janeiro", "bairro": "Centro"}, 5,
    )
    assert salvo == tmp_path / "vagas_encontradas_teste.html"
    assert salvo.is_file()
    assert "Auxiliar de CPD" in salvo.read_text(encoding="utf-8")


def test_busca_sem_resultados_gera_painel_vazio(tmp_path, capsys):
    import main
    args = type("Args", (), {"saida": str(tmp_path)})()
    filtros = {"cidade": "Rio de Janeiro", "bairro": "Centro", "palavra_chave": "CPD"}
    perfil = type("Perfil", (), {})()
    main._gerar_painel_vazio(args, filtros, perfil, ["CPD"])
    arquivos = list(tmp_path.glob("vagas_encontradas_*.html"))
    assert len(arquivos) == 1
    texto = arquivos[0].read_text(encoding="utf-8")
    assert "Nenhuma oportunidade nesta lista" in texto
    assert "CPD" in texto


def test_painel_mostra_exatamente_as_vagas_da_aba_principal_do_excel(tmp_path, vaga):
    from openpyxl import load_workbook
    from exportar import salvar_excel

    itens = [
        (vaga(titulo="Auxiliar de CPD", data_publicacao="hoje", link="https://x.test/cpd"), 91, "CPD"),
        (vaga(titulo="Técnico de TI", data_publicacao="ontem", link="https://x.test/ti"), 84, "TI"),
        (vaga(titulo="Estoquista sem data", data_publicacao="", link="https://x.test/estoque"), 76, "Estoque"),
    ]
    arquivo_excel = salvar_excel(itens, [], tmp_path / "espelho.xlsx", termos_busca=["CPD", "Informática"])
    wb = load_workbook(arquivo_excel, read_only=True, data_only=True)
    titulos_excel = [linha[2] for linha in wb["Vagas"].iter_rows(min_row=2, values_only=True) if linha[2]]
    destino = gerar_html(itens, tmp_path / "espelho.html", termos_busca=["CPD", "Informática"])
    texto = destino.read_text(encoding="utf-8")

    assert titulos_excel == ["Auxiliar de CPD", "Técnico de TI"]
    assert all(titulo in texto for titulo in titulos_excel)
    assert "Estoquista sem data" not in texto
    assert 'Vagas na seleção</span><strong class="metric-number">02</strong>' in texto
    assert "aba principal do Excel" in texto


def test_painel_visual_tem_identidade_premium_e_layout_movel(tmp_path, vaga):
    v = vaga(titulo="Analista de Suporte", empresa="Empresa Exemplo", data_publicacao="hoje", link="https://x.test/1")
    texto = gerar_html([(v, 88, "Experiência técnica relevante.")], tmp_path / "premium.html").read_text(encoding="utf-8")
    assert "Seu radar profissional" in texto
    assert "Georgia" in texto
    assert "--paper:#f3f1ec" in texto
    assert "@media(max-width:720px)" in texto
    assert "opportunity-card" in texto
    assert "https://fonts.googleapis.com" not in texto
