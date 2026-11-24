"""Consulta a Jooble REST API para o mercado brasileiro (chave própria necessária)."""
from __future__ import annotations

import os
import requests

from .base import Vaga
from .diagnostico import registrar_http, registrar_parser


def buscar_vagas_jooble(palavra_chave: str, cidade: str = "", max_resultados: int = 30) -> list[Vaga]:
    chave = (os.getenv("JOOBLE_API_KEY") or "").strip().strip('"').strip("'")
    if not chave:
        registrar_http("https://br.jooble.org/api/[CHAVE OCULTA]", None,
                       erro="JOOBLE_API_KEY não configurada", fonte="Jooble")
        return []
    url_real = f"https://br.jooble.org/api/{chave}"
    url_segura = "https://br.jooble.org/api/[CHAVE OCULTA]"
    payload = {
        "keywords": palavra_chave,
        "location": cidade or "Rio de Janeiro",
        "radius": "80",
        "page": "1",
        "ResultOnPage": min(30, max_resultados),
        "companysearch": "false",
    }
    try:
        resposta = requests.post(url_real, json=payload, timeout=25,
                                 headers={"Accept": "application/json", "Content-Type": "application/json"})
        registrar_http(url_segura, resposta.status_code, resposta.text[:30000], fonte="Jooble",
                       content_type=resposta.headers.get("Content-Type", ""))
        resposta.raise_for_status()
        dados = resposta.json()
    except (requests.RequestException, ValueError) as erro:
        registrar_http(url_segura, getattr(getattr(erro, "response", None), "status_code", None),
                       erro=f"{erro.__class__.__name__}: {str(erro)[:160]}", fonte="Jooble")
        return []

    itens = dados.get("jobs", []) if isinstance(dados, dict) else []
    vagas: list[Vaga] = []
    if isinstance(itens, list):
        for item in itens:
            if not isinstance(item, dict):
                continue
            titulo = str(item.get("title") or "").strip()
            link = str(item.get("link") or "").strip()
            if not titulo or not link:
                continue
            vagas.append(Vaga(
                titulo=titulo, empresa=str(item.get("company") or ""),
                cidade=str(item.get("location") or ""),
                data_publicacao=str(item.get("updated") or ""), link=link,
                descricao=str(item.get("snippet") or "")[:3000], fonte="Jooble",
            ))
            if len(vagas) >= max_resultados:
                break
    registrar_parser(url_segura, len(vagas), "API REST Jooble", fonte="Jooble")
    return vagas
