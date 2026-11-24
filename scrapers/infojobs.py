"""
scrapers/infojobs.py
Busca vagas no InfoJobs Brasil — renderizado no servidor, permite busca
combinada de cargo + cidade diretamente na URL:
  https://www.infojobs.com.br/vagas-de-{cargo}-em-{cidade},-{uf}.aspx
"""

import re

from bs4 import BeautifulSoup

from .base import Vaga, nova_sessao, buscar_url
from .adaptive import extrair_vagas_adaptativo, mesclar_vagas
from .diagnostico import registrar_parser
from .utils import slugify, slugify_cidade_sem_conectores
import config

BASE_URL = "https://www.infojobs.com.br"
LINK_VAGA_RE = re.compile(r"/vaga-de-.+?__\d+\.aspx")
LOCAL_RE = re.compile(r"([A-Za-zÀ-ÿ\s]+-\s*[A-Z]{2})\s*Km de você")


def _montar_url(palavra_chave: str, cidade: str) -> str:
    slug_termo = slugify(palavra_chave) if palavra_chave else "emprego"
    if cidade:
        slug_cidade = slugify_cidade_sem_conectores(cidade)
        uf = re.sub(r"[^a-z]", "", str(getattr(config, "UF_ALVO", "") or "").lower())
        sufixo_uf = f",-{uf}" if uf else ""
        return f"{BASE_URL}/vagas-de-{slug_termo}-em-{slug_cidade}{sufixo_uf}.aspx"
    return f"{BASE_URL}/vagas-de-{slug_termo}.aspx"


def buscar_vagas_infojobs(palavra_chave: str, cidade: str = "", max_resultados: int = 30) -> list[Vaga]:
    sessao = nova_sessao()
    url = _montar_url(palavra_chave, cidade)

    resposta = buscar_url(sessao, url, diagnostico_nome="InfoJobs")
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

        container = link_tag
        for _ in range(5):
            if container.parent is None:
                break
            container = container.parent
            if container.name in ("li", "article", "div") and len(container.get_text(strip=True)) > 60:
                break

        linhas = [l.strip() for l in container.get_text("\n").split("\n") if l.strip()]
        titulo = link_tag.get_text(strip=True) or (linhas[0] if linhas else "")

        empresa = ""
        empresa_tag = container.find("a", href=re.compile(r"/empresa-|^https://www\.infojobs\.com\.br/[a-z0-9-]+$"))
        if empresa_tag is not None and empresa_tag is not link_tag:
            empresa = empresa_tag.get_text(strip=True)

        texto_completo = " ".join(linhas)
        match_local = LOCAL_RE.search(texto_completo)
        local = match_local.group(1).strip() if match_local else cidade

        descricao_candidatas = [l for l in linhas if len(l) > 40 and "Km de você" not in l]
        descricao = descricao_candidatas[-1][:500] if descricao_candidatas else ""

        link_absoluto = href if href.startswith("http") else BASE_URL + href

        vagas.append(
            Vaga(
                titulo=titulo,
                empresa=empresa,
                cidade=local,
                data_publicacao="",
                link=link_absoluto,
                descricao=descricao,
                fonte="InfoJobs",
            )
        )

        if len(vagas) >= max_resultados:
            break

    alternativas, estrategia_adaptativa = extrair_vagas_adaptativo(resposta.text, "InfoJobs", BASE_URL, max_resultados)
    vagas = mesclar_vagas(vagas, alternativas, max_resultados)
    estrategia = "seletores conhecidos InfoJobs" if not estrategia_adaptativa.startswith("nenhuma") else estrategia_adaptativa
    if alternativas:
        estrategia += " + " + estrategia_adaptativa
    registrar_parser(url, len(vagas), estrategia, resposta.text, "InfoJobs")
    return vagas
