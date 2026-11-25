"""Consulta paginada à Jooble REST API brasileira.

A API usa uma chave por país e o plano gratuito documenta 100 requisições/dia
por chave. Por isso a paginação tem limite explícito e configurável.
"""
from __future__ import annotations

import os

import requests

from .base import Vaga
from .diagnostico import registrar_http, registrar_parser, registrar_schema_inesperado
from filtros import normalizar_link

URL_BASE = "https://br.jooble.org/api/"
URL_DIAGNOSTICO = "https://br.jooble.org/api/[CHAVE OCULTA]"


def _chave_item(item: dict) -> str:
    identificador = item.get("id")
    if identificador not in (None, ""):
        return f"id:{identificador}"
    link = str(item.get("link") or "").strip()
    if not link:
        return ""
    return normalizar_link(link)


def buscar_vagas_jooble(
    palavra_chave: str,
    cidade: str = "",
    max_resultados: int | None = None,
    max_paginas: int | None = None,
) -> list[Vaga]:
    """Busca várias páginas, parando ao atingir totalCount, página curta ou limite.

    ``max_resultados`` e ``max_paginas`` podem ser passados em testes/uso avançado.
    Sem argumentos, os limites vêm de config.py.
    """
    import config

    chave = (os.getenv("JOOBLE_API_KEY") or "").strip().strip('"').strip("'")
    if not chave:
        registrar_http(URL_DIAGNOSTICO, None, erro="JOOBLE_API_KEY não configurada", fonte="Jooble")
        return []

    tamanho_pagina = max(1, min(30, int(getattr(config, "JOOBLE_RESULTADOS_POR_PAGINA", 30))))
    limite_paginas = max(1, int(max_paginas or getattr(config, "JOOBLE_MAX_PAGINAS_POR_TERMO", 3)))
    limite_resultados = max(1, int(max_resultados or (tamanho_pagina * limite_paginas)))
    limite_paginas = min(limite_paginas, (limite_resultados + tamanho_pagina - 1) // tamanho_pagina)

    url_real = URL_BASE + chave
    vagas: list[Vaga] = []
    vistos: set[str] = set()
    total_informado: int | None = None
    sessao = requests.Session()
    sessao.headers.update({
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "AchaVagAI/1.0 (job-search client)",
    })

    for pagina in range(1, limite_paginas + 1):
        payload = {
            "keywords": palavra_chave,
            "location": cidade or "Rio de Janeiro",
            "radius": "80",
            "page": pagina,
            "ResultOnPage": tamanho_pagina,
            "companysearch": False,
        }
        try:
            resposta = sessao.post(url_real, json=payload, timeout=25)
            registrar_http(URL_DIAGNOSTICO, resposta.status_code, resposta.text[:30000],
                           fonte="Jooble", content_type=resposta.headers.get("Content-Type", ""))
            resposta.raise_for_status()
            dados = resposta.json()
        except requests.exceptions.JSONDecodeError:
            registrar_schema_inesperado("Jooble", URL_DIAGNOSTICO, {},
                                        "A API respondeu, mas o corpo não é JSON válido")
            break
        except requests.HTTPError:
            # O status e a URL sanitizada já foram registrados antes de raise_for_status.
            # Não usar str(erro): requests inclui a URL real, que contém a chave.
            break
        except requests.RequestException as erro:
            registrar_http(URL_DIAGNOSTICO, None,
                           erro=f"{erro.__class__.__name__}: falha de comunicação com a API Jooble",
                           fonte="Jooble")
            break
        except ValueError:
            registrar_schema_inesperado("Jooble", URL_DIAGNOSTICO, {},
                                        "A API respondeu, mas o corpo não é JSON válido")
            break

        if not isinstance(dados, dict) or not isinstance(dados.get("jobs", []), list):
            registrar_schema_inesperado("Jooble", URL_DIAGNOSTICO, dados,
                                        "Formato JSON inesperado: campo jobs ausente ou inválido")
            break

        try:
            total_informado = int(dados.get("totalCount")) if dados.get("totalCount") is not None else total_informado
        except (TypeError, ValueError):
            total_informado = None

        itens = dados.get("jobs", [])
        novos_nesta_pagina = 0
        for item in itens:
            if not isinstance(item, dict):
                continue
            titulo = str(item.get("title") or "").strip()
            link = str(item.get("link") or "").strip()
            if not titulo or not link:
                continue
            chave_item = _chave_item(item) or f"link:{link}"
            if chave_item in vistos:
                continue
            vistos.add(chave_item)
            vagas.append(Vaga(
                titulo=titulo,
                empresa=str(item.get("company") or ""),
                cidade=str(item.get("location") or ""),
                data_publicacao=str(item.get("updated") or ""),
                link=link,
                descricao=str(item.get("snippet") or "")[:3000],
                fonte="Jooble",
            ))
            novos_nesta_pagina += 1
            if len(vagas) >= limite_resultados:
                break

        if len(vagas) >= limite_resultados:
            break
        if not itens or len(itens) < tamanho_pagina or novos_nesta_pagina == 0:
            break
        if total_informado is not None and pagina * tamanho_pagina >= total_informado:
            break

    registrar_parser(URL_DIAGNOSTICO, len(vagas),
                     f"API REST Jooble paginada (até {limite_paginas} página(s))", fonte="Jooble")
    return vagas
