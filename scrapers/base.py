"""
base.py
Estruturas e utilidades compartilhadas por todos os scrapers de sites de vagas.
"""

import time
from dataclasses import dataclass, asdict

import requests

from config import HEADERS, REQUEST_DELAY_SECONDS


@dataclass
class Vaga:
    titulo: str
    empresa: str
    cidade: str
    data_publicacao: str
    link: str
    descricao: str
    fonte: str  # nome do site de origem (ex.: "LinkedIn", "Indeed", "RioVagas")
    termo_busca: str = ""  # qual cargo/palavra-chave pesquisada gerou esta vaga (preenchido pelo main.py)

    def to_dict(self) -> dict:
        return asdict(self)


def nova_sessao() -> requests.Session:
    """Cria uma sessão requests com headers de navegador."""
    sessao = requests.Session()
    sessao.headers.update(HEADERS)
    return sessao


def buscar_url(sessao: requests.Session, url: str, **kwargs) -> requests.Response | None:
    """Faz um GET com tratamento de erro e uma pequena pausa (boa prática de scraping,
    evita sobrecarregar o servidor e reduz o risco de bloqueio). Falhas são silenciosas
    por padrão (um site fora do ar ou bloqueando não deve poluir o terminal) — o
    chamador decide se quer registrar/mostrar algo a respeito."""
    try:
        resposta = sessao.get(url, timeout=15, **kwargs)
        resposta.raise_for_status()
        time.sleep(REQUEST_DELAY_SECONDS)
        return resposta
    except requests.RequestException:
        return None
