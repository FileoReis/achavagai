"""Estruturas, sessão HTTP e telemetria compartilhadas pelos scrapers."""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass

import requests

from config import HEADERS, REQUEST_DELAY_SECONDS
from .diagnostico import registrar_http


@dataclass
class Vaga:
    titulo: str
    empresa: str
    cidade: str
    data_publicacao: str
    link: str
    descricao: str
    fonte: str
    termo_busca: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def nova_sessao() -> requests.Session:
    sessao = requests.Session()
    sessao.headers.update(HEADERS)
    return sessao


def buscar_url(
    sessao: requests.Session,
    url: str,
    diagnostico_nome: str | None = None,
    **kwargs,
) -> requests.Response | None:
    """Faz GET sem esconder a natureza da falha.

    Não tenta resolver CAPTCHA, fazer login automatizado nem contornar bloqueios.
    ``diagnostico_nome`` identifica o portal no verificador de saúde.
    """
    resposta = None
    try:
        resposta = sessao.get(url, timeout=20, **kwargs)
        texto = getattr(resposta, "text", "") or ""
        registrar_http(
            url=url,
            status_code=resposta.status_code,
            texto=texto[:30000],
            content_type=(resposta.headers or {}).get("Content-Type", ""),
            fonte=diagnostico_nome,
            url_final=getattr(resposta, "url", "") or url,
        )
        resposta.raise_for_status()
        if resposta.status_code in (401, 403, 407, 429, 451):
            return None
        time.sleep(REQUEST_DELAY_SECONDS)
        return resposta
    except requests.RequestException as erro:
        status = getattr(getattr(erro, "response", None), "status_code", None)
        texto = getattr(getattr(erro, "response", None), "text", "") or ""
        # Se houve resposta HTTP, ela já foi registrada acima. Evita duplicar
        # tentativas/erros para 401/403/429 ao executar raise_for_status().
        if resposta is None:
            registrar_http(
                url=url, status_code=status, texto=texto[:30000],
                erro=f"{erro.__class__.__name__}: {str(erro)[:180]}",
                fonte=diagnostico_nome,
                url_final=getattr(getattr(erro, "response", None), "url", "") or url,
            )
        return None
