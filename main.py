"""
main.py
AchaVagAI — encontra vagas de emprego combinando com o seu currículo.

Uso:
    python main.py caminho/para/curriculo.pdf

Fluxo:
  1. Lê o PDF do currículo. Se houver IA configurada (GEMINI_API_KEY ou
     ANTHROPIC_API_KEY, incluindo via arquivo .env), usa-a para extrair um perfil
     estruturado (cidade, bairro, cargo, senioridade, habilidades); caso contrário,
     usa uma extração local por palavras-chave.
  2. Pergunta/confirma os filtros de busca (cidade, bairro, palavra-chave — aceita
     várias separadas por vírgula, nº de dias).
  3. Busca vagas no LinkedIn, Indeed, Vagas.com, InfoJobs e nos portais regionais
     (RioVagas, Rio Emprega, Rio Empregos, VagasRio), uma vez para cada palavra-chave.
  4. Descarta vagas mais antigas que o número de dias informado (quando é possível
     identificar a data de publicação) e ranqueia as demais por aderência ao
     currículo (IA quando disponível, com justificativa por vaga; TF-IDF local como
     alternativa), descartando também as vagas abaixo da nota mínima configurada.
  5. Gera mensagens de candidatura personalizadas para as melhores vagas (se IA
     disponível).
  6. Salva os resultados em uma planilha Excel (.xlsx) formatada, com links
     clicáveis, e mostra as melhores vagas no terminal, em formato colorido.
"""

import argparse
import os
import re
import sys
from datetime import datetime

from dateutil import parser as dateparser

from dotenv import load_dotenv

load_dotenv()  # lê variáveis de um arquivo .env na pasta do projeto, se existir

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.prompt import Prompt

from resume_parser import analisar_curriculo
from scrapers import (
    buscar_vagas_linkedin,
    buscar_vagas_indeed,
    buscar_vagas_todos_wordpress,
    buscar_vagas_vagas_com,
    buscar_vagas_infojobs,
)
from matcher import ranquear_por_similaridade, ranquear
from mensagem import gerar_mensagens_top
from config import SITES_ATIVOS, CIDADES_RJ, NOTA_MINIMA_PADRAO
import ia

console = Console()

SEPARADOR_TITULO_RE = re.compile(r"\s[–-]\s")


def dividir_palavras_chave(texto: str) -> list[str]:
    """Permite buscar vários cargos de uma vez, separados por vírgula."""
    termos = [t.strip() for t in texto.split(",")]
    return [t for t in termos if t]


def perguntar(pergunta: str, padrao: str | None) -> str:
    return Prompt.ask(f"[bold cyan]{pergunta}[/bold cyan]", default=padrao or "")


def montar_filtros(perfil) -> dict:
    console.print("\n[bold]--- Confirme ou ajuste os filtros de busca ---[/bold] [dim](Enter mantém o valor sugerido)[/dim]")
    cidade = perguntar("Cidade", perfil.cidade)
    bairro = perguntar("Bairro (opcional, usado apenas na exibição)", perfil.bairro)
    palavra_chave = perguntar(
        "Palavra-chave / cargo desejado [dim](pode informar vários, separados por vírgula)[/dim]",
        perfil.cargo_sugerido,
    )
    dias = perguntar("Considerar vagas publicadas até quantos dias atrás?", "30")
    return {"cidade": cidade, "bairro": bairro, "palavra_chave": palavra_chave, "dias": dias}


def buscar_todas_vagas(filtros: dict) -> list:
    termos = dividir_palavras_chave(filtros["palavra_chave"]) or [""]
    todas_vagas = []

    fontes = [
        ("linkedin", "LinkedIn", buscar_vagas_linkedin),
        ("indeed", "Indeed", buscar_vagas_indeed),
        ("vagas_com", "Vagas.com", buscar_vagas_vagas_com),
        ("infojobs", "InfoJobs", buscar_vagas_infojobs),
    ]

    for termo in termos:
        rotulo = termo or "(sem palavra-chave)"

        for chave_config, nome_site, funcao_busca in fontes:
            if not SITES_ATIVOS.get(chave_config):
                continue
            with console.status(f"[cyan]Buscando no {nome_site} — {rotulo}...[/cyan]"):
                vagas = funcao_busca(termo, filtros["cidade"])
            for vaga in vagas:
                vaga.termo_busca = termo
            if vagas:
                console.print(f"  [green]✓[/green] {nome_site} ({rotulo}): [bold]{len(vagas)}[/bold] vaga(s)")
            todas_vagas += vagas

        with console.status(f"[cyan]Buscando nos portais regionais — {rotulo}...[/cyan]"):
            vagas = buscar_vagas_todos_wordpress(termo, SITES_ATIVOS)
        for vaga in vagas:
            vaga.termo_busca = termo
        console.print(f"  [green]✓[/green] Portais regionais ({rotulo}): [bold]{len(vagas)}[/bold] vaga(s)")
        todas_vagas += vagas

    return todas_vagas


def remover_duplicadas(vagas: list) -> list:
    vistos = set()
    unicas = []
    for vaga in vagas:
        if vaga.link not in vistos:
            vistos.add(vaga.link)
            unicas.append(vaga)
    return unicas


def _idade_em_dias(data_publicacao: str) -> int | None:
    """Calcula há quantos dias a vaga foi publicada. Retorna None se a data
    estiver vazia ou em um formato não reconhecido (nesse caso, a vaga não é
    descartada pelo filtro de data — não dá pra confirmar que está velha)."""
    if not data_publicacao:
        return None
    try:
        data = dateparser.parse(data_publicacao)
    except (ValueError, OverflowError, TypeError):
        return None
    if data is None:
        return None
    agora = datetime.now(data.tzinfo) if data.tzinfo else datetime.now()
    return (agora - data).days


def filtrar_por_data(vagas: list, dias_maximo: int) -> tuple[list, int, int]:
    """Remove vagas cuja data de publicação seja mais antiga que `dias_maximo`.
    Vagas sem data identificável são mantidas (não há como confirmar a idade),
    mas contadas separadamente para informar o usuário.
    Retorna (vagas_filtradas, quantidade_removida_por_idade, quantidade_sem_data)."""
    filtradas = []
    removidas_por_idade = 0
    sem_data = 0

    for vaga in vagas:
        idade = _idade_em_dias(vaga.data_publicacao)
        if idade is None:
            sem_data += 1
            filtradas.append(vaga)
        elif idade <= dias_maximo:
            filtradas.append(vaga)
        else:
            removidas_por_idade += 1

    return filtradas, removidas_por_idade, sem_data


def enriquecer_vaga(vaga):
    """Tenta preencher empresa/cidade quando vieram vazias, usando o padrão
    "Cargo – Empresa – Local" do próprio título e a lista de cidades conhecidas."""
    partes = SEPARADOR_TITULO_RE.split(vaga.titulo)

    if not vaga.empresa and len(partes) >= 3:
        vaga.empresa = partes[1].strip()

    if not vaga.cidade:
        candidata = partes[-1].strip() if len(partes) >= 2 else ""
        if "RJ" in candidata or any(cidade.lower() in candidata.lower() for cidade in CIDADES_RJ):
            vaga.cidade = candidata
        else:
            cidade_no_titulo = next(
                (cidade for cidade in CIDADES_RJ if cidade.lower() in vaga.titulo.lower()), None
            )
            if cidade_no_titulo:
                vaga.cidade = cidade_no_titulo

    return vaga


def salvar_excel(ranking: list, mensagens: list, caminho: str) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Vagas"

    colunas = ["Pontuação (%)", "Cargo / Título", "Empresa", "Cidade", "Publicada em", "Fonte", "Motivo (IA)", "Link"]
    ws.append(colunas)
    _formatar_cabecalho(ws, len(colunas))

    for vaga, pontuacao, motivo in ranking:
        vaga = enriquecer_vaga(vaga)
        ws.append([pontuacao, vaga.titulo, vaga.empresa, vaga.cidade, vaga.data_publicacao, vaga.fonte, motivo, vaga.link])
        numero_linha = ws.max_row
        celula_link = ws.cell(row=numero_linha, column=8)
        celula_link.hyperlink = vaga.link
        celula_link.font = Font(color="0563C1", underline="single")
        ws.cell(row=numero_linha, column=1).alignment = Alignment(horizontal="center")

    larguras = {1: 14, 2: 50, 3: 26, 4: 20, 5: 16, 6: 14, 7: 45, 8: 55}
    for col_idx, largura in larguras.items():
        ws.column_dimensions[get_column_letter(col_idx)].width = largura
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:H{ws.max_row}"

    if mensagens:
        ws2 = wb.create_sheet("Mensagens de Candidatura")
        colunas2 = ["Cargo / Título", "Link", "Mensagem sugerida"]
        ws2.append(colunas2)
        _formatar_cabecalho(ws2, len(colunas2))
        for vaga, _pontuacao, mensagem in mensagens:
            ws2.append([vaga.titulo, vaga.link, mensagem])
            numero_linha = ws2.max_row
            celula_link = ws2.cell(row=numero_linha, column=2)
            celula_link.hyperlink = vaga.link
            celula_link.font = Font(color="0563C1", underline="single")
            ws2.cell(row=numero_linha, column=3).alignment = Alignment(wrap_text=True, vertical="top")
        ws2.column_dimensions["A"].width = 45
        ws2.column_dimensions["B"].width = 50
        ws2.column_dimensions["C"].width = 90
        ws2.freeze_panes = "A2"

    wb.save(caminho)


def _formatar_cabecalho(ws, n_colunas: int) -> None:
    cabecalho_fonte = Font(bold=True, color="FFFFFF")
    cabecalho_fundo = PatternFill(start_color="2F5597", end_color="2F5597", fill_type="solid")
    for col_idx in range(1, n_colunas + 1):
        celula = ws.cell(row=1, column=col_idx)
        celula.font = cabecalho_fonte
        celula.fill = cabecalho_fundo
        celula.alignment = Alignment(horizontal="center", vertical="center")


def exibir_perfil(perfil) -> None:
    tabela = Table(show_header=False, box=None, padding=(0, 1))
    tabela.add_row("[bold]Nome:[/bold]", perfil.nome or "[dim]não identificado[/dim]")
    tabela.add_row("[bold]Cidade:[/bold]", perfil.cidade or "[dim]não identificada[/dim]")
    tabela.add_row("[bold]Bairro:[/bold]", perfil.bairro or "[dim]não identificado[/dim]")
    tabela.add_row("[bold]Habilidades:[/bold]", ", ".join(perfil.habilidades) or "[dim]nenhuma identificada[/dim]")
    tabela.add_row("[bold]Cargo sugerido:[/bold]", perfil.cargo_sugerido or "[dim]não identificado[/dim]")
    if perfil.senioridade:
        tabela.add_row("[bold]Senioridade:[/bold]", perfil.senioridade)
    if perfil.resumo:
        tabela.add_row("[bold]Resumo:[/bold]", perfil.resumo)
    titulo = "Currículo analisado" + (" (via IA)" if perfil.extraido_por_ia else " (extração local)")
    console.print(Panel(tabela, title=f"[bold white]{titulo}[/bold white]", border_style="cyan"))
    if perfil.erro_ia:
        console.print(f"[yellow]A extração por IA do currículo falhou — usei a extração local acima. Motivo: {perfil.erro_ia}[/yellow]")


def exibir_resultados(ranking: list, top_n: int) -> None:
    tabela = Table(title=f"Top {min(top_n, len(ranking))} vagas mais compatíveis", header_style="bold white on dark_cyan")
    tabela.add_column("Nota", justify="center", width=6)
    tabela.add_column("Vaga", style="bold")
    tabela.add_column("Local", style="magenta")
    tabela.add_column("Fonte", style="yellow")
    tabela.add_column("Motivo (IA)", style="dim italic")

    for vaga, pontuacao, motivo in ranking[:top_n]:
        vaga = enriquecer_vaga(vaga)
        cor_nota = "green" if pontuacao >= 60 else ("yellow" if pontuacao >= 35 else "red")
        tabela.add_row(f"[{cor_nota}]{pontuacao:.0f}[/{cor_nota}]", vaga.titulo, vaga.cidade or "-", vaga.fonte, motivo or "-")
    console.print(tabela)

    console.print("\n[bold]Links para candidatura:[/bold]")
    for i, (vaga, _pontuacao, _motivo) in enumerate(ranking[:top_n], start=1):
        console.print(f"  {i}. [link={vaga.link}]{vaga.link}[/link]")


def exibir_mensagens(mensagens: list) -> None:
    if not mensagens:
        return
    console.print("\n[bold magenta]--- Mensagens de candidatura sugeridas (top vagas) ---[/bold magenta]")
    for vaga, _pontuacao, mensagem in mensagens:
        console.print(Panel(mensagem, title=f"[bold]{vaga.titulo}[/bold]", border_style="magenta", subtitle=vaga.link))


def main():
    parser = argparse.ArgumentParser(description="AchaVagAI - encontra vagas combinando com seu currículo")
    parser.add_argument("curriculo_pdf", help="Caminho para o arquivo PDF do currículo")
    parser.add_argument("--sem-ia", action="store_true", help="Desativa toda a análise de IA (ranking, extração de perfil e mensagens), mesmo com chave configurada.")
    parser.add_argument("--com-mensagens", action="store_true", help="Gera mensagens de candidatura personalizadas para as melhores vagas (desativado por padrão — usa chamadas extras de IA).")
    parser.add_argument("--top", type=int, default=15, help="Quantas vagas mostrar no resumo final (padrão: 15)")
    parser.add_argument("--top-mensagens", type=int, default=5, help="Para quantas vagas do topo gerar mensagem de candidatura (padrão: 5)")
    parser.add_argument("--nota-minima", type=float, default=NOTA_MINIMA_PADRAO, help=f"Nota mínima (0-100) para uma vaga aparecer nos resultados (padrão: {NOTA_MINIMA_PADRAO})")
    args = parser.parse_args()

    if args.sem_ia:
        os.environ.pop("GEMINI_API_KEY", None)
        os.environ.pop("ANTHROPIC_API_KEY", None)

    console.rule("[bold cyan]ACHAVAGAI[/bold cyan]")

    console.print(f"[dim]Lendo currículo:[/dim] {args.curriculo_pdf}")
    perfil = analisar_curriculo(args.curriculo_pdf)
    exibir_perfil(perfil)

    filtros = montar_filtros(perfil)

    console.print("\n[bold]--- Buscando vagas ---[/bold]")
    vagas = remover_duplicadas(buscar_todas_vagas(filtros))
    console.print(f"\n[bold]Total de vagas encontradas (após remover duplicadas):[/bold] {len(vagas)}")

    if not vagas:
        console.print("[red]Nenhuma vaga encontrada. Tente ajustar a palavra-chave ou verifique sua conexão.[/red]")
        sys.exit(0)

    try:
        dias_maximo = int(filtros["dias"])
    except (ValueError, TypeError):
        dias_maximo = None

    if dias_maximo:
        vagas, removidas_por_idade, sem_data = filtrar_por_data(vagas, dias_maximo)
        if removidas_por_idade:
            console.print(
                f"[dim]{removidas_por_idade} vaga(s) publicada(s) há mais de {dias_maximo} dias foram descartadas.[/dim]"
            )
        if sem_data:
            console.print(
                f"[dim]{sem_data} vaga(s) sem data identificável foram mantidas (não dá pra confirmar a idade).[/dim]"
            )

    if not vagas:
        console.print("[red]Nenhuma vaga passou do filtro de data. Tente aumentar o número de dias.[/red]")
        sys.exit(0)

    provedor = ia.provedor_disponivel()
    usou_ia = False
    if provedor:
        nome_provedor = "Gemini" if provedor == "gemini" else "Claude"
        console.print(f"\n[bold magenta]Analisando vagas com IA ({nome_provedor}) — isso pode levar alguns segundos...[/bold magenta]")
        with console.status("[magenta]Avaliando aderência ao currículo...[/magenta]"):
            ranking, usou_ia = ranquear(perfil.texto_completo, vagas)
        if not usou_ia:
            motivo_erro = ia.ultimo_erro or "motivo desconhecido"
            console.print(
                f"[yellow]A chamada à IA ({nome_provedor}) falhou nesta execução — usando ranking local "
                f"(TF-IDF) como alternativa, sem justificativa por vaga.[/yellow]\n"
                f"[dim]Motivo reportado: {motivo_erro}[/dim]"
            )
    else:
        console.print(
            "\n[yellow]Nenhuma chave de IA configurada — usando ranking local (TF-IDF), mais simples.[/yellow]\n"
            "[dim]Para uma análise mais profunda e gratuita, crie uma chave em "
            "https://aistudio.google.com/apikey, salve em um arquivo .env como GEMINI_API_KEY=sua-chave.[/dim]"
        )
        ranking = ranquear_por_similaridade(perfil.texto_completo, vagas)

    total_antes_filtro = len(ranking)
    ranking_completo = ranking  # guarda a lista completa (antes do filtro) para diagnóstico, se precisar
    ranking = [item for item in ranking if item[1] >= args.nota_minima]
    descartadas = total_antes_filtro - len(ranking)
    if descartadas:
        console.print(f"[dim]{descartadas} vaga(s) abaixo de {args.nota_minima:.0f}% de aderência foram descartadas (ajuste com --nota-minima).[/dim]")

    if not ranking:
        console.print(
            f"[red]Nenhuma vaga passou do filtro de nota mínima ({args.nota_minima:.0f}%).[/red]\n"
            "[yellow]Isso pode ser normal — ex.: se a vaga exige um requisito que seu currículo não "
            "atende (CNH de categoria diferente, curso técnico específico etc.), a IA reprova mesmo que "
            "o título pareça relacionado.[/yellow]\n"
            "[dim]Veja abaixo as vagas com maior nota mesmo assim, para entender o motivo:[/dim]"
        )
        exibir_resultados(ranking_completo, min(5, len(ranking_completo)))
        console.print(
            "\n[dim]Se quiser ver todas mesmo abaixo da nota mínima, rode de novo com --nota-minima 0.[/dim]"
        )
        nome_arquivo = f"vagas_encontradas_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
        salvar_excel(ranking_completo, [], nome_arquivo)
        console.print(f"\n[bold green]✓[/bold green] Mesmo assim, salvei todas as vagas avaliadas (com nota e motivo) em: [bold]{nome_arquivo}[/bold]")
        sys.exit(0)

    console.print()
    exibir_resultados(ranking, args.top)

    mensagens = []
    if provedor and args.com_mensagens:
        console.print(f"\n[bold magenta]Gerando mensagens de candidatura para as top {args.top_mensagens} vagas...[/bold magenta]")
        with console.status("[magenta]Escrevendo mensagens personalizadas...[/magenta]"):
            mensagens = gerar_mensagens_top(perfil.texto_completo, ranking, quantidade=args.top_mensagens)
        exibir_mensagens(mensagens)

    nome_arquivo = f"vagas_encontradas_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
    salvar_excel(ranking, mensagens, nome_arquivo)
    console.print(f"\n[bold green]✓[/bold green] Resultados completos salvos em: [bold]{nome_arquivo}[/bold]")
    console.print("[dim]Abra no Excel — os links já são clicáveis; mensagens de candidatura ficam na segunda aba.[/dim]")


if __name__ == "__main__":
    main()
