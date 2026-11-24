"""Busca vagas pela API JSON pública usada na página de busca da Gupy.

ATENÇÃO: este endpoint de busca do portal é público, mas não é a API corporativa
formalmente documentada para integração de empresas. A estrutura pode mudar sem
aviso; por isso esta fonte é marcada como experimental e passa pelo verificador
de schema/diagnóstico. Não usa login, token, CAPTCHA ou contorno de proteção.
"""
from __future__ import annotations

import math
import re
import time
from urllib.parse import urljoin

import requests

import config
from .base import Vaga
from .diagnostico import registrar_http, registrar_parser, registrar_schema_inesperado

API_URL = "https://portal.gupy.io/api/job-search/jobs"

_UF_ESTADO = {
    "AC": "Acre", "AL": "Alagoas", "AP": "Amapá", "AM": "Amazonas",
    "BA": "Bahia", "CE": "Ceará", "DF": "Distrito Federal", "ES": "Espírito Santo",
    "GO": "Goiás", "MA": "Maranhão", "MT": "Mato Grosso", "MS": "Mato Grosso do Sul",
    "MG": "Minas Gerais", "PA": "Pará", "PB": "Paraíba", "PR": "Paraná",
    "PE": "Pernambuco", "PI": "Piauí", "RJ": "Rio de Janeiro", "RN": "Rio Grande do Norte",
    "RS": "Rio Grande do Sul", "RO": "Rondônia", "RR": "Roraima", "SC": "Santa Catarina",
    "SP": "São Paulo", "SE": "Sergipe", "TO": "Tocantins",
}
_ESTADO_UF = {nome.casefold(): uf for uf, nome in _UF_ESTADO.items()}


def _estado_alvo() -> str:
    uf = str(getattr(config, "UF_ALVO", "") or "").strip().upper()
    return _UF_ESTADO.get(uf, "")


def _local(item: dict) -> str:
    cidade = str(item.get("city") or item.get("cityName") or "").strip()
    estado = str(item.get("state") or item.get("stateName") or "").strip()
    if estado:
        estado = _ESTADO_UF.get(estado.casefold(), estado.upper() if len(estado) == 2 else estado)
    partes = [x for x in (cidade, estado) if x]
    return " / ".join(partes)


def _texto_modalidade(item: dict) -> str:
    valor = str(item.get("workplaceType") or "").strip().lower()
    return {
        "remote": "Modalidade: remoto",
        "hybrid": "Modalidade: híbrido",
        "on-site": "Modalidade: presencial",
        "onsite": "Modalidade: presencial",
    }.get(valor, "")


def _pcd(item: dict) -> bool:
    badges = item.get("badges") or {}
    if isinstance(badges, dict):
        return badges.get("isPWD") is True
    if isinstance(badges, list):
        return any(isinstance(x, dict) and x.get("isPWD") is True for x in badges)
    return item.get("isPWD") is True or item.get("acceptsPwd") is True


def buscar_vagas_gupy(palavra_chave: str, cidade: str = "", max_resultados: int = 40) -> list[Vaga]:
    termo = (palavra_chave or "").strip()
    if not termo:
        return []

    tamanho_pagina = 20
    max_paginas = max(1, min(5, math.ceil(max_resultados / tamanho_pagina)))
    params_base = {
        "jobName": termo,
        "sortBy": "publishedDate",
        "sortOrder": "desc",
        "limit": tamanho_pagina,
    }
    estado = _estado_alvo()
    if estado:
        params_base["state"] = estado
    cidade = (cidade or "").strip()
    if cidade and cidade.casefold() not in {"rj", "estado do rio de janeiro", "brasil"}:
        params_base["city"] = cidade

    vagas: list[Vaga] = []
    schema_ok = False
    paginas_consultadas = 0
    for pagina in range(max_paginas):
        params = {**params_base, "offset": pagina * tamanho_pagina}
        try:
            resposta = requests.get(
                API_URL,
                params=params,
                timeout=25,
                headers={
                    "Accept": "application/json",
                    "User-Agent": "Mozilla/5.0 (compatible; AchaVagAI/1.0; personal-job-search)",
                },
            )
            registrar_http(
                API_URL, resposta.status_code, (resposta.text or "")[:30000],
                fonte="Gupy", content_type=(resposta.headers or {}).get("Content-Type", ""),
            )
            resposta.raise_for_status()
            dados = resposta.json()
        except (requests.RequestException, ValueError) as erro:
            registrar_http(
                API_URL,
                getattr(getattr(erro, "response", None), "status_code", None),
                erro=f"{erro.__class__.__name__}: {str(erro)[:180]}",
                fonte="Gupy",
            )
            break

        paginas_consultadas += 1
        itens = dados.get("data") if isinstance(dados, dict) else None
        if not isinstance(itens, list):
            registrar_schema_inesperado(
                "Gupy", API_URL, dados,
                "A API respondeu, mas a lista de vagas não veio no campo esperado; atualização de schema provável",
            )
            return vagas
        schema_ok = True
        if not itens:
            registrar_parser(API_URL, 0, "API pública Gupy: resposta válida sem anúncios", "", "Gupy")
            break

        extraidas_pagina = 0
        for item in itens:
            if not isinstance(item, dict):
                continue
            titulo = str(item.get("name") or item.get("title") or "").strip()
            link = str(item.get("jobUrl") or item.get("url") or "").strip()
            if not titulo or not link:
                continue
            if not link.startswith(("http://", "https://")):
                link = urljoin("https://portal.gupy.io/", link)
            descricao = str(item.get("description") or "").strip()
            modalidade = _texto_modalidade(item)
            prazo = str(item.get("applicationDeadline") or "").strip()
            if modalidade:
                descricao += f"\n{modalidade}"
            if prazo:
                descricao += f"\nPrazo de candidatura: {prazo}"
            if _pcd(item):
                descricao += "\nVaga afirmativa para PcD."
            vagas.append(Vaga(
                titulo=titulo,
                empresa=str(item.get("careerPageName") or item.get("company") or "").strip(),
                cidade=_local(item),
                data_publicacao=str(item.get("publishedDate") or item.get("datePosted") or "").strip(),
                link=link,
                descricao=descricao[:5000],
                fonte="Gupy",
            ))
            extraidas_pagina += 1
            if len(vagas) >= max_resultados:
                break

        if extraidas_pagina == 0 and itens:
            registrar_schema_inesperado(
                "Gupy", API_URL, dados,
                "A API trouxe itens, mas os campos de título/link não foram reconhecidos",
            )
            return vagas
        registrar_parser(API_URL, extraidas_pagina, "API pública Gupy experimental (JSON)", "", "Gupy")
        if len(itens) < tamanho_pagina or len(vagas) >= max_resultados:
            break
        # Busca pessoal e limitada: pequena pausa entre páginas, sem varredura em massa.
        if pagina + 1 < max_paginas:
            time.sleep(max(0.0, float(getattr(config, "REQUEST_DELAY_SECONDS", 1.0))))

    if paginas_consultadas == 0 and not schema_ok:
        return []
    return vagas
