"""Exporta oportunidades para Excel e cria uma Central de Resultados (.BAT/.PS1).

Os hyperlinks do XLSX são relações externas HTTPS normais. Se o Windows estiver
com o protocolo HTTP/HTTPS associado incorretamente, o .BAT/.PS1 auxiliar abre o
endereço diretamente no executável do Chrome, sem depender dessa associação.
"""
from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from classificacao import classificar_vaga
from filtros import idade_em_dias
from matcher import MOTIVO_SEM_IA

LIMITE_CELULA = 32000
LIMITE_LINK = 2000


def selecionar_vagas_aba_principal(ranking: list[tuple]) -> list[tuple]:
    """Retorna exatamente as linhas da aba principal ``Vagas`` do Excel.

    A aba principal contém somente oportunidades cuja data de publicação pôde
    ser interpretada. Anúncios sem data ficam exclusivamente na aba própria.
    Este helper é compartilhado pelo Excel e pelo painel HTML para impedir que
    os dois relatórios apresentem universos diferentes.
    """
    return [
        item for item in ranking
        if idade_em_dias(getattr(item[0], "data_publicacao", "")) is not None
    ]

_VERDE = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
_AMARELO = PatternFill(start_color="FFEB9C", end_color="FFEB9C", fill_type="solid")
_VERMELHO = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")
_AZUL_CLARO = PatternFill(start_color="DDEBF7", end_color="DDEBF7", fill_type="solid")

_COLUNAS = [
    "Pontuação (%)", "Nova", "Cargo / Título", "Empresa", "Cidade",
    "Publicada em", "Fonte", "Motivo (IA)", "Link", "Classificação",
    "Data confirmada?", "Base da pontuação", "Situação da nota",
]


def limpar_celula(valor) -> str:
    texto = "" if valor is None else str(valor)
    return ILLEGAL_CHARACTERS_RE.sub("", texto)[:LIMITE_CELULA]


def _texto_seguro_excel(valor) -> str:
    """Neutraliza texto externo que poderia ser interpretado como fórmula."""
    texto = limpar_celula(valor)
    if texto.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + texto
    return texto


def _url_http_valida(valor: str) -> str | None:
    texto = limpar_celula(valor).strip()
    if not texto or len(texto) > LIMITE_LINK or any(ord(ch) < 32 for ch in texto):
        return None
    try:
        partes = urlsplit(texto)
    except ValueError:
        return None
    if partes.scheme.lower() not in {"http", "https"} or not partes.netloc:
        return None
    if partes.username or partes.password:
        return None
    return texto


def _formatar_cabecalho(ws, n_colunas: int) -> None:
    fonte = Font(bold=True, color="FFFFFF")
    fundo = PatternFill(start_color="2F5597", end_color="2F5597", fill_type="solid")
    for coluna in range(1, n_colunas + 1):
        celula = ws.cell(row=1, column=coluna)
        celula.font = fonte
        celula.fill = fundo
        celula.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[1].height = 30


def _colocar_link(celula, link: str) -> None:
    url = _url_http_valida(link)
    if url:
        celula.value = url
        celula.hyperlink = url  # relação externa HTTPS, não fórmula HYPERLINK()
        celula.font = Font(color="0563C1", underline="single")
        celula.alignment = Alignment(wrap_text=True, vertical="top")
    else:
        celula.value = _texto_seguro_excel(link)


def _linha_vaga(
    item: tuple, novas: set[int], termos_busca, perfil, nota_minima: float | None = None
) -> tuple[list, str, bool, str | None]:
    vaga, pontuacao, motivo = item
    categoria = classificar_vaga(vaga, termos_busca, perfil)
    idade = idade_em_dias(getattr(vaga, "data_publicacao", ""))
    data_confirmada = idade is not None
    avaliacao_local = motivo == MOTIVO_SEM_IA
    if avaliacao_local:
        # Mantém a coluna "Motivo (IA)" vazia; a coluna "Base da pontuação"
        # informa explicitamente que essa linha recebeu apenas similaridade local.
        motivo_exibido = ""
        base_pontuacao = "Similaridade textual local (TF-IDF)"
        situacao_nota = "Não comparável à nota mínima da IA"
    else:
        motivo_exibido = motivo
        base_pontuacao = "IA ou cache de avaliação anterior"
        if nota_minima is None:
            situacao_nota = "Sem corte por nota mínima"
        elif float(pontuacao) >= float(nota_minima):
            situacao_nota = "Atingiu a nota mínima"
        else:
            situacao_nota = "Abaixo da nota mínima"
    valores = [
        round(float(pontuacao), 1),
        "sim" if id(vaga) in novas else "",
        _texto_seguro_excel(getattr(vaga, "titulo", "")),
        _texto_seguro_excel(getattr(vaga, "empresa", "")),
        _texto_seguro_excel(getattr(vaga, "cidade", "")),
        _texto_seguro_excel(getattr(vaga, "data_publicacao", "")),
        _texto_seguro_excel(getattr(vaga, "fonte", "")),
        _texto_seguro_excel(motivo_exibido),
        "",  # o hyperlink é aplicado abaixo
        categoria,
        "Sim" if data_confirmada else "Não confirmada",
        base_pontuacao,
        situacao_nota,
    ]
    return valores, categoria, data_confirmada, getattr(vaga, "link", "")


def _preencher_aba(
    wb: Workbook, nome: str, itens: list[tuple], novas: set[int], termos_busca, perfil,
    incluir_categoria: bool = True, nota_minima: float | None = None,
) -> None:
    ws = wb.create_sheet(nome)
    colunas = list(_COLUNAS if incluir_categoria else _COLUNAS[:9])
    ws.append(colunas)
    _formatar_cabecalho(ws, len(colunas))
    for item in itens:
        valores, categoria, data_confirmada, link = _linha_vaga(
            item, novas, termos_busca, perfil, nota_minima
        )
        ws.append(valores if incluir_categoria else valores[:9])
        linha = ws.max_row
        _colocar_link(ws.cell(row=linha, column=9), link)
        nota = ws.cell(row=linha, column=1)
        nota.alignment = Alignment(horizontal="center", vertical="center")
        nota.fill = _VERDE if item[1] >= 80 else (_AMARELO if item[1] >= 50 else _VERMELHO)
        ws.cell(row=linha, column=2).alignment = Alignment(horizontal="center")
        ws.cell(row=linha, column=8).alignment = Alignment(wrap_text=True, vertical="top")
        if incluir_categoria:
            ws.cell(row=linha, column=10).fill = _AZUL_CLARO
            ws.cell(row=linha, column=11).alignment = Alignment(horizontal="center")
        ws.row_dimensions[linha].height = 42

    larguras = {
        1: 14, 2: 8, 3: 50, 4: 26, 5: 22, 6: 21, 7: 18, 8: 60, 9: 62,
        10: 25, 11: 18, 12: 34, 13: 30,
    }
    for indice, largura in larguras.items():
        if indice <= len(colunas):
            ws.column_dimensions[get_column_letter(indice)].width = largura
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(colunas))}{max(ws.max_row, 1)}"


def _aba_ajuda(wb: Workbook) -> None:
    ws = wb.create_sheet("Como abrir links")
    linhas = [
        ["Como abrir os links das vagas"],
        ["Os links da coluna Link são hyperlinks externos HTTPS gravados no XLSX. A planilha não define qual navegador o Windows usa."],
        ["Se clicar no link abrir a pasta Documentos/Explorador, a associação HTTP/HTTPS do Windows está incorreta."],
        ["Correção permanente: Configurações do Windows > Aplicativos > Aplicativos padrão > Google Chrome; associe HTTP e HTTPS ao Chrome."],
        ["Use abrir_links_chrome_<nome-da-planilha>.bat para abrir a Central de Resultados criada ao lado desta planilha."],
        ["Na Central: 1 abre uma vaga pelo número; 2 abre esta planilha; 3 abre o painel HTML no Chrome; 4 abre a pasta; 0 sai."],
        ["O menu abre apenas a vaga escolhida. A planilha usa o aplicativo padrão do Windows e o painel é aberto no Chrome."],
        ["Os links também permanecem visíveis na coluna Link para copiar e colar diretamente no navegador."],
        ["Nas abas, 'Base da pontuação' identifica notas da IA/cache ou similaridade TF-IDF local. Notas TF-IDF não são comparáveis às notas da IA."],
        ["'Todas as vagas' reúne o universo que passou pelos filtros obrigatórios. Vagas não avaliadas pela IA aparecem com pontuação local e essa condição fica explícita."],
        ["'Situação da nota' informa se uma nota da IA atingiu o corte mínimo. A similaridade TF-IDF não é aprovada/reprovada por esse corte."],
        ["Atenção: confira o domínio de destino antes de se candidatar e nunca informe senhas ou dados bancários em páginas desconhecidas."],
    ]
    for row in linhas:
        ws.append(row)
    ws.merge_cells("A1:F1")
    ws["A1"].font = Font(bold=True, size=15, color="FFFFFF")
    ws["A1"].fill = PatternFill(start_color="2F5597", end_color="2F5597", fill_type="solid")
    ws["A1"].alignment = Alignment(vertical="center")
    ws.row_dimensions[1].height = 28
    for row in range(2, len(linhas) + 1):
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=6)
        ws.cell(row, 1).alignment = Alignment(wrap_text=True, vertical="top")
        ws.row_dimensions[row].height = 42
    ws.column_dimensions["A"].width = 34
    for col in "BCDEF":
        ws.column_dimensions[col].width = 18
    ws.freeze_panes = "A2"


def _gerar_atalho_chrome(caminho_xlsx: Path, ranking: list[tuple]) -> tuple[Path, Path]:
    """Cria a Central para abrir vaga individual, XLSX, HTML ou pasta da pesquisa."""
    links = []
    vistos = set()
    for vaga, _nota, _motivo in ranking:
        url = _url_http_valida(getattr(vaga, "link", ""))
        if url and url not in vistos:
            links.append({"titulo": limpar_celula(getattr(vaga, "titulo", "Vaga"))[:120], "url": url})
            vistos.add(url)
    # Mesmo sem links externos, o menu continua útil para abrir a planilha,
    # o painel HTML ou a pasta da pesquisa. A opção de vaga individual será
    # apresentada como indisponível quando a lista estiver vazia.
    nome_base = f"abrir_links_chrome_{caminho_xlsx.stem}"
    caminho_bat = caminho_xlsx.with_name(nome_base + ".bat")
    caminho_ps1 = caminho_xlsx.with_name(nome_base + ".ps1")
    caminho_html = caminho_xlsx.with_suffix(".html")

    # JSON Lines evita ambiguidades do ConvertFrom-Json com arrays na raiz em
    # diferentes versões do PowerShell. Cada item continua sendo um registro escalar.
    payload_texto = "\n".join(
        json.dumps(item, ensure_ascii=False, separators=(",", ":"))
        for item in links
    )
    payload = base64.b64encode(payload_texto.encode("utf-8")).decode("ascii")
    html_nome_b64 = base64.b64encode(caminho_html.name.encode("utf-8")).decode("ascii")
    xlsx_nome_b64 = base64.b64encode(caminho_xlsx.name.encode("utf-8")).decode("ascii")

    ps1 = r"""$ErrorActionPreference = 'Stop'
$encoded = '__PAYLOAD__'
$htmlNameEncoded = '__HTML_NAME__'
$xlsxNameEncoded = '__XLSX_NAME__'
$raw = [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String($encoded))
$htmlName = [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String($htmlNameEncoded))
$xlsxName = [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String($xlsxNameEncoded))
$painelHtml = Join-Path $PSScriptRoot $htmlName
$planilhaXlsx = Join-Path $PSScriptRoot $xlsxName

# Cada linha contém exatamente um objeto JSON: uma escolha abre uma única vaga.
$links = [System.Collections.Generic.List[object]]::new()
foreach ($linha in ($raw -split "`r?`n")) {
    if ([System.String]::IsNullOrWhiteSpace($linha)) { continue }
    $item = ConvertFrom-Json -InputObject $linha -ErrorAction Stop
    if ($null -eq $item -or $item.titulo -is [array] -or $item.url -is [array]) {
        Write-Host 'Um registro de link possui formato invalido e foi ignorado.' -ForegroundColor Yellow
        continue
    }
    $titulo = [string]$item.titulo
    $url = [string]$item.url
    if ([System.String]::IsNullOrWhiteSpace($titulo) -or $url -notmatch '^https?://') {
        Write-Host 'Um registro sem titulo ou com URL invalida foi ignorado.' -ForegroundColor Yellow
        continue
    }
    [void]$links.Add([pscustomobject]@{ titulo = $titulo; url = $url })
}

function Get-ChromePath {
    $comando = Get-Command 'chrome.exe' -ErrorAction SilentlyContinue
    if ($comando -and $comando.Source -and (Test-Path -LiteralPath $comando.Source)) {
        return $comando.Source
    }
    $raizes = @($env:ProgramFiles, ${env:ProgramFiles(x86)}, $env:LOCALAPPDATA) |
        Where-Object { -not [System.String]::IsNullOrWhiteSpace($_) }
    foreach ($raiz in $raizes) {
        $candidato = Join-Path $raiz 'Google\Chrome\Application\chrome.exe'
        if (Test-Path -LiteralPath $candidato) { return $candidato }
    }
    Write-Host ''
    Write-Host 'O Google Chrome nao foi encontrado automaticamente.' -ForegroundColor Yellow
    $manual = Read-Host 'Informe o caminho completo do chrome.exe (ou Enter para cancelar)'
    if ($manual -and (Test-Path -LiteralPath $manual)) { return $manual }
    return $null
}

function Abrir-NoChrome([string]$url, [string]$tipo) {
    if ($url -notmatch '^(https?://|file://)') {
        Write-Host 'Destino invalido; nada foi aberto.' -ForegroundColor Red
        return $false
    }
    $chrome = Get-ChromePath
    if (-not $chrome) {
        Write-Host 'Nao foi possivel localizar o Chrome. Verifique o caminho informado.' -ForegroundColor Red
        return $false
    }
    if ($tipo -eq 'painel') {
        $argumentos = '--new-window "{0}"' -f $url
    } else {
        $argumentos = '--new-tab "{0}"' -f $url
    }
    Start-Process -FilePath $chrome -ArgumentList $argumentos
    return $true
}

function Mostrar-Cabecalho {
    Clear-Host
    Write-Host ''
    Write-Host '  A C H A V A G A I' -ForegroundColor Cyan
    Write-Host '  CENTRAL DE RESULTADOS' -ForegroundColor White
    Write-Host '  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━' -ForegroundColor DarkCyan
    Write-Host ('  {0} vagas disponíveis para abertura individual' -f $links.Count) -ForegroundColor Gray
    if (Test-Path -LiteralPath $planilhaXlsx) {
        Write-Host '  Planilha Excel: disponível nesta pasta' -ForegroundColor Green
    } else {
        Write-Host '  Planilha Excel: não encontrada nesta pasta' -ForegroundColor Yellow
    }
    if (Test-Path -LiteralPath $painelHtml) {
        Write-Host '  Painel HTML: disponível nesta pasta' -ForegroundColor Green
    } else {
        Write-Host '  Painel HTML: não encontrado nesta pasta' -ForegroundColor Yellow
    }
    Write-Host ''
}

$sair = $false
while (-not $sair) {
    Mostrar-Cabecalho
    Write-Host '  ESCOLHA COMO DESEJA ACESSAR OS RESULTADOS' -ForegroundColor Yellow
    Write-Host ''
    Write-Host '  [1] ' -NoNewline -ForegroundColor Green
    Write-Host 'ABRIR UMA VAGA PELO NUMERO' -ForegroundColor White
    Write-Host '      Lista numerada; abre somente a oportunidade escolhida no Chrome.' -ForegroundColor DarkGray
    Write-Host ''
    Write-Host '  [2] ' -NoNewline -ForegroundColor Cyan
    Write-Host 'ABRIR A PLANILHA EXCEL (.XLSX)' -ForegroundColor White
    Write-Host '      Abre todas as abas, filtros e links no Excel ou app padrão.' -ForegroundColor DarkGray
    Write-Host ''
    Write-Host '  [3] ' -NoNewline -ForegroundColor Magenta
    Write-Host 'ABRIR O PAINEL VISUAL NO NAVEGADOR (.HTML)' -ForegroundColor White
    Write-Host '      Painel premium com pesquisa, filtros e cartões de vagas.' -ForegroundColor DarkGray
    Write-Host ''
    Write-Host '  [4] ' -NoNewline -ForegroundColor DarkYellow
    Write-Host 'ABRIR A PASTA DESTA PESQUISA' -ForegroundColor White
    Write-Host ''
    Write-Host '  [0] ' -NoNewline -ForegroundColor Red
    Write-Host 'SAIR' -ForegroundColor White
    Write-Host ''
    $opcao = Read-Host '  Digite 1, 2, 3, 4 ou 0'

    switch ($opcao) {
        '1' {
            if ($links.Count -eq 0) {
                Write-Host 'Nenhum link de candidatura valido foi encontrado nesta pesquisa.' -ForegroundColor Yellow
                Read-Host 'Pressione Enter para voltar'
                continue
            }
            Clear-Host
            Write-Host ''
            Write-Host '  A C H A V A G A I  |  ESCOLHA UMA VAGA' -ForegroundColor Cyan
            Write-Host '  ─────────────────────────────────────────────────────────' -ForegroundColor DarkCyan
            for ($i = 0; $i -lt $links.Count; $i++) {
                Write-Host ('  {0,3}. ' -f ($i + 1)) -NoNewline -ForegroundColor Green
                Write-Host ([string]$links[$i].titulo) -ForegroundColor White
            }
            Write-Host ''
            Write-Host '  [0] Voltar ao menu principal' -ForegroundColor DarkGray
            $entrada = Read-Host '  Digite o numero da vaga'
            if ($entrada -eq '0') { continue }
            $numero = 0
            if ([int]::TryParse($entrada, [ref]$numero) -and $numero -ge 1 -and $numero -le $links.Count) {
                $selecionada = $links[$numero - 1]
                $url = [string]$selecionada.url
                if (Abrir-NoChrome $url 'vaga') {
                    Write-Host ''
                    Write-Host ('Vaga aberta no Chrome: {0}' -f $selecionada.titulo) -ForegroundColor Green
                    Start-Sleep -Milliseconds 1000
                } else {
                    Read-Host 'Pressione Enter para voltar'
                }
            } else {
                Write-Host 'Numero invalido. Nenhuma vaga foi aberta.' -ForegroundColor Yellow
                Start-Sleep -Milliseconds 1000
            }
        }
        '2' {
            if (-not (Test-Path -LiteralPath $planilhaXlsx)) {
                Write-Host 'Planilha Excel nao encontrada nesta pasta.' -ForegroundColor Yellow
                Read-Host 'Pressione Enter para voltar'
                continue
            }
            try {
                Start-Process -FilePath $planilhaXlsx
                Write-Host 'Planilha solicitada ao aplicativo padrao (normalmente Excel).' -ForegroundColor Green
                Start-Sleep -Milliseconds 1000
            } catch {
                Write-Host ('Nao foi possivel abrir a planilha: {0}' -f $_.Exception.Message) -ForegroundColor Red
                Read-Host 'Pressione Enter para voltar'
            }
        }
        '3' {
            if (-not (Test-Path -LiteralPath $painelHtml)) {
                Write-Host 'Painel HTML nao encontrado nesta pasta.' -ForegroundColor Yellow
                Read-Host 'Pressione Enter para voltar'
                continue
            }
            $caminhoCompleto = (Resolve-Path -LiteralPath $painelHtml).Path
            $urlHtml = ([System.Uri]$caminhoCompleto).AbsoluteUri
            if (Abrir-NoChrome $urlHtml 'painel') {
                Write-Host 'Painel visual solicitado ao Google Chrome.' -ForegroundColor Green
                Start-Sleep -Milliseconds 1000
            } else {
                Read-Host 'Pressione Enter para voltar'
            }
        }
        '4' {
            Start-Process -FilePath 'explorer.exe' -ArgumentList ('"{0}"' -f $PSScriptRoot)
        }
        '0' { $sair = $true }
        default {
            Write-Host 'Opcao invalida. Escolha 1, 2, 3, 4 ou 0.' -ForegroundColor Yellow
            Start-Sleep -Milliseconds 1000
        }
    }
}
Write-Host ''
Write-Host 'Obrigado por usar o AchaVagAI.' -ForegroundColor Cyan
Start-Sleep -Milliseconds 500
""".replace("__PAYLOAD__", payload).replace("__HTML_NAME__", html_nome_b64).replace("__XLSX_NAME__", xlsx_nome_b64)

    bat = f'''@echo off
setlocal EnableExtensions
chcp 65001 >nul
color 0B
title AchaVagAI - Central de Resultados
cls
echo.
echo   ============================================================
echo                 A C H A V A G A I
echo               CENTRAL DE RESULTADOS
echo   ============================================================
echo.
echo   Escolha como deseja consultar suas oportunidades:
echo.
echo     [1] Vaga individual pelo numero
echo     [2] Planilha Excel (.xlsx)
echo     [3] Painel visual no navegador (.html)
echo     [4] Pasta desta pesquisa
echo     [0] Sair
echo.
echo   Abrindo o menu interativo...
echo.
set "SCRIPT=%~dp0{caminho_ps1.name}"
if not exist "%SCRIPT%" (
  color 0C
  echo   ERRO: arquivo auxiliar nao encontrado:
  echo   {caminho_ps1.name}
  echo.
  pause
  exit /b 1
)
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%"
set "RC=%ERRORLEVEL%"
endlocal & exit /b %RC%
'''
    caminho_ps1.write_text(ps1, encoding="utf-8-sig")
    caminho_bat.write_text(bat, encoding="utf-8")
    return caminho_bat, caminho_ps1

def montar_planilha(
    ranking: list,
    mensagens: list,
    novas: set[int] | None = None,
    termos_busca: list[str] | tuple[str, ...] | None = None,
    perfil=None,
    nota_minima: float | None = None,
) -> Workbook:
    novas = novas or set()
    wb = Workbook()
    # A aba principal contém somente vagas com data de publicação interpretável.
    verificadas = selecionar_vagas_aba_principal(ranking)
    sem_data = [item for item in ranking if idade_em_dias(getattr(item[0], "data_publicacao", "")) is None]

    todas_classificadas = [(item, classificar_vaga(item[0], termos_busca, perfil)) for item in ranking]
    diretas = [item for item, categoria in todas_classificadas
               if categoria == "Pesquisa direta" and idade_em_dias(getattr(item[0], "data_publicacao", "")) is not None]
    compativeis = [item for item, categoria in todas_classificadas
                   if categoria == "Compatível com currículo" and idade_em_dias(getattr(item[0], "data_publicacao", "")) is not None]
    alternativas = [item for item, categoria in todas_classificadas
                    if categoria == "Alternativa" and idade_em_dias(getattr(item[0], "data_publicacao", "")) is not None]

    # Mantém o nome tradicional da primeira aba para não quebrar o fluxo do usuário.
    ws = wb.active
    ws.title = "Vagas"
    _preencher_aba(wb, "Cargos pesquisados", diretas, novas, termos_busca, perfil, nota_minima=nota_minima)
    _preencher_aba(wb, "Compatíveis", compativeis, novas, termos_busca, perfil, nota_minima=nota_minima)
    _preencher_aba(wb, "Alternativas", alternativas, novas, termos_busca, perfil, nota_minima=nota_minima)
    _preencher_aba(wb, "Data não confirmada", sem_data, novas, termos_busca, perfil, nota_minima=nota_minima)
    _preencher_aba(wb, "Todas as vagas", ranking, novas, termos_busca, perfil, nota_minima=nota_minima)

    # Principal: apenas publicações com data interpretável. A coluna de status mantém
    # explícito o que foi validado temporalmente.
    _preencher_aba_em_worksheet(ws, verificadas, novas, termos_busca, perfil, nota_minima)
    _aba_ajuda(wb)

    if mensagens:
        ws2 = wb.create_sheet("Mensagens de Candidatura")
        colunas2 = ["Cargo / Título", "Link", "Mensagem sugerida"]
        ws2.append(colunas2)
        _formatar_cabecalho(ws2, len(colunas2))
        for vaga, _pontuacao, mensagem in mensagens:
            ws2.append([_texto_seguro_excel(getattr(vaga, "titulo", "")), "", _texto_seguro_excel(mensagem)])
            linha = ws2.max_row
            _colocar_link(ws2.cell(row=linha, column=2), getattr(vaga, "link", ""))
            ws2.cell(row=linha, column=3).alignment = Alignment(wrap_text=True, vertical="top")
        ws2.column_dimensions["A"].width = 45
        ws2.column_dimensions["B"].width = 62
        ws2.column_dimensions["C"].width = 90
        ws2.freeze_panes = "A2"
    return wb


def _preencher_aba_em_worksheet(
    ws, itens: list[tuple], novas: set[int], termos_busca, perfil, nota_minima: float | None = None
) -> None:
    ws.append(_COLUNAS)
    _formatar_cabecalho(ws, len(_COLUNAS))
    for item in itens:
        valores, _categoria, _data_confirmada, link = _linha_vaga(
            item, novas, termos_busca, perfil, nota_minima
        )
        ws.append(valores)
        linha = ws.max_row
        _colocar_link(ws.cell(row=linha, column=9), link)
        nota = ws.cell(row=linha, column=1)
        nota.alignment = Alignment(horizontal="center", vertical="center")
        nota.fill = _VERDE if item[1] >= 80 else (_AMARELO if item[1] >= 50 else _VERMELHO)
        ws.cell(row=linha, column=2).alignment = Alignment(horizontal="center")
        ws.cell(row=linha, column=8).alignment = Alignment(wrap_text=True, vertical="top")
        ws.cell(row=linha, column=10).fill = _AZUL_CLARO
        ws.cell(row=linha, column=11).alignment = Alignment(horizontal="center")
        ws.row_dimensions[linha].height = 42
    larguras = {
        1: 14, 2: 8, 3: 50, 4: 26, 5: 22, 6: 21, 7: 18, 8: 60, 9: 62,
        10: 25, 11: 18, 12: 34, 13: 30,
    }
    for indice, largura in larguras.items():
        ws.column_dimensions[get_column_letter(indice)].width = largura
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:M{max(ws.max_row, 1)}"


def salvar_excel(
    ranking: list,
    mensagens: list,
    caminho: str | Path,
    novas: set[int] | None = None,
    termos_busca: list[str] | tuple[str, ...] | None = None,
    perfil=None,
    nota_minima: float | None = None,
) -> Path:
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    wb = montar_planilha(ranking, mensagens, novas, termos_busca, perfil, nota_minima)
    destino = caminho
    try:
        wb.save(destino)
    except PermissionError:
        for numero in range(2, 100):
            alternativo = caminho.with_name(f"{caminho.stem}_{numero}{caminho.suffix}")
            try:
                wb.save(alternativo)
                destino = alternativo
                break
            except PermissionError:
                continue
        else:
            raise

    # Ajuda explícita para casos em que Windows abre o Explorador ao clicar em HTTPS.
    try:
        _gerar_atalho_chrome(destino, ranking)
    except OSError:
        # A planilha já está salva; falha ao escrever o atalho auxiliar não invalida o XLSX.
        pass
    return destino
