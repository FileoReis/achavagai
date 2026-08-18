"""
scrapers/linkedin.py

IMPORTANTE (leia antes de usar):
O LinkedIn não oferece uma API pública gratuita de busca de vagas para terceiros,
e os Termos de Uso do LinkedIn proíbem scraping automatizado da plataforma.
Este módulo usa o endpoint público "jobs-guest" (o mesmo que carrega os resultados
de busca de vagas para quem visita o site sem estar logado). Ele é usado por vários
projetos open-source, mas pode:
  - parar de funcionar a qualquer momento (o LinkedIn muda o HTML com frequência);
  - resultar em bloqueio temporário do seu IP se usado com muita frequência;
  - violar os Termos de Uso do LinkedIn.
Use por sua conta e risco, com moderação (poucas requisições, com pausas),
e considere usar preferencialmente a candidatura manual pelo site/app oficial
ou, se disponível para você, a API oficial de parceiros do LinkedIn.
"""

from bs4 import BeautifulSoup

from .base import Vaga, nova_sessao, buscar_url

BASE_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"


def buscar_vagas_linkedin(palavra_chave: str, cidade: str, max_paginas: int = 2) -> list[Vaga]:
    """Busca vagas públicas no LinkedIn para a palavra-chave e cidade informadas.

    Retorna lista vazia (sem quebrar o restante do script) se o LinkedIn
    bloquear ou mudar a estrutura da página.
    """
    sessao = nova_sessao()
    vagas: list[Vaga] = []

    for pagina in range(max_paginas):
        params = {
            "keywords": palavra_chave,
            "location": cidade,
            "start": pagina * 25,
        }
        resposta = buscar_url(sessao, BASE_URL, params=params)
        if resposta is None:
            break

        soup = BeautifulSoup(resposta.text, "html.parser")
        cards = soup.find_all("li")
        if not cards:
            break

        for card in cards:
            titulo_tag = card.find("h3", class_="base-search-card__title")
            empresa_tag = card.find("h4", class_="base-search-card__subtitle")
            local_tag = card.find("span", class_="job-search-card__location")
            data_tag = card.find("time")
            link_tag = card.find("a", class_="base-card__full-link")

            if not (titulo_tag and link_tag):
                continue

            vagas.append(
                Vaga(
                    titulo=titulo_tag.get_text(strip=True),
                    empresa=empresa_tag.get_text(strip=True) if empresa_tag else "",
                    cidade=local_tag.get_text(strip=True) if local_tag else cidade,
                    data_publicacao=data_tag["datetime"] if data_tag and data_tag.has_attr("datetime") else "",
                    link=link_tag["href"].split("?")[0],
                    descricao="",  # descrição completa exigiria abrir cada vaga individualmente
                    fonte="LinkedIn",
                )
            )

    return vagas
