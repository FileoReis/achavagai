"""
scrapers/vagas_com.py
Busca vagas no Vagas.com.br — um dos maiores portais de emprego do Brasil.
Diferente do LinkedIn/Indeed, é renderizado no servidor (não depende de
JavaScript), o que torna o scraping mais estável.

A busca é feita por palavra-chave via a URL "/vagas-de-{termo}"; a cidade não
entra diretamente na URL (o site usa filtros por clique, não por querystring
simples), então o filtro de local é aplicado depois, pelo próprio matcher.
"""

import re

from bs4 import BeautifulSoup

from .base import Vaga, nova_sessao, buscar_url
from .utils import slugify

BASE_URL = "https://www.vagas.com.br"
LINK_VAGA_RE = re.compile(r"/vagas/v\d+/")
DATA_RE = re.compile(r"\d{2}/\d{2}/\d{4}")
LOCAL_RE = re.compile(r"([A-Za-zÀ-ÿ\s]+?)\s*/\s*([A-Z]{2})\b")


def buscar_vagas_vagas_com(palavra_chave: str, cidade: str = "", max_resultados: int = 30) -> list[Vaga]:
    if not palavra_chave:
        return []

    sessao = nova_sessao()
    url = f"{BASE_URL}/vagas-de-{slugify(palavra_chave)}"

    resposta = buscar_url(sessao, url)
    if resposta is None:
        return []

    soup = BeautifulSoup(resposta.text, "html.parser")
    vagas: list[Vaga] = []
    links_vistos = set()

    for link_tag in soup.find_all("a", href=True):
        href = link_tag["href"]
        if not LINK_VAGA_RE.search(href) or href in links_vistos:
            continue
        links_vistos.add(href)

        # Sobe na árvore até um container razoável (li/article) para ter contexto.
        container = link_tag
        for _ in range(5):
            if container.parent is None:
                break
            container = container.parent
            if container.name in ("li", "article"):
                break

        linhas = [l.strip() for l in container.get_text("\n").split("\n") if l.strip()]
        titulo = link_tag.get_text(strip=True) or (linhas[0] if linhas else "")

        empresa = ""
        if len(linhas) >= 2 and linhas[1].lower() != "confidencial":
            empresa = linhas[1]

        texto_completo = " ".join(linhas)
        match_local = LOCAL_RE.search(texto_completo)
        local = f"{match_local.group(1).strip()} / {match_local.group(2)}" if match_local else ""

        match_data = DATA_RE.search(texto_completo)
        data_publicacao = match_data.group(0) if match_data else ""

        descricao_candidatas = [
            l for l in linhas[2:] if len(l) > 40 and not DATA_RE.search(l) and not LOCAL_RE.fullmatch(l)
        ]
        descricao = descricao_candidatas[0][:500] if descricao_candidatas else ""

        link_absoluto = href if href.startswith("http") else BASE_URL + href

        vagas.append(
            Vaga(
                titulo=titulo,
                empresa=empresa,
                cidade=local,
                data_publicacao=data_publicacao,
                link=link_absoluto,
                descricao=descricao,
                fonte="Vagas.com",
            )
        )

        if len(vagas) >= max_resultados:
            break

    return vagas
