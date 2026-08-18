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

from bs4 import BeautifulSoup

from .base import Vaga, nova_sessao, buscar_url

# nome de exibição -> URL base do site
SITES_WORDPRESS = {
    "RioVagas": "https://riovagas.com.br",
    "Rio Emprega": "https://rioemprega.com.br",
    "Rio Empregos": "https://rioempregos.com.br",
    "VagasRio": "https://vagasrio.com.br",
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


def _extrair_data_do_texto(texto: str) -> str:
    """Tenta achar uma data por extenso no texto (ex.: "7 de February de 2025")
    e converte para ISO (AAAA-MM-DD). Retorna "" se não encontrar nada reconhecível."""
    match = DATA_EXTENSO_RE.search(texto)
    if not match:
        return ""
    dia, mes_nome, ano = match.groups()
    mes = MESES.get(mes_nome.lower())
    if not mes:
        return ""
    try:
        return f"{int(ano):04d}-{mes:02d}-{int(dia):02d}"
    except ValueError:
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


def buscar_vagas_wordpress(nome_site: str, url_base: str, palavra_chave: str) -> list[Vaga]:
    sessao = nova_sessao()
    vagas: list[Vaga] = []

    url_busca = f"{url_base}/?s={palavra_chave.replace(' ', '+')}"
    resposta = buscar_url(sessao, url_busca)
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
                titulo=titulo_tag.get_text(strip=True) if titulo_tag else link_tag.get_text(strip=True),
                empresa="",  # geralmente não estruturado nesses sites
                cidade="",   # idem — normalmente vem só no texto da vaga
                data_publicacao=_extrair_data(post, data_tag),
                link=link_tag["href"],
                descricao=resumo_tag.get_text(strip=True) if resumo_tag else "",
                fonte=nome_site,
            )
        )

    return vagas


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
