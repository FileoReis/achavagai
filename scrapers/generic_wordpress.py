"""
scrapers/generic_wordpress.py

Vários portais regionais de emprego (RioVagas, Rio Emprega, Rio Empregos, VagasRio
etc.) são construídos em WordPress e funcionam como um blog: cada vaga é um "post".
Isso significa que, diferente do LinkedIn/Indeed, eles não têm filtros estruturados
de cidade/bairro/data — a busca é feita pela caixa de pesquisa do site (parâmetro
"?s=" do WordPress) e a "vaga" é, na prática, o post do blog.

Este módulo é GENÉRICO: você registra um site em SITES_WORDPRESS (nome + URL base)
e ele tenta buscar e extrair os posts automaticamente. Como o HTML varia entre temas
do WordPress, o parser usa algumas tentativas (article, .post, .entry) para aumentar
a chance de funcionar em vários sites sem configuração adicional. Se um site em
específico não funcionar bem, ajuste os seletores para ele.

Para adicionar um novo site regional, basta incluir uma nova entrada no dicionário
SITES_WORDPRESS abaixo, com a URL base do site.
"""

import re
from urllib.parse import urlencode, urljoin

from bs4 import BeautifulSoup

from .base import Vaga, nova_sessao, buscar_url
from .adaptive import extrair_vagas_adaptativo
from .diagnostico import registrar_parser, registrar_schema_inesperado
from intencao_busca import compilar_intencoes, vaga_corresponde

# nome de exibição -> URL base do site
SITES_WORDPRESS = {
    "RioVagas": "https://riovagas.com.br",
    "Rio Emprega": "https://rioemprega.com.br",
    "Rio Empregos": "https://rioempregos.com.br",
    "VagasRio": "https://www.vagasrio.com.br",
}

# Alguns desses portais mostram a data por extenso ("7 de February de 2025" — sim,
# misturando português com nome de mês em inglês, aparentemente um bug do próprio
# site) em vez de um atributo datetime="" utilizável diretamente. Este mapa cobre
# nomes de mês em português E em inglês para dar conta dos dois casos.
MESES = {
    "janeiro": 1, "january": 1,
    "fevereiro": 2, "february": 2,
    "marco": 3, "março": 3, "march": 3,
    "abril": 4, "april": 4,
    "maio": 5, "may": 5,
    "junho": 6, "june": 6,
    "julho": 7, "july": 7,
    "agosto": 8, "august": 8,
    "setembro": 9, "september": 9,
    "outubro": 10, "october": 10,
    "novembro": 11, "november": 11,
    "dezembro": 12, "december": 12,
}
DATA_EXTENSO_RE = re.compile(r"(\d{1,2})\s+de\s+(\w+)\s+de\s+(\d{4})", re.IGNORECASE)

# Nas páginas de LISTAGEM/busca (diferente da página de detalhe de cada vaga), esses
# portais costumam mostrar a data em formato numérico brasileiro, ex.: "16/08/2026 –
# 08:27". Como é a página de listagem que o scraper realmente lê, esse é o formato
# que mais aparece na prática — o padrão por extenso acima cobre principalmente as
# páginas de detalhe (quando o texto completo do post inclui essa informação).
DATA_NUMERICA_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")


def _extrair_data_do_texto(texto: str) -> str:
    """Tenta achar uma data no texto, em qualquer um dos formatos usados por esses
    portais — por extenso (ex.: "7 de February de 2025") ou numérico brasileiro
    (ex.: "16/08/2026 – 08:27") — e converte para ISO (AAAA-MM-DD). Retorna "" se
    não encontrar nada reconhecível."""
    match_extenso = DATA_EXTENSO_RE.search(texto)
    if match_extenso:
        dia, mes_nome, ano = match_extenso.groups()
        mes = MESES.get(mes_nome.lower())
        if mes:
            try:
                return f"{int(ano):04d}-{mes:02d}-{int(dia):02d}"
            except ValueError:
                pass

    match_numerico = DATA_NUMERICA_RE.search(texto)
    if match_numerico:
        dia, mes, ano = match_numerico.groups()
        try:
            dia, mes, ano = int(dia), int(mes), int(ano)
            if 1 <= dia <= 31 and 1 <= mes <= 12:
                return f"{ano:04d}-{mes:02d}-{dia:02d}"
        except ValueError:
            pass

    return ""


def _extrair_posts(soup: BeautifulSoup) -> list:
    """Tenta localizar os elementos de post usando seletores comuns de temas WordPress."""
    for seletor in ("article", "div.post", "div.entry", "div.td-module-container"):
        tag, *classe = seletor.split(".")
        posts = soup.find_all(tag, class_=classe[0]) if classe else soup.find_all(tag)
        if posts:
            return posts
    return []


def _extrair_data(post, data_tag) -> str:
    """Extrai a data de publicação tentando, em ordem: (1) atributo datetime="" de
    uma tag <time>, (2) o texto dessa tag por extenso, (3) uma busca por data por
    extenso em todo o texto do post (cobre casos sem tag <time> nenhuma)."""
    if data_tag and data_tag.has_attr("datetime"):
        return data_tag["datetime"]
    if data_tag:
        encontrada = _extrair_data_do_texto(data_tag.get_text(" ", strip=True))
        if encontrada:
            return encontrada
    return _extrair_data_do_texto(post.get_text(" ", strip=True))


def _relevante(vaga: Vaga, palavra_chave: str) -> bool:
    """Filtro de segurança local: confirma que o termo buscado realmente aparece
    no título ou na descrição da vaga. Necessário porque a busca nativa ("?s=")
    de alguns desses portais não é confiável — em teste, o VagasRio chegou a
    ignorar completamente o termo pesquisado e devolver sempre os posts mais
    recentes do site inteiro, independente da palavra buscada (confirmado
    comparando os resultados de uma busca real com uma busca por um termo
    inexistente — ambos retornaram o mesmo conteúdo). Sem esse filtro, o
    ranking final acaba avaliando vagas de áreas completamente diferentes."""
    return vaga_corresponde(vaga, compilar_intencoes([palavra_chave]))


def _texto_renderizado_wp(valor) -> str:
    if isinstance(valor, dict):
        valor = valor.get("rendered", "")
    if not valor:
        return ""
    return BeautifulSoup(str(valor), "html.parser").get_text(" ", strip=True)


def _buscar_rest_vagasrio(sessao, url_base: str, palavra_chave: str) -> list[Vaga]:
    """Fallback público do WordPress REST API, sem autenticação ou evasão.

    Só é usado no VagasRio quando a busca HTML não fornece vagas relevantes.
    O endpoint padrão /wp-json/wp/v2/posts pode estar desativado; nesse caso o
    diagnóstico registra a resposta e a aplicação continua com as outras fontes.
    """
    endpoint = urljoin(url_base.rstrip("/") + "/", "wp-json/wp/v2/posts")
    parametros = {
        "search": palavra_chave,
        "per_page": 30,
        "page": 1,
        "_fields": "date,link,title,excerpt",
    }
    resposta = buscar_url(sessao, endpoint, diagnostico_nome="VagasRio", params=parametros)
    if resposta is None:
        return []
    try:
        dados = resposta.json()
    except (ValueError,):
        registrar_parser(endpoint, 0, "resposta não JSON do WordPress REST API",
                         resposta.text, "VagasRio",
                         content_type=resposta.headers.get("Content-Type", ""),
                         url_final=getattr(resposta, "url", "") or endpoint)
        return []

    if not isinstance(dados, list):
        registrar_schema_inesperado(
            "VagasRio", endpoint, dados,
            "WordPress REST API respondeu JSON, mas não retornou uma lista de posts",
        )
        return []

    vagas: list[Vaga] = []
    for post in dados:
        if not isinstance(post, dict):
            continue
        titulo = _texto_renderizado_wp(post.get("title"))
        link = str(post.get("link") or "").strip()
        descricao = _texto_renderizado_wp(post.get("excerpt"))
        if not titulo or not link:
            continue
        vaga = Vaga(
            titulo=titulo,
            empresa="",
            cidade="",
            data_publicacao=str(post.get("date") or ""),
            link=link,
            descricao=descricao[:2500],
            fonte="VagasRio",
        )
        if _relevante(vaga, palavra_chave):
            vagas.append(vaga)

    registrar_parser(
        endpoint, len(vagas), "WordPress REST API pública (posts)", "", "VagasRio",
        content_type=resposta.headers.get("Content-Type", ""),
        url_final=getattr(resposta, "url", "") or endpoint,
    )
    return vagas


def buscar_vagas_wordpress(nome_site: str, url_base: str, palavra_chave: str) -> list[Vaga]:
    sessao = nova_sessao()
    vagas: list[Vaga] = []

    url_busca = f"{url_base.rstrip('/')}/?{urlencode({'s': palavra_chave})}"
    resposta = buscar_url(sessao, url_busca, diagnostico_nome=nome_site)
    if resposta is None:
        return vagas

    soup = BeautifulSoup(resposta.text, "html.parser")
    posts = _extrair_posts(soup)
    for post in posts:
        link_tag = post.find("a", href=True)
        titulo_tag = post.find(["h1", "h2", "h3"])
        data_tag = post.find("time")
        resumo_tag = post.find("p")
        if not link_tag:
            continue
        vagas.append(
            Vaga(
                titulo=titulo_tag.get_text(" ", strip=True) if titulo_tag else link_tag.get_text(" ", strip=True),
                empresa="",
                cidade="",
                data_publicacao=_extrair_data(post, data_tag),
                link=urljoin(url_base.rstrip("/") + "/", link_tag["href"]),
                descricao=resumo_tag.get_text(" ", strip=True) if resumo_tag else "",
                fonte=nome_site,
            )
        )

    vagas_relevantes = [v for v in vagas if _relevante(v, palavra_chave)]
    if vagas_relevantes:
        registrar_parser(url_busca, len(vagas_relevantes), "cartões WordPress (article/post/entry)",
                         resposta.text, nome_site,
                         content_type=resposta.headers.get("Content-Type", ""),
                         url_final=getattr(resposta, "url", "") or url_busca)
        return vagas_relevantes

    # Mesmo quando o HTML contém uma listagem, se nenhum post corresponde ao
    # termo, isso é um resultado vazio da busca local, não uma mudança de layout.
    if posts:
        estrategia = "cartões WordPress reconhecidos; nenhum correspondente ao termo"
    else:
        estrategia = "busca WordPress sem cartões reconhecidos"
    registrar_parser(url_busca, 0, estrategia, resposta.text, nome_site,
                     content_type=resposta.headers.get("Content-Type", ""),
                     url_final=getattr(resposta, "url", "") or url_busca)

    # O parser semântico ainda pode reconhecer cartões mesmo quando as classes
    # do tema WordPress mudaram. Tentamos antes de consultar uma rota alternativa.
    alternativas, estrategia_adaptativa = extrair_vagas_adaptativo(
        resposta.text, nome_site, getattr(resposta, "url", "") or url_base, 60
    )
    alternativas = [v for v in alternativas if _relevante(v, palavra_chave)]
    if alternativas:
        registrar_parser(url_busca, len(alternativas), estrategia_adaptativa,
                         resposta.text, nome_site,
                         content_type=resposta.headers.get("Content-Type", ""),
                         url_final=getattr(resposta, "url", "") or url_busca)
        return alternativas

    # No VagasRio a busca nativa foi observada retornando search-no-results.
    # Fazemos uma única consulta complementar ao endpoint público padrão do WP.
    if nome_site == "VagasRio":
        import config
        if getattr(config, "VAGASRIO_USAR_REST_FALLBACK", True):
            return _buscar_rest_vagasrio(sessao, url_base, palavra_chave)
    return []


def buscar_vagas_todos_wordpress(palavra_chave: str, sites_ativos: dict[str, bool]) -> list[Vaga]:
    """Busca em todos os sites WordPress cadastrados e habilitados em config.SITES_ATIVOS."""
    todas_vagas: list[Vaga] = []
    mapa_chave = {
        "riovagas": "RioVagas",
        "rioemprega": "Rio Emprega",
        "rioempregos": "Rio Empregos",
        "vagasrio": "VagasRio",
    }
    for chave_config, nome_site in mapa_chave.items():
        if not sites_ativos.get(chave_config, False):
            continue
        url_base = SITES_WORDPRESS[nome_site]
        todas_vagas.extend(buscar_vagas_wordpress(nome_site, url_base, palavra_chave))

    return todas_vagas
