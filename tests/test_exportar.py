import pytest
from openpyxl import Workbook, load_workbook

import exportar


def cor(celula) -> str:
    return celula.fill.start_color.rgb[-6:]


def test_cria_planilha_com_colunas_links_cores_e_marca_de_nova(tmp_path, vaga):
    boa = vaga(titulo="Auxiliar", empresa="Loja", cidade="Rio de Janeiro", link="https://x.com/1",
               fonte="Indeed", data_publicacao="hoje")
    fraca = vaga(titulo="Estoquista", link="https://x.com/2")
    media = vaga(titulo="Atendente", link="https://x.com/3")

    destino = tmp_path / "subpasta" / "r.xlsx"
    salvo = exportar.salvar_excel([(boa, 85.0, "motivo bom"), (media, 40.0, ""), (fraca, 12.0, "")], [], destino, novas={id(boa)})
    assert salvo == destino and destino.is_file()  # a pasta que não existia foi criada

    ws = load_workbook(destino)["Vagas"]
    assert [c.value for c in ws[1]][:3] == ["Pontuação (%)", "Nova", "Cargo / Título"]
    assert ws["A2"].value == 85.0 and ws["C2"].value == "Auxiliar" and ws["H2"].value == "motivo bom"
    assert ws["B2"].value == "sim" and not ws["B3"].value
    assert ws["I2"].hyperlink.target == "https://x.com/1"
    assert (cor(ws["A2"]), cor(ws["A3"]), cor(ws["A4"])) == ("C6EFCE", "FFEB9C", "FFC7CE")
    assert ws.freeze_panes == "A2" and ws.auto_filter.ref == "A1:I4"


def test_caracteres_de_controle_nao_derrubam_a_gravacao(tmp_path, vaga):
    suja = vaga(titulo="Vendedor\x0b\x00 Júnior", empresa="Loja\x07", link="https://x.com/1")
    salvo = exportar.salvar_excel([(suja, 50.0, "motivo\x1f ok")], [], tmp_path / "r.xlsx")
    ws = load_workbook(salvo)["Vagas"]
    assert ws["C2"].value == "Vendedor Júnior" and ws["D2"].value == "Loja" and ws["H2"].value == "motivo ok"


def test_texto_gigante_e_cortado_no_limite_do_excel(tmp_path, vaga):
    salvo = exportar.salvar_excel([(vaga(titulo="A", link="https://x.com/1"), 50.0, "x" * 40000)], [], tmp_path / "r.xlsx")
    assert len(load_workbook(salvo)["Vagas"]["H2"].value) == exportar.LIMITE_CELULA


def test_link_que_nao_e_http_vira_texto_sem_hiperlink(tmp_path, vaga):
    salvo = exportar.salvar_excel([(vaga(titulo="A", link="javascript:alert(1)"), 50.0, "")], [], tmp_path / "r.xlsx")
    celula = load_workbook(salvo)["Vagas"]["I2"]
    assert celula.value == "javascript:alert(1)" and celula.hyperlink is None


def test_aba_de_mensagens_so_existe_quando_ha_mensagens(tmp_path, vaga):
    v = vaga(titulo="Auxiliar", link="https://x.com/1")
    sem = load_workbook(exportar.salvar_excel([(v, 80.0, "ok")], [], tmp_path / "a.xlsx"))
    assert sem.sheetnames == ["Vagas"]

    com = load_workbook(exportar.salvar_excel([(v, 80.0, "ok")], [(v, 80.0, "Olá, tenho interesse na vaga.")], tmp_path / "b.xlsx"))
    assert com.sheetnames == ["Vagas", "Mensagens de Candidatura"]
    aba = com["Mensagens de Candidatura"]
    assert aba["A2"].value == "Auxiliar" and aba["C2"].value == "Olá, tenho interesse na vaga."
    assert aba["B2"].hyperlink.target == "https://x.com/1"


def test_planilha_vazia_nao_quebra(tmp_path):
    ws = load_workbook(exportar.salvar_excel([], [], tmp_path / "r.xlsx"))["Vagas"]
    assert ws.max_row == 1


def test_arquivo_aberto_no_excel_salva_com_outro_nome(tmp_path, vaga, monkeypatch):
    tentativas = []
    salvar_original = Workbook.save

    def trava_o_nome_original(self, caminho):
        tentativas.append(str(caminho))
        if str(caminho).endswith("r.xlsx"):
            raise PermissionError("arquivo em uso")
        return salvar_original(self, caminho)

    monkeypatch.setattr(Workbook, "save", trava_o_nome_original)
    salvo = exportar.salvar_excel([(vaga(titulo="A", link="https://x.com/1"), 50.0, "")], [], tmp_path / "r.xlsx")
    assert salvo.name == "r_2.xlsx" and salvo.is_file()
    assert len(tentativas) == 2


def test_se_nenhum_nome_alternativo_funciona_o_erro_original_sobe(tmp_path, vaga, monkeypatch):
    def sempre_trava(self, caminho):
        raise PermissionError("tudo travado")

    monkeypatch.setattr(Workbook, "save", sempre_trava)
    with pytest.raises(PermissionError):
        exportar.salvar_excel([], [], tmp_path / "r.xlsx")
