"""
main.py
AchaVagAI: encontra vagas de emprego combinando com o seu currículo.

Uso:
    python main.py caminho/para/curriculo.pdf

Fluxo:
  1. Lê o PDF do currículo. Se houver IA configurada (GEMINI_API_KEY ou
     ANTHROPIC_API_KEY, inclusive via arquivo .env), usa-a para extrair um perfil
     estruturado (cidade, bairro, cargo, senioridade, habilidades); caso contrário,
     usa uma extração local por palavras-chave.
  2. Pergunta/confirma os filtros de busca (cidade, bairro, palavra-chave, que
     aceita várias separadas por vírgula, e nº de dias).
  3. Busca vagas em Vagas.com, InfoJobs, Empregare, Empregando Brasil, Gupy,
     Jooble (se configurado) e portais regionais. Indeed e LinkedIn ficam desativados
     por padrão e são oferecidos como buscas manuais. Cada fonte mostra seu diagnóstico.
  4. Remove duplicadas, descarta vagas antigas (quando há data), de outros estados
     e fora da nota mínima. Ranqueia por aderência ao currículo: IA quando disponível
     (com justificativa por vaga, lendo a descrição completa das melhores candidatas),
     TF-IDF local como alternativa.
  5. Reaproveita notas de execuções anteriores (cache) e marca as vagas NOVAS.
  6. Gera mensagens de candidatura para as melhores vagas (se IA disponível e
     --com-mensagens).
  7. Salva os resultados em uma planilha Excel (.xlsx), um painel visual local HTML
     e mostra as melhores vagas no terminal.

Dá para rodar sem nenhuma pergunta: veja --sim, --cidade, --cargo, --dias e --saida.
"""

from __future__ import annotations

# Mostra atividade imediatamente, antes de carregar dependências externas.
# Isso evita que a janela pareça congelada enquanto os módulos são importados.
import time
_BOOT_INICIO = time.monotonic()
_EXECUTADO_COMO_SCRIPT = __name__ == "__main__"
if _EXECUTADO_COMO_SCRIPT:
    print("AchaVagAI: inicializando componentes...", flush=True)

import argparse
import glob
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")  # lê o .env da pasta do projeto, de onde quer que o script seja chamado

from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

import config
import descricoes
import ia
from config import NOTA_MINIMA_PADRAO, SITES_ATIVOS, UF_ALVO
from exportar import salvar_excel
from classificacao import classificar_vaga
from filtros import (
    dividir_palavras_chave,
    enriquecer_vaga,
    filtrar_encerradas,
    filtrar_por_data,
    filtrar_por_regiao,
    idade_em_dias,
    motivo_de_encerramento,
    remover_duplicadas,
)
from habilitacao import filtrar_por_habilitacao, motivo_de_eliminacao
from historico import Historico, chave_do_contexto
from matcher import MOTIVO_SEM_IA, PROMPT_VERSAO, ranquear_detalhado, ranquear_por_similaridade
from mensagem import gerar_mensagens_top
from resume_parser import CurriculoInvalido, analisar_curriculo
from intencao_busca import filtrar_por_intencao

# A pasta scrapers/ tem um módulo por site. Se ela não estiver ao lado deste arquivo,
# o programa avisa com clareza em vez de mostrar um erro técnico.
try:
    from scrapers import (
        buscar_vagas_indeed,
        buscar_vagas_infojobs,
        buscar_vagas_linkedin,
        buscar_vagas_todos_wordpress,
        buscar_vagas_vagas_com,
        buscar_vagas_empregare,
        buscar_vagas_empregando_brasil,
        buscar_vagas_jooble,
        buscar_vagas_gupy,
    )
    from scrapers.diagnostico import limpar_todos as limpar_diagnosticos, obter as obter_diagnostico, listar as listar_diagnosticos
    ERRO_SCRAPERS: ImportError | None = None
except ImportError as _erro:
    ERRO_SCRAPERS = _erro
    buscar_vagas_indeed = buscar_vagas_infojobs = buscar_vagas_linkedin = None
    buscar_vagas_todos_wordpress = buscar_vagas_vagas_com = None
    buscar_vagas_empregare = buscar_vagas_empregando_brasil = buscar_vagas_jooble = buscar_vagas_gupy = None
    limpar_diagnosticos = obter_diagnostico = listar_diagnosticos = None

console = Console()


def _cfg(nome: str, padrao):
    return getattr(config, nome, padrao)


def _gerar_painel_html(ranking_exportacao, caminho_xlsx, novas, termos_busca, perfil, filtros, dias_maximo):
    """Gera o painel local HTML usando exatamente a mesma base do Excel."""
    try:
        # Importação local para não aumentar o tempo de inicialização do CLI.
        from html_report import salvar_html

        destino_html = Path(caminho_xlsx).with_suffix(".html")
        return salvar_html(
            ranking_exportacao,
            destino_html,
            novas=novas,
            termos_busca=termos_busca,
            perfil=perfil,
            metadata={
                "cidade": filtros.get("cidade", ""),
                "bairro": filtros.get("bairro", ""),
                "uf": UF_ALVO,
                "dias_maximo": dias_maximo,
            },
        )
    except Exception as erro:
        console.print(f"[yellow]Não foi possível gerar o painel HTML: {escape(type(erro).__name__)}: {escape(str(erro)[:240])}[/yellow]")
        return None


def _mostrar_central_resultados(salvo: Path, html_salvo: Path | None, args) -> None:
    """Mostra a Central .BAT e, em execução interativa, permite abri-la imediatamente."""
    salvo = Path(salvo)
    atalho_bat = salvo.with_name(f"abrir_links_chrome_{salvo.stem}.bat")
    atalho_ps1 = salvo.with_name(f"abrir_links_chrome_{salvo.stem}.ps1")

    console.print()
    console.print(Panel(
        "[bold green]SUA PESQUISA ESTÁ PRONTA![/bold green]\n\n"
        "Para consultar as oportunidades, abra a [bold cyan]CENTRAL DE RESULTADOS (.BAT)[/bold cyan]:\n"
        f"[bold white]{escape(atalho_bat.name)}[/bold white]\n\n"
        "Dentro dela, escolha como deseja acessar suas vagas:\n"
        "[green]1[/green]  Abrir uma vaga pelo número (uma por vez)\n"
        "[cyan]2[/cyan]  Abrir a planilha Excel (.xlsx)\n"
        "[magenta]3[/magenta]  Abrir o painel visual no navegador (.html)\n"
        "[yellow]4[/yellow]  Abrir a pasta desta pesquisa\n"
        "[red]0[/red]  Sair",
        title="[bold cyan]ACHA VAGAI | CENTRAL DE RESULTADOS[/bold cyan]",
        border_style="green",
        padding=(1, 2),
    ))
    console.print(f"[dim]Planilha: {escape(salvo.name)}[/dim]")
    if html_salvo:
        console.print(f"[dim]Painel: {escape(Path(html_salvo).name)}[/dim]")
    if not atalho_bat.is_file():
        console.print("[yellow]O atalho .BAT não foi criado. Confira se há links HTTP/HTTPS válidos nas vagas.[/yellow]")
        return
    if not atalho_ps1.is_file():
        console.print("[yellow]O arquivo auxiliar .PS1 não foi encontrado ao lado do .BAT.[/yellow]")
        return

    console.print(f"[bold green]Central criada:[/bold green] [cyan]{escape(str(atalho_bat))}[/cyan]")
    # --sim significa execução sem interação; nesse caso apenas mostra o caminho.
    if args.sim or not getattr(sys.stdin, "isatty", lambda: False)():
        console.print("[bold yellow]Dê dois cliques no arquivo .BAT acima para abrir o menu de resultados.[/bold yellow]")
        return

    resposta = console.input("\n[bold yellow]Digite [B] e pressione Enter para abrir a Central agora, ou pressione Enter para encerrar: [/bold yellow]")
    if resposta.strip().casefold() == "b":
        iniciar = getattr(os, "startfile", None)
        if sys.platform == "win32" and callable(iniciar):
            try:
                iniciar(str(atalho_bat))
                console.print("[bold green]Central de resultados aberta em uma nova janela.[/bold green]")
            except OSError as erro:
                console.print(f"[red]Não consegui abrir o .BAT automaticamente: {escape(str(erro)[:220])}[/red]")
                console.print("[yellow]Abra-o manualmente com dois cliques no Explorador de Arquivos.[/yellow]")
        else:
            console.print("[yellow]A abertura automática está disponível no Windows. Execute o .BAT manualmente neste sistema.[/yellow]")


def _gerar_painel_vazio(args, filtros, perfil, termos_busca):
    """Mesmo uma busca sem resultados gera uma página explicando que não houve vagas."""
    pasta_saida = Path(args.saida) if args.saida else Path(".")
    nome_base = pasta_saida / f"vagas_encontradas_{datetime.now().strftime('%Y%m%d_%H%M')}"
    html_salvo = _gerar_painel_html([], nome_base.with_suffix(".xlsx"), set(), termos_busca, perfil, filtros, None)
    if html_salvo:
        console.print(f"[dim]Painel HTML sem resultados salvo em: {escape(str(html_salvo))}[/dim]")


# ---------------------------------------------------------------------------
# Entrada: perguntas, caminho do PDF, configuração da IA
# ---------------------------------------------------------------------------

def perguntar(pergunta: str, padrao: str | None) -> str:
    return Prompt.ask(f"[bold cyan]{pergunta}[/bold cyan]", default=padrao or "")


def _limpar_caminho(caminho: str) -> str:
    """Remove aspas que costumam vir junto quando se arrasta um arquivo para o
    terminal, ou quando se copia um caminho do Explorador de Arquivos do Windows."""
    return caminho.strip().strip('"').strip("'")


def _listar_pdfs() -> list[tuple[str, str]]:
    """(rótulo, caminho) dos PDFs da pasta atual ou, se não houver nenhum, da pasta
    do projeto."""
    nomes = sorted(glob.glob("*.pdf"))
    if nomes:
        return [(nome, nome) for nome in nomes]
    return [(p.name, str(p)) for p in sorted(BASE_DIR.glob("*.pdf"))]


def resolver_caminho_pdf(caminho_informado: str | None, automatico: bool = False) -> str:
    """Garante um caminho válido para o PDF do currículo antes de continuar, sem
    nunca deixar o script quebrar com um erro feio de arquivo não encontrado.

    - Se `caminho_informado` já existir, usa ele direto.
    - Se não existir (ou não tiver sido informado), tenta ajudar: encontra .pdf na
      pasta atual (sugerindo se houver 1, ou listando para escolher se houver vários)
      e, em último caso, pede o caminho completo digitado.
    - Com `automatico` (flag --sim) e um único PDF na pasta, usa esse sem perguntar."""
    if caminho_informado:
        caminho_informado = _limpar_caminho(caminho_informado)
        if os.path.isfile(caminho_informado):
            return caminho_informado
        console.print(f"[yellow]Não encontrei o arquivo \"{escape(caminho_informado)}\".[/yellow]")

    while True:
        pdfs = _listar_pdfs()

        if len(pdfs) == 1:
            if automatico or Confirm.ask(
                f"Encontrei [bold]{escape(pdfs[0][0])}[/bold] na pasta, usar esse arquivo?", default=True
            ):
                return pdfs[0][1]
        elif len(pdfs) > 1:
            console.print("\n[bold]Encontrei vários PDFs na pasta:[/bold]")
            for i, (rotulo, _) in enumerate(pdfs, start=1):
                console.print(f"  {i}. {escape(rotulo)}")
            escolha = _limpar_caminho(
                perguntar("Digite o número do currículo desejado, ou cole o caminho completo de outro arquivo", "1")
            )
            if escolha.isdigit() and 1 <= int(escolha) <= len(pdfs):
                return pdfs[int(escolha) - 1][1]
            if os.path.isfile(escolha):
                return escolha
            console.print(f"[yellow]Não encontrei \"{escape(escolha)}\".[/yellow]")
            continue

        caminho_manual = _limpar_caminho(perguntar("Digite o caminho completo do PDF do currículo", ""))
        if os.path.isfile(caminho_manual):
            return caminho_manual
        console.print(f"[red]Não encontrei \"{escape(caminho_manual)}\". Tente novamente.[/red]")


def _salvar_env(chaves: dict) -> None:
    """Salva (ou atualiza) o .env da pasta do projeto, preservando os comentários e
    as outras variáveis que já estavam lá."""
    caminho = BASE_DIR / ".env"
    linhas = caminho.read_text(encoding="utf-8").splitlines() if caminho.is_file() else []
    pendentes = dict(chaves)
    novas = []
    for linha in linhas:
        nome = linha.split("=", 1)[0].strip()
        if "=" in linha and not linha.lstrip().startswith("#") and nome in pendentes:
            novas.append(f"{nome}={pendentes.pop(nome)}")
        else:
            novas.append(linha)
    novas.extend(f"{nome}={valor}" for nome, valor in pendentes.items())
    caminho.write_text("\n".join(novas).rstrip("\n") + "\n", encoding="utf-8")
    console.print("[bold green]✓[/bold green] Chave(s) salva(s) em [bold].env[/bold]. Não vai precisar configurar de novo.")


def configurar_ia_interativa() -> None:
    """Se nenhuma chave de IA estiver configurada (nem por .env, nem por variável de
    ambiente), explica os benefícios e oferece configurar uma agora, sem precisar sair
    do script para editar arquivo nenhum."""
    if ia.provedor_disponivel():
        return

    console.print(Panel(
        "O AchaVagAI funciona sem IA (usando um ranking local mais simples, por "
        "similaridade de texto), mas fica bem melhor com uma IA configurada:\n\n"
        "• Lê o currículo inteiro e entende contexto, não só palavras-chave soltas\n"
        "• Avalia requisitos reais da vaga (ex.: categoria de CNH, curso técnico, "
        "vaga exclusiva PCD) em vez de só comparar se o título parece parecido\n"
        "• Explica o motivo de cada nota\n"
        "• Pode gerar mensagens de candidatura prontas para copiar e enviar\n\n"
        "O [bold]Gemini[/bold] (Google) tem plano gratuito e não pede cartão de crédito. "
        "Crie uma chave em [bold]https://aistudio.google.com/apikey[/bold].\n"
        "[dim]Atenção: no plano gratuito o Google pode usar o que for enviado para melhorar seus "
        "produtos. Por isso o AchaVagAI remove CPF, telefone, e-mail e endereço do currículo "
        "antes de enviar (veja ANONIMIZAR_CURRICULO no config.py).[/dim]",
        title="[bold]Nenhuma IA configurada[/bold]",
        border_style="yellow",
    ))

    if not Confirm.ask("Quer configurar uma chave de IA agora?", default=True):
        console.print("[dim]Ok, seguindo sem IA. Pode configurar depois criando um arquivo .env na pasta do projeto.[/dim]")
        return

    nomes_provedor = {"gemini": ("GEMINI_API_KEY", "Gemini"), "claude": ("ANTHROPIC_API_KEY", "Claude")}
    chaves_coletadas = {}

    while True:
        escolha = Prompt.ask("Qual provedor você quer configurar", choices=["gemini", "claude"], default="gemini")
        nome_var, nome_exibicao = nomes_provedor[escolha]
        console.print("[dim](a chave não aparece na tela enquanto você cola; é normal)[/dim]")
        chave_valor = Prompt.ask(f"Cole sua chave do {nome_exibicao}", password=True).strip()

        if chave_valor:
            chaves_coletadas[nome_var] = chave_valor
            os.environ[nome_var] = chave_valor
            console.print(f"[green]✓[/green] {nome_exibicao} configurado para esta execução.")
        else:
            console.print("[yellow]Nenhuma chave informada, pulando.[/yellow]")

        if not Confirm.ask("Quer adicionar a chave de outro provedor também (ex.: como alternativa)?", default=False):
            break

    if chaves_coletadas:
        _salvar_env(chaves_coletadas)


def montar_filtros(perfil, args=None) -> dict:
    """Pergunta os filtros de busca. Valores passados por linha de comando
    (--cidade, --bairro, --cargo, --dias) não são perguntados; com --sim, os demais
    assumem a sugestão do currículo sem perguntar."""
    automatico = bool(args and getattr(args, "sim", False))

    def valor(opcao, pergunta, padrao):
        if opcao is not None:
            return str(opcao)
        if automatico:
            return padrao or ""
        return perguntar(pergunta, padrao)

    if not automatico:
        console.print("\n[bold]--- Confirme ou ajuste os filtros de busca ---[/bold] [dim](Enter mantém o valor sugerido)[/dim]")
    return {
        "cidade": valor(getattr(args, "cidade", None), "Cidade", perfil.cidade),
        "bairro": valor(getattr(args, "bairro", None), "Bairro (opcional, usado apenas na exibição)", perfil.bairro),
        "palavra_chave": valor(
            getattr(args, "cargo", None),
            "Palavra-chave / cargo desejado [dim](pode informar vários, separados por vírgula)[/dim]",
            perfil.cargo_sugerido,
        ),
        "dias": valor(getattr(args, "dias", None), "Considerar vagas publicadas até quantos dias atrás?", "30"),
    }


# ---------------------------------------------------------------------------
# Busca nos sites
# ---------------------------------------------------------------------------

def _montar_fontes(filtros: dict) -> list[tuple[str, object]]:
    """Lista de (nome do site, função que recebe o termo e devolve as vagas)."""
    cidade = filtros["cidade"]
    fontes = []
    for chave, nome, funcao in (
        ("linkedin", "LinkedIn", buscar_vagas_linkedin),
        ("indeed", "Indeed", buscar_vagas_indeed),
        ("vagas_com", "Vagas.com", buscar_vagas_vagas_com),
        ("infojobs", "InfoJobs", buscar_vagas_infojobs),
    ):
        if SITES_ATIVOS.get(chave):
            fontes.append((nome, lambda termo, f=funcao: f(termo, cidade)))
    for chave, nome, funcao in (
        ("empregare", "Empregare", buscar_vagas_empregare),
        ("empregando_brasil", "Empregando Brasil", buscar_vagas_empregando_brasil),
        ("gupy", "Gupy", buscar_vagas_gupy),
        ("jooble", "Jooble", buscar_vagas_jooble),
    ):
        if SITES_ATIVOS.get(chave) and funcao is not None:
            fontes.append((nome, lambda termo, f=funcao: f(termo, cidade)))
    # O grupo dos portais regionais decide sozinho quais sites usar (SITES_ATIVOS).
    fontes.append(("Portais regionais", lambda termo: buscar_vagas_todos_wordpress(termo, SITES_ATIVOS)))
    return fontes


def _buscar_na_fonte(nome: str, funcao, termos: list[str]) -> dict:
    """Roda todos os termos em UM site, um de cada vez (para respeitar a pausa entre
    requisições do mesmo site). Um erro no site não derruba a busca nos outros."""
    inicio = time.monotonic()
    vagas, por_termo, erros = [], {}, []
    for termo in termos:
        try:
            achadas = list(funcao(termo) or [])
        except Exception as erro:  # um scraper quebrado (site mudou) não pode parar tudo
            erros.append(f"{erro.__class__.__name__}: {erro}")
            continue
        for vaga in achadas:
            vaga.termo_busca = termo
        por_termo[termo or "(sem palavra-chave)"] = len(achadas)
        vagas += achadas
    # Uma mesma vaga pode aparecer em várias buscas do mesmo portal quando o
    # usuário informa vários cargos. Exibe e devolve a contagem já deduplicada.
    vagas = remover_duplicadas(vagas)
    return {"nome": nome, "vagas": vagas, "por_termo": por_termo, "erros": erros, "segundos": time.monotonic() - inicio}


def _relatar_fonte(resultado: dict, varios_termos: bool) -> None:
    nome, quantidade = escape(resultado["nome"]), len(resultado["vagas"])
    detalhe = ""
    if varios_termos and quantidade:
        detalhe = " [dim](" + ", ".join(f"{escape(t)}: {n}" for t, n in resultado["por_termo"].items()) + ")[/dim]"
    tempo = f" [dim]{resultado['segundos']:.0f}s[/dim]"

    if resultado["erros"] and not quantidade:
        console.print(f"  [red]✗[/red] {nome}: falhou. [dim]{escape(resultado['erros'][0][:160])}[/dim]")
    elif quantidade:
        console.print(f"  [green]✓[/green] {nome}: [bold]{quantidade}[/bold] vaga(s){detalhe}{tempo}")
        if resultado["erros"]:
            console.print(f"    [yellow]Algumas buscas falharam:[/yellow] [dim]{escape(resultado['erros'][0][:160])}[/dim]")
        elif obter_diagnostico:
            estado_fonte = obter_diagnostico(resultado["nome"])
            if estado_fonte.get("status") == "parcial":
                console.print(f"    [yellow]Consulta parcial:[/yellow] [dim]{escape(estado_fonte.get('detalhe', 'uma ou mais páginas/termos falharam')[:240])}[/dim]")
    else:
        estado = {}
        if obter_diagnostico:
            if resultado["nome"] == "Portais regionais" and listar_diagnosticos:
                nomes_regionais = {"RioVagas", "Rio Emprega", "Rio Empregos", "VagasRio"}
                itens = [d for d in listar_diagnosticos() if d.get("fonte") in nomes_regionais]
                prioridades = {"estrutura_alterada": 5, "bloqueio": 4, "erro_http": 3,
                               "erro_rede": 2, "configuracao_ausente": 1, "sem_resultados": 0}
                estado = max(itens, key=lambda d: prioridades.get(d.get("status"), -1), default={})
            else:
                estado = obter_diagnostico(resultado["nome"])
        status = estado.get("status", "sem_diagnostico")
        detalhe_estado = estado.get("detalhe", "")
        if status == "sem_resultados":
            explicacao = "página/API reconhecida; a fonte informou que não há resultados"
        elif status == "estrutura_alterada":
            explicacao = "possível mudança no HTML; extrator alternativo não reconheceu os cartões"
            if estado.get("snapshot"):
                detalhe_estado += f" | DOM estrutural: {estado['snapshot']}"
        elif status == "bloqueio":
            explicacao = "proteção/CAPTCHA detectado; nenhuma tentativa de contornar a proteção"
        elif status == "acesso_negado":
            explicacao = "servidor recusou a requisição (HTTP 403); não é falha de conexão"
        elif status == "autenticacao_falhou":
            explicacao = "autenticação recusada (HTTP 401); verifique a credencial da fonte"
        elif status == "limite_requisicoes":
            explicacao = "limite de requisições atingido (HTTP 429); tente após a janela de renovação"
        elif status == "proxy_requer_autenticacao":
            explicacao = "proxy exige autenticação (HTTP 407)"
        elif status == "restricao_legal":
            explicacao = "acesso indisponível por restrição legal (HTTP 451)"
        elif status == "parcial":
            explicacao = "algumas consultas falharam e outras responderam; veja o diagnóstico abaixo"
        elif status == "erro_http":
            explicacao = "erro HTTP devolvido pelo portal"
        elif status == "erro_rede":
            explicacao = "falha de conexão/timeout"
        elif status == "configuracao_ausente":
            explicacao = "fonte opcional não configurada"
        elif status == "resposta_vazia":
            explicacao = "resposta vazia ou curta demais para identificar a página"
        else:
            explicacao = "nenhum anúncio foi extraído; a causa não foi identificada"
        console.print(f"  [yellow]-[/yellow] {nome}: 0 vaga(s){tempo} [dim]({explicacao})[/dim]")
        if detalhe_estado:
            console.print(f"    [dim]{escape(detalhe_estado[:260])}[/dim]")


def _montar_urls_busca_manual(fonte: str, termos: list[str], cidade: str) -> list[tuple[str, str]]:
    """Retorna (termo, URL) para uma busca manual específica por cargo."""
    from urllib.parse import urlencode

    urls = []
    for termo in termos:
        termo = str(termo or "").strip()
        if not termo:
            continue
        if fonte.lower() == "indeed":
            url = "https://br.indeed.com/jobs?" + urlencode({"q": termo, "l": cidade})
        elif fonte.lower() == "linkedin":
            url = "https://www.linkedin.com/jobs/search/?" + urlencode({"keywords": termo, "location": cidade})
        else:
            raise ValueError(f"Fonte manual não suportada: {fonte}")
        urls.append((termo, url))
    return urls


def buscar_todas_vagas(filtros: dict) -> list:
    termos = dividir_palavras_chave(filtros["palavra_chave"]) or [""]
    fontes = _montar_fontes(filtros)
    resultados: dict[str, dict] = {}
    if limpar_diagnosticos:
        limpar_diagnosticos()

    paralelo = bool(_cfg("BUSCA_PARALELA", True)) and len(fontes) > 1
    rotulo = ", ".join(t or "(sem palavra-chave)" for t in termos)
    with console.status(f"[cyan]Buscando em {len(fontes)} fonte(s): {escape(rotulo)}...[/cyan]"):
        if paralelo:
            pool = ThreadPoolExecutor(max_workers=len(fontes))
            try:
                futuros = [pool.submit(_buscar_na_fonte, nome, funcao, termos) for nome, funcao in fontes]
                for futuro in as_completed(futuros):
                    resultado = futuro.result()
                    resultados[resultado["nome"]] = resultado
                    _relatar_fonte(resultado, len(termos) > 1)
            except KeyboardInterrupt:
                pool.shutdown(wait=False, cancel_futures=True)
                raise
            else:
                pool.shutdown()
        else:
            for nome, funcao in fontes:
                resultado = _buscar_na_fonte(nome, funcao, termos)
                resultados[nome] = resultado
                _relatar_fonte(resultado, len(termos) > 1)

    # Junta na ordem fixa das fontes, para o resultado não depender de quem terminou antes.
    todas = []
    for nome, _ in fontes:
        todas += resultados[nome]["vagas"]

    # Indeed e LinkedIn proíbem scraping automatizado sem autorização expressa.
    # Em vez de insistir em bloqueios, o AchaVagAI oferece atalhos de busca manual.
    cidade_url = filtros.get("cidade", "Rio de Janeiro")
    if not SITES_ATIVOS.get("indeed", False) or not SITES_ATIVOS.get("linkedin", False):
        console.print("\n[dim]Pesquisas manuais (não entram automaticamente no ranking/Excel):[/dim]")
        if not SITES_ATIVOS.get("indeed", False):
            for termo, url in _montar_urls_busca_manual("indeed", termos, cidade_url):
                console.print(f"  Indeed — {escape(termo)}: [link={url}]abrir pesquisa[/link]")
        if not SITES_ATIVOS.get("linkedin", False):
            for termo, url in _montar_urls_busca_manual("linkedin", termos, cidade_url):
                console.print(f"  LinkedIn — {escape(termo)}: [link={url}]abrir pesquisa[/link]")
    return todas


# ---------------------------------------------------------------------------
# Saída na tela
# ---------------------------------------------------------------------------

def exibir_perfil(perfil) -> None:
    tabela = Table(show_header=False, box=None, padding=(0, 1))
    tabela.add_row("[bold]Nome:[/bold]", escape(perfil.nome) if perfil.nome else "[dim]não identificado[/dim]")
    tabela.add_row("[bold]Cidade:[/bold]", escape(perfil.cidade) if perfil.cidade else "[dim]não identificada[/dim]")
    tabela.add_row("[bold]Bairro:[/bold]", escape(perfil.bairro) if perfil.bairro else "[dim]não identificado[/dim]")
    tabela.add_row(
        "[bold]CNH:[/bold]",
        escape(", ".join(perfil.cnh)) if perfil.cnh else "[dim]não informada no currículo[/dim]",
    )
    tabela.add_row(
        "[bold]Habilidades:[/bold]",
        escape(", ".join(perfil.habilidades)) if perfil.habilidades else "[dim]nenhuma identificada[/dim]",
    )
    tabela.add_row(
        "[bold]Cargo sugerido:[/bold]",
        escape(perfil.cargo_sugerido) if perfil.cargo_sugerido else "[dim]não identificado[/dim]",
    )
    if getattr(perfil, "areas_atuacao", None):
        tabela.add_row("[bold]Áreas comprovadas:[/bold]", escape(", ".join(perfil.areas_atuacao[:5])))
    if getattr(perfil, "cargos_compativeis", None):
        tabela.add_row("[bold]Cargos compatíveis:[/bold]", escape(", ".join(perfil.cargos_compativeis[:6])))
    if perfil.senioridade:
        tabela.add_row("[bold]Senioridade:[/bold]", escape(perfil.senioridade))
    if perfil.resumo:
        tabela.add_row("[bold]Resumo:[/bold]", escape(perfil.resumo))
    titulo = "Currículo analisado" + (" (via IA)" if perfil.extraido_por_ia else " (extração local)")
    console.print(Panel(tabela, title=f"[bold white]{titulo}[/bold white]", border_style="cyan"))
    if perfil.erro_ia:
        console.print(
            "[yellow]A extração por IA do currículo falhou, então usei a extração local acima. "
            f"Motivo: {escape(perfil.erro_ia)}[/yellow]"
        )
    for aviso in getattr(perfil, "avisos_evidencia", []) or []:
        console.print(f"[yellow]Validação de evidência do currículo: {escape(aviso)}[/yellow]")


def exibir_resultados(ranking: list, top_n: int, novas: set[int] | None = None) -> None:
    novas = novas or set()
    tabela = Table(title=f"Top {min(top_n, len(ranking))} vagas mais compatíveis", header_style="bold white on dark_cyan")
    tabela.add_column("Nota", justify="center", width=6)
    tabela.add_column("Vaga", style="bold")
    tabela.add_column("Local", style="magenta")
    tabela.add_column("Fonte", style="yellow")
    tabela.add_column("Motivo (IA)", style="dim italic")

    for vaga, pontuacao, motivo in ranking[:top_n]:
        cor_nota = "green" if pontuacao >= 60 else ("yellow" if pontuacao >= 35 else "red")
        titulo = escape(vaga.titulo or "-")
        if id(vaga) in novas:
            titulo = "[bold green]NOVA[/bold green] " + titulo
        tabela.add_row(
            f"[{cor_nota}]{pontuacao:.0f}[/{cor_nota}]",
            titulo,
            escape(vaga.cidade or "-"),
            escape(vaga.fonte or "-"),
            escape(motivo or "-"),
        )
    console.print(tabela)

    console.print("\n[bold]Links para candidatura:[/bold]")
    for i, (vaga, _pontuacao, _motivo) in enumerate(ranking[:top_n], start=1):
        destino = (vaga.link or "").replace("[", "%5B").replace("]", "%5D")
        console.print(f"  {i}. [link={destino}]{escape(vaga.link or '-')}[/link]")


def exibir_mensagens(mensagens: list) -> None:
    if not mensagens:
        return
    console.print("\n[bold magenta]--- Mensagens de candidatura sugeridas (top vagas) ---[/bold magenta]")
    for vaga, _pontuacao, mensagem in mensagens:
        console.print(Panel(
            escape(mensagem),
            title=f"[bold]{escape(vaga.titulo or '-')}[/bold]",
            border_style="magenta",
            subtitle=escape(vaga.link or ""),
        ))


# ---------------------------------------------------------------------------
# Programa
# ---------------------------------------------------------------------------

def criar_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AchaVagAI - encontra vagas combinando com seu currículo")
    parser.add_argument("curriculo_pdf", nargs="?", default=None,
                        help="Caminho para o arquivo PDF do currículo (se não informado, o script ajuda a encontrar)")
    parser.add_argument("--sem-ia", action="store_true",
                        help="Desativa toda a análise de IA (ranking, extração de perfil e mensagens), mesmo com chave configurada.")
    parser.add_argument("--com-mensagens", action="store_true",
                        help="Gera mensagens de candidatura personalizadas para as melhores vagas (desativado por padrão, usa chamadas extras de IA).")
    parser.add_argument("--top", type=int, default=15, help="Quantas vagas mostrar no resumo final (padrão: 15)")
    parser.add_argument("--top-mensagens", type=int, default=5,
                        help="Para quantas vagas do topo gerar mensagem de candidatura (padrão: 5)")
    parser.add_argument("--nota-minima", type=float, default=None,
                        help=f"Nota mínima (0-100) para uma vaga aparecer nos resultados (padrão: {NOTA_MINIMA_PADRAO} com IA; "
                             "sem IA a nota mínima não é aplicada)")
    parser.add_argument("--sim", action="store_true",
                        help="Não faz perguntas: aceita as sugestões do currículo para o que não for informado por flag.")
    parser.add_argument("--cidade", default=None, help="Cidade da busca (pula a pergunta)")
    parser.add_argument("--bairro", default=None, help="Bairro (pula a pergunta)")
    parser.add_argument("--cargo", default=None, help="Cargo(s) a buscar, separados por vírgula (pula a pergunta)")
    parser.add_argument("--dias", default=None, help="Idade máxima das vagas, em dias (pula a pergunta)")
    parser.add_argument("--saida", default=None, help="Pasta onde salvar a planilha Excel (padrão: pasta atual)")
    parser.add_argument("--sem-cache", action="store_true",
                        help="Ignora as notas guardadas de execuções anteriores e pede tudo de novo à IA.")
    parser.add_argument("--sem-analise-profunda", action="store_true",
                        help="Não abre a página de cada vaga para ler a descrição completa (mais rápido, notas menos precisas).")
    return parser


def _mensagem_scrapers_ausentes() -> None:
    if isinstance(ERRO_SCRAPERS, ModuleNotFoundError) and ERRO_SCRAPERS.name == "scrapers":
        console.print(Panel(
            "A pasta [bold]scrapers/[/bold] (os módulos que buscam em cada site) não está ao lado do "
            "[bold]main.py[/bold].\n\n"
            f"Pasta procurada: {escape(str(BASE_DIR))}\n\n"
            "Coloque a pasta scrapers/ do seu projeto aqui e rode de novo. Se você extraiu a "
            "atualização por cima da pasta antiga, ela deve estar lá. Se perdeu a pasta, reenvie o "
            "projeto completo para ela ser recriada.",
            title="[bold red]Falta a pasta scrapers[/bold red]",
            border_style="red",
        ))
    else:
        console.print(Panel(
            "Não consegui carregar a pasta [bold]scrapers/[/bold]:\n"
            f"{escape(f'{ERRO_SCRAPERS.__class__.__name__}: {ERRO_SCRAPERS}')}\n\n"
            "Se for um pacote faltando, rode: [bold]pip install -r requirements.txt[/bold]",
            title="[bold red]Erro ao carregar os scrapers[/bold red]",
            border_style="red",
        ))


def _executar(args) -> None:
    if _EXECUTADO_COMO_SCRIPT:
        console.print(f"[dim]Módulos carregados em {time.monotonic() - _BOOT_INICIO:.2f}s.[/dim]")
    if args.sem_ia:
        ia.desativar()
    # Começa direto pelo modelo que funcionou da última vez e mostra, uma vez só, por que
    # algum modelo da lista foi deixado de lado.
    ia.usar_arquivo_de_preferencia(BASE_DIR / _cfg("MODELO_PREFERIDO_ARQUIVO", ".achavagai_modelo.json"))
    ia.aviso_callback = lambda texto: console.print(f"  [dim]{escape(texto)}[/dim]")

    console.rule("[bold cyan]ACHAVAGAI[/bold cyan]")

    if ERRO_SCRAPERS is not None:
        _mensagem_scrapers_ausentes()
        sys.exit(1)

    if not args.sem_ia and not args.sim:
        configurar_ia_interativa()

    caminho_pdf = resolver_caminho_pdf(args.curriculo_pdf, automatico=args.sim)

    console.print(f"[dim]Lendo currículo:[/dim] {escape(caminho_pdf)}")
    console.print("[dim]Carregando o leitor de PDF e extraindo o texto do currículo...[/dim]")
    try:
        perfil = analisar_curriculo(caminho_pdf)
    except CurriculoInvalido as erro:
        console.print(f"[red]{escape(str(erro))}[/red]")
        sys.exit(1)
    exibir_perfil(perfil)

    filtros = montar_filtros(perfil, args)

    console.print("\n[bold]--- Buscando vagas ---[/bold]")
    bruto = buscar_todas_vagas(filtros)
    vagas = remover_duplicadas(bruto)
    console.print(
        f"\n[bold]Total de vagas encontradas (após remover duplicadas):[/bold] {len(vagas)}"
        + (f" [dim]({len(bruto) - len(vagas)} repetida(s) removida(s))[/dim]" if len(bruto) > len(vagas) else "")
    )

    if not vagas:
        console.print("[red]Nenhuma vaga encontrada. Tente ajustar a palavra-chave ou verifique sua conexão.[/red]")
        _gerar_painel_vazio(args, filtros, perfil, dividir_palavras_chave(filtros.get("palavra_chave", "")))
        sys.exit(0)

    for vaga in vagas:  # preenche empresa/cidade vazios ANTES de filtrar e de a IA avaliar
        enriquecer_vaga(vaga)

    termos_intencao = dividir_palavras_chave(filtros.get("palavra_chave", ""))
    if termos_intencao:
        vagas, descartadas_por_intencao = filtrar_por_intencao(vagas, termos_intencao)
        if descartadas_por_intencao:
            console.print(
                f"[dim]{len(descartadas_por_intencao)} vaga(s) descartadas por não corresponderem "
                f"ao título ou descrição dos cargos procurados ({escape(', '.join(termos_intencao))}).[/dim]"
            )
            for irrelevante in descartadas_por_intencao[:3]:
                titulo = (irrelevante.titulo or "")[:85]
                console.print(f"[dim]  • {escape(titulo)}[/dim]")

    if not vagas:
        console.print("[yellow]As fontes devolveram anúncios, mas nenhum correspondia aos cargos escolhidos. Revise as palavras-chave ou amplie os sinônimos.[/yellow]")
        _gerar_painel_vazio(args, filtros, perfil, termos_intencao)
        sys.exit(0)

    try:
        dias_maximo = int(filtros["dias"])
    except (ValueError, TypeError):
        dias_maximo = None

    if dias_maximo:
        vagas, removidas_por_idade, sem_data = filtrar_por_data(vagas, dias_maximo)
        if removidas_por_idade:
            console.print(f"[dim]{removidas_por_idade} vaga(s) publicada(s) há mais de {dias_maximo} dias foram descartadas.[/dim]")
        if sem_data:
            console.print(f"[dim]{sem_data} vaga(s) sem data identificável foram mantidas (não dá pra confirmar a idade).[/dim]")

    if not vagas:
        console.print("[red]Nenhuma vaga passou do filtro de data. Tente aumentar o número de dias.[/red]")
        _gerar_painel_vazio(args, filtros, perfil, termos_intencao)
        sys.exit(0)

    if _cfg("FILTRAR_VAGAS_ENCERRADAS", True):
        vagas, encerradas = filtrar_encerradas(vagas)
        if encerradas:
            console.print(
                f"[dim]{len(encerradas)} vaga(s) já encerrada(s) foram descartadas "
                "(a data de comparecimento, entrevista ou prazo escrita na vaga já passou):[/dim]"
            )
            for vaga_antiga, data_limite in encerradas[:3]:
                titulo = vaga_antiga.titulo if len(vaga_antiga.titulo) <= 90 else vaga_antiga.titulo[:87] + "..."
                console.print(f"[dim]  • {escape(titulo)} (data: {data_limite:%d/%m/%Y})[/dim]")
            if len(encerradas) > 3:
                console.print(f"[dim]  ... e mais {len(encerradas) - 3}.[/dim]")
        if not vagas:
            console.print("[red]Todas as vagas encontradas já estavam encerradas. Tente de novo mais tarde ou ajuste a busca.[/red]")
            _gerar_painel_vazio(args, filtros, perfil, termos_intencao)
            sys.exit(0)
            sys.exit(0)

    vagas, removidas_por_regiao = filtrar_por_regiao(vagas)
    if removidas_por_regiao:
        console.print(
            f"[dim]{removidas_por_regiao} vaga(s) de fora do estado {UF_ALVO} foram descartadas "
            "(ajustável em UF_ALVO no config.py).[/dim]"
        )

    if not vagas:
        console.print("[red]Nenhuma vaga passou do filtro de região. Tente ajustar UF_ALVO no config.py.[/red]")
        sys.exit(0)

    usar_filtro_cnh = bool(_cfg("FILTRAR_POR_HABILITACAO", True) and perfil.cnh)
    if usar_filtro_cnh:
        vagas, sem_cnh = filtrar_por_habilitacao(vagas, perfil.cnh)
        _avisar_descartadas_por_cnh(sem_cnh, perfil.cnh)
        if not vagas:
            console.print("[red]Todas as vagas encontradas exigem uma CNH que o currículo não informa.[/red]")
            sys.exit(0)

    def regra_depois_da_leitura(vaga) -> str | None:
        """Regras que podem mudar depois de ler a página da vaga: a descrição completa pode
        revelar a CNH exigida, e a página costuma ter a data de publicação (e o prazo)."""
        if usar_filtro_cnh:
            motivo = motivo_de_eliminacao(vaga, perfil.cnh)
            if motivo:
                return motivo
        if dias_maximo:
            idade = idade_em_dias(getattr(vaga, "data_publicacao", ""))
            if idade is not None and idade > dias_maximo:
                return f"publicada há {idade} dias (o limite é {dias_maximo})"
        if _cfg("FILTRAR_VAGAS_ENCERRADAS", True):
            return motivo_de_encerramento(vaga)
        return None

    # -- ranking ----------------------------------------------------------------
    historico = Historico(
        BASE_DIR / _cfg("HISTORICO_ARQUIVO", ".achavagai_historico.json"),
        validade_dias=_cfg("CACHE_VALIDADE_DIAS", 14),
        usar_cache=not args.sem_cache,
    )
    if historico.aviso:
        console.print(f"[dim]{escape(historico.aviso)}[/dim]")

    provedor = ia.provedor_disponivel()
    nome_provedor = ia.nome_provedor()
    resultado = None
    try:
        if provedor:
            contexto = {
                "cidade": filtros["cidade"], "bairro": filtros["bairro"], "uf": UF_ALVO,
                "cnh": ", ".join(perfil.cnh),
                "termos_busca": termos_intencao,
                "areas_atuacao": getattr(perfil, "areas_atuacao", []),
                "cargos_compativeis": getattr(perfil, "cargos_compativeis", []),
                "experiencias_relevantes": getattr(perfil, "experiencias_relevantes", []),
                "formacao": getattr(perfil, "formacao", []),
                "experiencia_conducao_comprovada": getattr(perfil, "experiencia_conducao_comprovada", False),
                "objetivo_conducao_declarado": getattr(perfil, "objetivo_conducao_declarado", False),
                "experiencia_cpd_comprovada": getattr(perfil, "experiencia_cpd_comprovada", False),
            }
            chave_ctx = chave_do_contexto(perfil.texto_para_ia, contexto, PROMPT_VERSAO)
            ia.aviso_callback = lambda texto: console.print(f"  [dim]{escape(texto)}[/dim]")

            console.print(f"\n[bold magenta]Analisando vagas com IA ({nome_provedor}). Isso pode levar alguns instantes...[/bold magenta]")
            with console.status("[magenta]Avaliando aderência ao currículo...[/magenta]") as status:
                def analise_profunda(vagas_para_ia: list) -> None:
                    if args.sem_analise_profunda or int(_cfg("QUANTIDADE_ANALISE_PROFUNDA", 25)) <= 0:
                        return
                    status.update("[magenta]Lendo a descrição completa das melhores candidatas...[/magenta]")
                    estatisticas = descricoes.enriquecer_descricoes(
                        vagas_para_ia,
                        ao_avancar=lambda feitas, total: status.update(
                            f"[magenta]Lendo a descrição completa das vagas ({feitas}/{total})...[/magenta]"
                        ),
                    )
                    if estatisticas["tentadas"] or estatisticas["ignoradas"]:
                        extra = f", {estatisticas['ignoradas']} de sites pulados de propósito (ex.: LinkedIn)" if estatisticas["ignoradas"] else ""
                        console.print(
                            f"  [dim]Descrição completa obtida para {estatisticas['enriquecidas']} de "
                            f"{estatisticas['tentadas']} vaga(s) tentadas{extra}.[/dim]"
                        )

                def mostrar_lote(feitos: int, total: int) -> None:
                    status.update(f"[magenta]Avaliando aderência ao currículo (lote {min(feitos + 1, total)} de {total})...[/magenta]")

                resultado = ranquear_detalhado(
                    perfil.texto_para_ia,
                    vagas,
                    contexto=contexto,
                    cache_get=lambda vaga: historico.nota_em_cache(vaga, chave_ctx),
                    cache_set=lambda vaga, nota, motivo: historico.guardar_avaliacao(vaga, chave_ctx, nota, motivo),
                    antes_da_ia=analise_profunda,
                    ao_avancar=mostrar_lote,
                    eliminatoria=regra_depois_da_leitura,
                )
            ranking, usou_ia = resultado.ranking, resultado.usou_ia
            # A tela usa o subconjunto avaliado por IA/cache; o Excel recebe todo
            # o universo elegível, com TF-IDF explicitamente identificado no restante.
            ranking_exportacao = resultado.ranking_completo or resultado.ranking
        else:
            console.print(
                "\n[yellow]Nenhuma chave de IA configurada, usando ranking local (TF-IDF), mais simples.[/yellow]\n"
                "[dim]Para uma análise mais profunda e gratuita, crie uma chave em "
                "https://aistudio.google.com/apikey e salve em um arquivo .env como GEMINI_API_KEY=sua-chave.[/dim]"
            )
            ranking, usou_ia = ranquear_por_similaridade(perfil.texto_para_ia, vagas), False
            ranking_exportacao = [
                (vaga, nota, MOTIVO_SEM_IA) for vaga, nota, _motivo in ranking
            ]
    finally:
        ia.aviso_callback = None
        historico.salvar()  # guarda as notas já obtidas, mesmo que algo tenha falhado depois

    if resultado is not None:
        _resumo_da_ia(resultado, nome_provedor)
        _avisar_eliminadas_depois_da_leitura(resultado.eliminadas)

    # -- nota mínima ------------------------------------------------------------
    nota_minima = args.nota_minima
    if nota_minima is None:
        nota_minima = NOTA_MINIMA_PADRAO if usou_ia else 0.0
        if not usou_ia:
            console.print("[dim]Sem notas da IA, a nota mínima não foi aplicada (a pontuação local não é comparável). Use --nota-minima para forçar.[/dim]")

    total_antes_filtro = len(ranking)
    ranking_antes_nota_minima = ranking  # ranking avaliado, antes do corte de nota
    ranking = [item for item in ranking if item[1] >= nota_minima or item[2] == MOTIVO_SEM_IA]
    descartadas = total_antes_filtro - len(ranking)
    if descartadas:
        console.print(f"[dim]{descartadas} vaga(s) abaixo de {nota_minima:.0f}% de aderência foram descartadas (ajuste com --nota-minima).[/dim]")

    # O resumo e o Excel usam o mesmo universo completo. As categorias contam somente
    # vagas com data interpretável; anúncios sem data aparecem numa aba própria.
    contagem_categorias = {"Pesquisa direta": 0, "Compatível com currículo": 0, "Alternativa": 0}
    sem_data_exportacao = 0
    avaliadas_ia_cache = 0
    somente_local = 0
    for vaga_item, _nota_item, motivo_item in ranking_exportacao:
        if idade_em_dias(getattr(vaga_item, "data_publicacao", "")) is None:
            sem_data_exportacao += 1
        else:
            categoria = classificar_vaga(vaga_item, termos_intencao, perfil)
            contagem_categorias[categoria] = contagem_categorias.get(categoria, 0) + 1
        if motivo_item == MOTIVO_SEM_IA:
            somente_local += 1
        else:
            avaliadas_ia_cache += 1
    console.print(
        "[dim]Universo exportado (após filtros obrigatórios): "
        f"{len(ranking_exportacao)} vaga(s). Com data confirmada: "
        f"{contagem_categorias['Pesquisa direta']} pesquisada(s), "
        f"{contagem_categorias['Compatível com currículo']} compatível(is), "
        f"{contagem_categorias['Alternativa']} alternativa(s). "
        f"Sem data confirmada: {sem_data_exportacao}. "
        f"Avaliação: {avaliadas_ia_cache} IA/cache, {somente_local} pontuação local (sem avaliação IA).[/dim]"
    )

    pasta_saida = Path(args.saida) if args.saida else Path(".")
    nome_arquivo = pasta_saida / f"vagas_encontradas_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"

    if not ranking:
        console.print(
            f"[red]Nenhuma vaga passou do filtro de nota mínima ({nota_minima:.0f}%).[/red]\n"
            "[yellow]Isso pode ser normal: se a vaga exige um requisito que seu currículo não "
            "atende (CNH de categoria diferente, curso técnico específico etc.), a IA reprova mesmo que "
            "o título pareça relacionado.[/yellow]\n"
            "[dim]Veja abaixo as vagas com maior nota mesmo assim, para entender o motivo:[/dim]"
        )
        exibir_resultados(ranking_antes_nota_minima, min(5, len(ranking_antes_nota_minima)))
        console.print("\n[dim]A planilha mantém o universo elegível completo; vagas avaliadas abaixo do corte ficam identificadas na coluna 'Situação da nota'.[/dim]")
        salvo = salvar_excel(
            ranking_exportacao, [], nome_arquivo, termos_busca=termos_intencao,
            perfil=perfil, nota_minima=nota_minima,
        )
        console.print(f"\n[bold green]✓[/bold green] Mesmo assim, salvei todo o universo elegível, incluindo vagas com pontuação local: [bold]{escape(str(salvo))}[/bold]")
        novas_html = {id(vaga) for vaga, _, _ in ranking_exportacao if historico.eh_nova(vaga)}
        html_salvo = _gerar_painel_html(
            ranking_exportacao, salvo, novas_html, termos_intencao, perfil, filtros, dias_maximo
        )
        if html_salvo:
            console.print(f"[bold green]✓[/bold green] Painel visual HTML salvo em: [bold]{escape(str(html_salvo))}[/bold]")
        _mostrar_central_resultados(salvo, html_salvo, args)
        sys.exit(0)

    novas = {id(vaga) for vaga, _, _ in ranking_exportacao if historico.eh_nova(vaga)}
    if novas:
        console.print(f"[dim]{len(novas)} vaga(s) nova(s) desde a última execução estão marcadas como NOVA.[/dim]")

    console.print()
    exibir_resultados(ranking, args.top, novas)

    mensagens = []
    if provedor and args.com_mensagens:
        console.print(f"\n[bold magenta]Gerando mensagens de candidatura para as top {args.top_mensagens} vagas...[/bold magenta]")
        with console.status("[magenta]Escrevendo mensagens personalizadas...[/magenta]"):
            mensagens = gerar_mensagens_top(perfil.texto_para_ia, ranking, quantidade=args.top_mensagens)
        exibir_mensagens(mensagens)

    salvo = salvar_excel(
        ranking_exportacao, mensagens, nome_arquivo, novas,
        termos_busca=termos_intencao, perfil=perfil, nota_minima=nota_minima,
    )
    html_salvo = _gerar_painel_html(
        ranking_exportacao, salvo, novas, termos_intencao, perfil, filtros, dias_maximo
    )
    historico.registrar_vistas([vaga for vaga, _, _ in ranking_exportacao])
    historico.salvar()
    _mostrar_central_resultados(salvo, html_salvo, args)


def _avisar_descartadas_por_cnh(descartadas: list, categorias, depois_da_analise: bool = False) -> None:
    """Mostra quantas vagas saíram por exigirem CNH que o currículo não informa, com exemplos."""
    if not descartadas:
        return
    quando = " depois de ler a descrição completa" if depois_da_analise else ""
    console.print(
        f"[dim]{len(descartadas)} vaga(s) descartada(s){quando} por exigirem uma CNH que o seu currículo "
        f"não informa (currículo: {escape(', '.join(categorias))}). Exemplos:[/dim]"
    )
    for vaga, motivo in descartadas[:3]:
        titulo = vaga.titulo if len(vaga.titulo) <= 70 else vaga.titulo[:67] + "..."
        console.print(f"[dim]  • {escape(titulo)}: {escape(motivo)}[/dim]")
    if len(descartadas) > 3:
        console.print(f"[dim]  ... e mais {len(descartadas) - 3}. Para desligar: FILTRAR_POR_HABILITACAO = False no config.py.[/dim]")


def _avisar_eliminadas_depois_da_leitura(eliminadas: list) -> None:
    """Vagas que só foram descartadas depois de ler a página: CNH exigida, data de publicação
    antiga (a lista de resultados não trazia a data) ou prazo vencido."""
    if not eliminadas:
        return
    console.print(
        f"[dim]{len(eliminadas)} vaga(s) descartada(s) depois de ler a página da vaga "
        "(CNH exigida, data de publicação ou prazo). Exemplos:[/dim]"
    )
    for vaga, motivo in eliminadas[:3]:
        titulo = vaga.titulo if len(vaga.titulo) <= 70 else vaga.titulo[:67] + "..."
        console.print(f"[dim]  • {escape(titulo)}: {escape(motivo)}[/dim]")
    if len(eliminadas) > 3:
        console.print(f"[dim]  ... e mais {len(eliminadas) - 3}.[/dim]")


def _resumo_da_ia(resultado, nome_provedor: str | None) -> None:
    """Conta ao usuário o que a IA fez (ou por que não fez)."""
    if resultado.usou_ia:
        partes = []
        if resultado.avaliadas_ia:
            partes.append(f"{resultado.avaliadas_ia} vaga(s) avaliada(s) agora")
        if resultado.do_cache:
            partes.append(f"{resultado.do_cache} reaproveitada(s) do histórico (sem gastar a IA)")
        modelo = f" / {ia.modelo_usado}" if ia.modelo_usado else ""
        console.print(f"[dim]IA ({nome_provedor}{escape(modelo)}): {', '.join(partes)}.[/dim]")
        if resultado.sem_nota_ia:
            console.print(
                f"[yellow]{resultado.sem_nota_ia} vaga(s) ficaram sem nota da IA ({resultado.lotes_com_falha} "
                "lote(s) falharam) e aparecem no fim da lista, com pontuação local.[/yellow]\n"
                f"[dim]Motivo reportado: {escape(resultado.erro or 'motivo desconhecido')}[/dim]"
            )
        if resultado.realinhadas:
            console.print(f"[dim]A IA colocou {resultado.realinhadas} nota(s) na vaga errada; corrigi conferindo o título.[/dim]")
        if getattr(resultado, "evidencias_corrigidas", 0):
            console.print(
                f"[yellow]{resultado.evidencias_corrigidas} justificativa(s) foram corrigidas porque atribuíam experiência em motorista ou CPD sem evidência no currículo.[/yellow]"
            )
        if resultado.sem_correspondencia:
            console.print(
                f"[dim]{resultado.sem_correspondencia} avaliação(ões) da IA não correspondiam a nenhuma vaga do lote "
                "e foram ignoradas (a vaga foi pedida de novo ou ficou sem nota).[/dim]"
            )
        if resultado.fora_do_limite:
            console.print(
                f"[dim]{resultado.fora_do_limite} vaga(s) não foram avaliadas individualmente pela IA "
                f"por causa do limite IA_TOP_ANALISE no config.py. Elas continuam na planilha completa "
                "com pontuação TF-IDF local, identificada como não avaliada pela IA.[/dim]"
            )
    else:
        console.print(
            f"[yellow]A chamada à IA ({nome_provedor}) falhou nesta execução, então usei o ranking local "
            "(TF-IDF), sem justificativa por vaga.[/yellow]\n"
            f"[dim]Motivo reportado: {escape(resultado.erro or ia.ultimo_erro or 'motivo desconhecido')}[/dim]"
        )


def main(argv: list[str] | None = None) -> None:
    args = criar_parser().parse_args(argv)
    try:
        _executar(args)
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrompido pelo usuário.[/yellow]")
        sys.exit(130)


if __name__ == "__main__":
    main()
