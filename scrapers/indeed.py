"""
scrapers/indeed.py
Busca vagas no Indeed Brasil (br.indeed.com) a partir da página pública de resultados.

Assim como outros scrapers, depende da estrutura HTML atual do site, que pode mudar.
Se o Indeed passar a exigir captcha/login para ver resultados, este scraper pode
retornar poucos ou nenhum resultado — nesse caso, use a busca manual no site.
"""

from bs4 import BeautifulSoup

from .base import Vaga, nova_sessao, buscar_url

BASE_URL = "https://br.indeed.com/jobs"


def buscar_vagas_indeed(palavra_chave: str, cidade: str, max_paginas: int = 2) -> list[Vaga]:
    sessao = nova_sessao()
    vagas: list[Vaga] = []

    for pagina in range(max_paginas):
        params = {"q": palavra_chave, "l": cidade, "start": pagina * 10}
        resposta = buscar_url(sessao, BASE_URL, params=params)
        if resposta is None:
            break

        soup = BeautifulSoup(resposta.text, "html.parser")
        cards = soup.find_all("div", class_="job_seen_beacon") or soup.find_all("td", class_="resultContent")
        if not cards:
            break

        for card in cards:
            titulo_tag = card.find("h2") or card.find("a", class_="jcs-JobTitle")
            empresa_tag = card.find("span", {"data-testid": "company-name"})
            local_tag = card.find("div", {"data-testid": "text-location"})
            link_tag = card.find("a", href=True)

            if not (titulo_tag and link_tag):
                continue

            link = link_tag["href"]
            if link.startswith("/"):
                link = "https://br.indeed.com" + link

            vagas.append(
                Vaga(
                    titulo=titulo_tag.get_text(strip=True),
                    empresa=empresa_tag.get_text(strip=True) if empresa_tag else "",
                    cidade=local_tag.get_text(strip=True) if local_tag else cidade,
                    data_publicacao="",  # Indeed mostra texto relativo ("há 2 dias"); tratar se necessário
                    link=link,
                    descricao="",
                    fonte="Indeed",
                )
            )

    return vagas
