"""
exportar.py
Gera a planilha Excel (.xlsx) com os resultados: uma aba "Vagas" (com links
clicáveis, nota colorida e marca de vaga nova) e, se houver, uma aba com as
mensagens de candidatura.

Dois problemas comuns que esta versão resolve:
- Textos copiados de sites às vezes trazem caracteres de controle invisíveis, que
  fazem o openpyxl lançar IllegalCharacterError e perder todo o resultado da busca.
  Eles são removidos antes de gravar.
- No Windows, se a planilha anterior ainda estiver aberta no Excel, o arquivo fica
  travado (PermissionError). Em vez de falhar, o script salva com outro nome.
"""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

LIMITE_CELULA = 32000  # o Excel aceita no máximo 32.767 caracteres por célula
LIMITE_LINK = 2000     # links maiores que isso não viram hiperlink no Excel

_VERDE = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
_AMARELO = PatternFill(start_color="FFEB9C", end_color="FFEB9C", fill_type="solid")
_VERMELHO = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")


def limpar_celula(valor) -> str:
    """Texto seguro para uma célula: sem caracteres ilegais e com tamanho limitado."""
    texto = "" if valor is None else str(valor)
    return ILLEGAL_CHARACTERS_RE.sub("", texto)[:LIMITE_CELULA]


def _formatar_cabecalho(ws, n_colunas: int) -> None:
    fonte = Font(bold=True, color="FFFFFF")
    fundo = PatternFill(start_color="2F5597", end_color="2F5597", fill_type="solid")
    for coluna in range(1, n_colunas + 1):
        celula = ws.cell(row=1, column=coluna)
        celula.font = fonte
        celula.fill = fundo
        celula.alignment = Alignment(horizontal="center", vertical="center")


def _colocar_link(celula, link: str) -> None:
    texto = limpar_celula(link)
    celula.value = texto
    if texto.startswith(("http://", "https://")) and len(texto) <= LIMITE_LINK:
        celula.hyperlink = texto
        celula.font = Font(color="0563C1", underline="single")


def montar_planilha(ranking: list, mensagens: list, novas: set[int] | None = None) -> Workbook:
    """Monta a planilha em memória. `novas` é o conjunto de id() das vagas que são
    novidade desde a última execução (veja historico.py)."""
    novas = novas or set()
    wb = Workbook()
    ws = wb.active
    ws.title = "Vagas"

    colunas = ["Pontuação (%)", "Nova", "Cargo / Título", "Empresa", "Cidade", "Publicada em", "Fonte", "Motivo (IA)", "Link"]
    ws.append(colunas)
    _formatar_cabecalho(ws, len(colunas))

    for vaga, pontuacao, motivo in ranking:
        ws.append([
            round(float(pontuacao), 1),
            "sim" if id(vaga) in novas else "",
            limpar_celula(getattr(vaga, "titulo", "")),
            limpar_celula(getattr(vaga, "empresa", "")),
            limpar_celula(getattr(vaga, "cidade", "")),
            limpar_celula(getattr(vaga, "data_publicacao", "")),
            limpar_celula(getattr(vaga, "fonte", "")),
            limpar_celula(motivo),
            "",
        ])
        linha = ws.max_row
        _colocar_link(ws.cell(row=linha, column=9), getattr(vaga, "link", ""))
        nota = ws.cell(row=linha, column=1)
        nota.alignment = Alignment(horizontal="center")
        nota.fill = _VERDE if pontuacao >= 60 else (_AMARELO if pontuacao >= 35 else _VERMELHO)
        ws.cell(row=linha, column=2).alignment = Alignment(horizontal="center")
        ws.cell(row=linha, column=8).alignment = Alignment(wrap_text=True, vertical="top")

    larguras = {1: 14, 2: 8, 3: 50, 4: 26, 5: 20, 6: 16, 7: 14, 8: 45, 9: 55}
    for indice, largura in larguras.items():
        ws.column_dimensions[get_column_letter(indice)].width = largura
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(colunas))}{max(ws.max_row, 1)}"

    if mensagens:
        ws2 = wb.create_sheet("Mensagens de Candidatura")
        colunas2 = ["Cargo / Título", "Link", "Mensagem sugerida"]
        ws2.append(colunas2)
        _formatar_cabecalho(ws2, len(colunas2))
        for vaga, _pontuacao, mensagem in mensagens:
            ws2.append([limpar_celula(getattr(vaga, "titulo", "")), "", limpar_celula(mensagem)])
            linha = ws2.max_row
            _colocar_link(ws2.cell(row=linha, column=2), getattr(vaga, "link", ""))
            ws2.cell(row=linha, column=3).alignment = Alignment(wrap_text=True, vertical="top")
        ws2.column_dimensions["A"].width = 45
        ws2.column_dimensions["B"].width = 50
        ws2.column_dimensions["C"].width = 90
        ws2.freeze_panes = "A2"
    return wb


def salvar_excel(ranking: list, mensagens: list, caminho: str | Path, novas: set[int] | None = None) -> Path:
    """Grava a planilha e devolve o caminho realmente usado (que muda de nome se o
    arquivo estiver aberto no Excel). Cria a pasta de destino se não existir."""
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    wb = montar_planilha(ranking, mensagens, novas)
    try:
        wb.save(caminho)
        return caminho
    except PermissionError:
        for numero in range(2, 100):
            alternativo = caminho.with_name(f"{caminho.stem}_{numero}{caminho.suffix}")
            try:
                wb.save(alternativo)
                return alternativo
            except PermissionError:
                continue
        raise
