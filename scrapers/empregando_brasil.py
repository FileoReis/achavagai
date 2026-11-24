"""Feed XML público de vagas ativas do Empregando Brasil."""
from __future__ import annotations

import re
import threading
import time
import xml.etree.ElementTree as ET
from html import unescape
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from .base import Vaga
from .diagnostico import registrar_http, registrar_parser
from intencao_busca import compilar_intencoes, vaga_corresponde

FEED_URL = "https://empregandobrasil.com.br/feeds/partners/jobs.xml"
_LOCK = threading.Lock()
_CACHE: tuple[float, list[dict]] | None = None


def _texto(node) -> str:
    if node is None:
        return ""
    bruto = "".join(node.itertext()) if hasattr(node, "itertext") else str(node)
    return re.sub(r"\s+", " ", BeautifulSoup(unescape(bruto), "html.parser").get_text(" ", strip=True)).strip()


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _filhos(item) -> dict[str, str]:
    resultado = {}
    for filho in list(item):
        resultado[_local_name(filho.tag)] = _texto(filho)
    return resultado


def _carregar_feed() -> list[dict]:
    global _CACHE
    agora = time.monotonic()
    with _LOCK:
        if _CACHE and agora - _CACHE[0] < 12 * 60 * 60:
            return list(_CACHE[1])
    try:
        resposta = requests.get(FEED_URL, timeout=25, headers={"Accept": "application/xml,text/xml"})
        registrar_http(FEED_URL, resposta.status_code, resposta.text[:30000], fonte="Empregando Brasil",
                       content_type=resposta.headers.get("Content-Type", ""))
        resposta.raise_for_status()
        raiz = ET.fromstring(resposta.content)
        itens = []
        for elem in raiz.iter():
            if _local_name(elem.tag) in {"job", "vaga", "item"}:
                campo = _filhos(elem)
                if campo.get("title") or campo.get("titulo"):
                    itens.append(campo)
        with _LOCK:
            _CACHE = (time.monotonic(), itens)
        registrar_parser(FEED_URL, len(itens), "feed XML parceiro", resposta.text, "Empregando Brasil")
        return itens
    except (requests.RequestException, ET.ParseError) as erro:
        registrar_http(FEED_URL, getattr(getattr(erro, "response", None), "status_code", None),
                       erro=f"{erro.__class__.__name__}: {str(erro)[:160]}", fonte="Empregando Brasil")
        return []


def _corresponde(vaga: Vaga, termo: str) -> bool:
    return vaga_corresponde(vaga, compilar_intencoes([termo]))


def buscar_vagas_empregando_brasil(palavra_chave: str, cidade: str = "", max_resultados: int = 40) -> list[Vaga]:
    itens = _carregar_feed()
    vagas = []
    for item in itens:
        titulo = item.get("title") or item.get("titulo") or ""
        link = item.get("url") or item.get("link") or ""
        if not titulo or not link:
            continue
        local = ", ".join(x for x in (item.get("city") or item.get("cidade"), item.get("state") or item.get("uf")) if x)
        vaga = Vaga(
            titulo=titulo, empresa=item.get("company") or item.get("empresa") or "",
            cidade=local, data_publicacao=item.get("published") or item.get("created") or item.get("data") or "",
            link=urljoin(FEED_URL, link), descricao=(item.get("description") or item.get("descricao") or "")[:4000],
            fonte="Empregando Brasil",
        )
        if _corresponde(vaga, palavra_chave):
            vagas.append(vaga)
        if len(vagas) >= max_resultados:
            break
    # Feed cacheado pode não ter originado requisição nesta chamada; ainda registra parser.
    registrar_parser(FEED_URL, len(vagas), "feed XML ativo (cache de 12h)", fonte="Empregando Brasil")
    return vagas
