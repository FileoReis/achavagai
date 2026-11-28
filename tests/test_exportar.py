import json
import base64
import pytest
from openpyxl import Workbook, load_workbook

import exportar


def cor(celula) -> str:
    return celula.fill.start_color.rgb[-6:]


def test_planilha_separa_datas_categorias_e_mantem_links(tmp_path, vaga):
    direta = vaga(titulo="Técnico deInformaticaN1", empresa="Loja", cidade="Rio de Janeiro",
                  link="https://x.com/1", fonte="Teste", data_publicacao="hoje")
    desconhecida = vaga(titulo="Estoquista", link="https://x.com/2", data_publicacao="")
    alternativa = vaga(titulo="Atendente", link="https://x.com/3", data_publicacao="ontem")
    perfil = type("Perfil", (), {
        "areas_atuacao": ["Logística e Distribuição"], "habilidades": ["Controle de estoque"],
        "cargos_compativeis": ["Estoquista"], "cargo_sugerido": "Gerente Operacional",
        "experiencia_conducao_comprovada": False, "objetivo_conducao_declarado": False,
    })()

    destino = tmp_path / "subpasta" / "r.xlsx"
    salvo = exportar.salvar_excel(
        [(direta, 85.0, "motivo bom"), (alternativa, 40.0, "motivo alternativo"), (desconhecida, 12.0, "sem data")],
        [], destino, novas={id(direta)}, termos_busca=["Informática"], perfil=perfil,
    )
    assert salvo == destino and destino.is_file()

    wb = load_workbook(destino)
    assert "Vagas" in wb.sheetnames
    assert "Cargos pesquisados" in wb.sheetnames
    assert "Compatíveis" in wb.sheetnames
    assert "Alternativas" in wb.sheetnames
    assert "Data não confirmada" in wb.sheetnames
    assert "Como abrir links" in wb.sheetnames

    # Aba principal contém apenas vagas cuja data pôde ser interpretada.
    ws = wb["Vagas"]
    assert ws["A2"].value == 85.0 and ws["C2"].value == "Técnico deInformaticaN1"
    assert ws["B2"].value == "sim"
    assert ws["I2"].hyperlink.target == "https://x.com/1"
    assert ws["J2"].value == "Pesquisa direta" and ws["K2"].value == "Sim"
    assert ws.max_row == 3  # duas vagas com data confirmada

    assert wb["Data não confirmada"].max_row == 2
    assert wb["Data não confirmada"]["C2"].value == "Estoquista"
    assert wb["Data não confirmada"]["K2"].value == "Não confirmada"
    assert wb["Alternativas"]["C2"].value == "Atendente"

    # O atalho auxilia no caso em que a associação HTTP/HTTPS do Windows está errada.
    bat = tmp_path / "subpasta" / "abrir_links_chrome_r.bat"
    ps1 = tmp_path / "subpasta" / "abrir_links_chrome_r.ps1"
    assert bat.is_file() and ps1.is_file()
    assert "chrome.exe" in ps1.read_text(encoding="utf-8-sig")


def test_caracteres_de_controle_nao_derrubam_a_gravacao(tmp_path, vaga):
    suja = vaga(titulo="Vendedor\x0b\x00 Júnior", empresa="Loja\x07", link="https://x.com/1", data_publicacao="hoje")
    salvo = exportar.salvar_excel([(suja, 50.0, "motivo\x1f ok")], [], tmp_path / "r.xlsx")
    ws = load_workbook(salvo)["Vagas"]
    assert ws["C2"].value == "Vendedor Júnior" and ws["D2"].value == "Loja" and ws["H2"].value == "motivo ok"


def test_texto_gigante_e_cortado_no_limite_do_excel(tmp_path, vaga):
    salvo = exportar.salvar_excel([(vaga(titulo="A", link="https://x.com/1", data_publicacao="hoje"), 50.0, "x" * 40000)], [], tmp_path / "r.xlsx")
    assert len(load_workbook(salvo)["Vagas"]["H2"].value) == exportar.LIMITE_CELULA


def test_link_que_nao_e_http_vira_texto_sem_hiperlink(tmp_path, vaga):
    salvo = exportar.salvar_excel([(vaga(titulo="A", link="javascript:alert(1)", data_publicacao="hoje"), 50.0, "")], [], tmp_path / "r.xlsx")
    celula = load_workbook(salvo)["Vagas"]["I2"]
    assert celula.value == "javascript:alert(1)" and celula.hyperlink is None


def test_texto_que_parece_formula_e_gravado_como_texto(tmp_path, vaga):
    salvo = exportar.salvar_excel([(vaga(titulo="=HYPERLINK(\"https://evil.test\")", link="https://x.com/1", data_publicacao="hoje"), 50.0, "=1+1")], [], tmp_path / "r.xlsx")
    ws = load_workbook(salvo, data_only=False)["Vagas"]
    assert ws["C2"].value.startswith("'=") and ws["H2"].value == "'=1+1"
    assert ws["C2"].data_type == "s" and ws["H2"].data_type == "s"


def test_aba_de_mensagens_so_existe_quando_ha_mensagens(tmp_path, vaga):
    v = vaga(titulo="Auxiliar", link="https://x.com/1", data_publicacao="hoje")
    sem = load_workbook(exportar.salvar_excel([(v, 80.0, "ok")], [], tmp_path / "a.xlsx"))
    assert "Mensagens de Candidatura" not in sem.sheetnames

    com = load_workbook(exportar.salvar_excel([(v, 80.0, "ok")], [(v, 80.0, "Olá, tenho interesse na vaga.")], tmp_path / "b.xlsx"))
    assert "Mensagens de Candidatura" in com.sheetnames
    aba = com["Mensagens de Candidatura"]
    assert aba["A2"].value == "Auxiliar" and aba["C2"].value == "Olá, tenho interesse na vaga."
    assert aba["B2"].hyperlink.target == "https://x.com/1"


def test_planilha_vazia_nao_quebra(tmp_path):
    wb = load_workbook(exportar.salvar_excel([], [], tmp_path / "r.xlsx"))
    assert wb["Vagas"].max_row == 1
    assert wb["Data não confirmada"].max_row == 1


def test_arquivo_aberto_no_excel_salva_com_outro_nome(tmp_path, vaga, monkeypatch):
    tentativas = []
    salvar_original = Workbook.save

    def trava_o_nome_original(self, caminho):
        tentativas.append(str(caminho))
        if str(caminho).endswith("r.xlsx"):
            raise PermissionError("arquivo em uso")
        return salvar_original(self, caminho)

    monkeypatch.setattr(Workbook, "save", trava_o_nome_original)
    salvo = exportar.salvar_excel([(vaga(titulo="A", link="https://x.com/1", data_publicacao="hoje"), 50.0, "")], [], tmp_path / "r.xlsx")
    assert salvo.name == "r_2.xlsx" and salvo.is_file()
    assert len(tentativas) == 2
    assert (tmp_path / "abrir_links_chrome_r_2.bat").is_file()


def test_se_nenhum_nome_alternativo_funciona_o_erro_original_sobe(tmp_path, monkeypatch):
    def sempre_trava(self, caminho):
        raise PermissionError("tudo travado")

    monkeypatch.setattr(Workbook, "save", sempre_trava)
    with pytest.raises(PermissionError):
        exportar.salvar_excel([], [], tmp_path / "r.xlsx")


def test_exporta_todo_o_universo_e_identifica_notas_locais(tmp_path, vaga):
    from matcher import MOTIVO_SEM_IA

    perfil = type("Perfil", (), {
        "areas_atuacao": ["Logística e Distribuição", "Suporte Técnico e TI"],
        "habilidades": ["Controle de estoque", "Rotinas administrativas"],
        "cargos_compativeis": ["Estoquista", "Gerente Operacional", "Motorista de Carga"],
        "cargo_sugerido": "Gerente Operacional",
        "experiencia_conducao_comprovada": False,
        "objetivo_conducao_declarado": False,
    })()
    ranking = [
        (vaga(titulo="Auxiliar de CPD", link="https://x.test/1", data_publicacao="hoje"), 91, "Experiência em CPD não comprovada."),
        (vaga(titulo="Técnico de TI Jr.", link="https://x.test/2", data_publicacao="ontem"), 84, "Suporte de TI comprovado."),
        (vaga(titulo="Estoquista", link="https://x.test/3", data_publicacao="hoje"), 72, MOTIVO_SEM_IA),
        (vaga(titulo="Auxiliar de Entrega", link="https://x.test/4", data_publicacao=""), 38, MOTIVO_SEM_IA),
        (vaga(titulo="Atendente de Loja", link="https://x.test/5", data_publicacao="hoje"), 21, MOTIVO_SEM_IA),
    ]
    destino = exportar.salvar_excel(
        ranking, [], tmp_path / "universo.xlsx", termos_busca=["CPD", "Informática", "Motorista"],
        perfil=perfil, nota_minima=25,
    )
    wb = load_workbook(destino)

    def dados(nome):
        ws = wb[nome]
        return list(ws.iter_rows(min_row=2, values_only=True))

    assert len([r for r in dados("Todas as vagas") if r[2]]) == 5
    assert len([r for r in dados("Vagas") if r[2]]) == 4
    assert len([r for r in dados("Data não confirmada") if r[2]]) == 1
    assert len([r for r in dados("Cargos pesquisados") if r[2]]) == 2
    assert len([r for r in dados("Compatíveis") if r[2]]) == 1
    assert len([r for r in dados("Alternativas") if r[2]]) == 1

    todas = {r[2]: r for r in dados("Todas as vagas")}
    assert "TF-IDF" in todas["Estoquista"][11]
    assert "não comparável" in todas["Estoquista"][12].lower()
    assert todas["Auxiliar de CPD"][12] == "Atingiu a nota mínima"
    assert "Não comparável" in todas["Atendente de Loja"][12]
    assert wb["Vagas"].auto_filter.ref.startswith("A1:M")


def test_atalho_chrome_usa_um_registro_json_por_linha_e_selecao_escalar(tmp_path, vaga):
    """Cada numero do menu deve apontar para exatamente um titulo e uma URL."""
    import re

    ranking = [
        (vaga(titulo="Auxiliar de CPD", link="https://exemplo.test/cpd?a=1&b=2", data_publicacao="hoje"), 95, "CPD"),
        (vaga(titulo="Motorista B", link="https://exemplo.test/motorista", data_publicacao="hoje"), 90, "CNH B"),
        (vaga(titulo="Técnico de Informática", link="https://exemplo.test/ti", data_publicacao="ontem"), 88, "TI"),
    ]
    destino = exportar.salvar_excel(ranking, [], tmp_path / "atalho.xlsx")
    ps1_path = destino.with_name("abrir_links_chrome_atalho.ps1")
    ps1 = ps1_path.read_text(encoding="utf-8-sig")

    encoded = re.search(r"\$encoded = '([A-Za-z0-9+/=]+)'", ps1).group(1)
    decoded = base64.b64decode(encoded).decode("utf-8")
    registros = [json.loads(linha) for linha in decoded.splitlines() if linha.strip()]

    assert len(registros) == 3
    assert [item["titulo"] for item in registros] == [
        "Auxiliar de CPD", "Motorista B", "Técnico de Informática"
    ]
    assert [item["url"] for item in registros] == [
        "https://exemplo.test/cpd?a=1&b=2",
        "https://exemplo.test/motorista",
        "https://exemplo.test/ti",
    ]
    assert "$links = [System.Collections.Generic.List[object]]::new()" in ps1
    assert "ConvertFrom-Json -InputObject $linha" in ps1
    assert "$selecionada = $links[$numero - 1]" in ps1
    assert "$url = [string]$selecionada.url" in ps1
    assert "Start-Process -FilePath $chrome -ArgumentList $argumentos" in ps1
    assert "$raw | ConvertFrom-Json" not in ps1
    assert "$links[$i].titulo" in ps1


def test_menu_amigavel_inclui_atalho_direto_para_painel_html(tmp_path, vaga):
    """O BAT abre um menu e o PS1 oferece o HTML e vagas individuais."""
    import re

    ranking = [
        (vaga(titulo="Auxiliar de CPD", link="https://exemplo.test/cpd", data_publicacao="hoje"), 95, "CPD"),
        (vaga(titulo="Motorista B", link="https://exemplo.test/motorista", data_publicacao="hoje"), 90, "CNH B"),
    ]
    destino = exportar.salvar_excel(ranking, [], tmp_path / "painel.xlsx")
    bat = destino.with_name("abrir_links_chrome_painel.bat").read_text(encoding="utf-8")
    ps1 = destino.with_name("abrir_links_chrome_painel.ps1").read_text(encoding="utf-8-sig")

    assert "color 0b" in bat.lower()
    assert "title AchaVagAI - Central de Resultados" in bat
    assert "chcp 65001" in bat
    assert "powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass" in bat

    assert "ABRIR UMA VAGA PELO NUMERO" in ps1
    assert "ABRIR A PLANILHA EXCEL (.XLSX)" in ps1
    assert "ABRIR A PLATAFORMA INTERATIVA DE CARREIRA" in ps1
    assert "ABRIR A PASTA DESTA PESQUISA" in ps1
    assert "$painelHtml = Join-Path $PSScriptRoot $htmlName" in ps1
    assert "$planilhaXlsx = Join-Path $PSScriptRoot $xlsxName" in ps1
    assert "Start-Process -FilePath $planilhaXlsx" in ps1
    assert "Start-Process -FilePath $chrome -ArgumentList $argumentos" in ps1
    assert "--new-window" in ps1 and "--new-tab" in ps1
    assert "while (-not $sair)" in ps1
    assert "'0' { $sair = $true }" in ps1

    encoded_html = re.search(r"\$htmlNameEncoded = '([A-Za-z0-9+/=]+)'", ps1).group(1)
    encoded_xlsx = re.search(r"\$xlsxNameEncoded = '([A-Za-z0-9+/=]+)'", ps1).group(1)
    import base64
    assert base64.b64decode(encoded_html).decode("utf-8") == "painel.html"
    assert base64.b64decode(encoded_xlsx).decode("utf-8") == "painel.xlsx"
    assert "[2] Planilha Excel (.xlsx)" in bat
    assert "[3] Plataforma interativa de carreira (dashboard + acompanhamento)" in bat



def test_cria_central_mesmo_sem_links_validos_para_abrir_excel_html_e_pasta(tmp_path):
    destino = exportar.salvar_excel([], [], tmp_path / "sem_links.xlsx")
    bat = tmp_path / "abrir_links_chrome_sem_links.bat"
    ps1 = tmp_path / "abrir_links_chrome_sem_links.ps1"
    assert destino.is_file()
    assert bat.is_file() and ps1.is_file()
    conteudo = ps1.read_text(encoding="utf-8-sig")
    assert "ABRIR A PLANILHA EXCEL (.XLSX)" in conteudo
    assert "ABRIR A PLATAFORMA INTERATIVA DE CARREIRA" in conteudo
    assert "Nenhum link de candidatura valido" in conteudo
