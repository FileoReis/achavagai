"""
scrapers/utils.py
Funções utilitárias compartilhadas pelos scrapers.
"""

import re
import unicodedata

PALAVRAS_CONECTORAS = {"de", "do", "da", "dos", "das"}


def _remover_acentos(texto: str) -> str:
    nfkd = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def slugify(texto: str) -> str:
    """Converte um texto em slug de URL: minúsculas, sem acentos, palavras
    separadas por hífen. Ex.: "Técnico em Informática" -> "tecnico-em-informatica"."""
    texto = _remover_acentos(texto).lower()
    texto = re.sub(r"[^a-z0-9\s-]", "", texto)
    texto = re.sub(r"[\s_-]+", "-", texto).strip("-")
    return texto


def slugify_cidade_sem_conectores(cidade: str) -> str:
    """Slug de cidade removendo palavras conectoras comuns (de/do/da/dos/das),
    usado pelo InfoJobs. Ex.: "Rio de Janeiro" -> "rio-janeiro",
    "Duque de Caxias" -> "duque-caxias", "São João de Meriti" -> "sao-joao-meriti"."""
    palavras = [p for p in cidade.split() if p.lower() not in PALAVRAS_CONECTORAS]
    return slugify(" ".join(palavras))
