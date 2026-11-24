"""Validação local da intenção da busca para evitar vagas fora do cargo pedido.

Não usa IA: siglas como CPD precisam de correspondência exata para não serem
confundidas com PCD. A localização é deliberadamente ignorada nesta etapa, pois
alguns scrapers misturam cidade, resumo e metadados no mesmo campo.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


def normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", str(texto or ""))
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", texto.lower()).strip()


@dataclass(frozen=True)
class Intencao:
    termo_original: str
    padroes: tuple[str, ...]
    exige_correspondencia_exata: bool = True


_PADROES_ESPECIAIS: dict[str, tuple[str, ...]] = {
    "cpd": (
        r"\bcpd\b",
        r"\bcentral de processamento de dados\b",
        r"\bcentro de processamento de dados\b",
    ),
    "informatica": (
        r"\binformatica\b",
        r"\btecnologia da informacao\b",
        r"\btecnico de informatica\b",
        r"\btecnica de informatica\b",
        r"\banalista de ti\b",
        r"\bsuporte (?:tecnico )?(?:de )?ti\b",
        r"\bsuporte tecnico em informatica\b",
        r"\bhelp ?desk\b",
        r"\bservice desk\b",
        r"\bmanutencao de (?:microcomputadores|computadores|micros)\b",
        r"\binfraestrutura de ti\b",
        r"\bredes de computadores\b",
    ),
    "motorista": (
        r"\bmotorista\b",
        r"\bcondutor(?:a)?\b",
        r"\bentregador(?:a)?\b",
        r"\bmotorista entregador\b",
    ),
    "auxiliar administrativo": (
        r"\bauxiliar administrativo\b",
        r"\bassistente administrativo\b",
    ),
}


def compilar_intencoes(termos: list[str] | tuple[str, ...]) -> list[Intencao]:
    resultado: list[Intencao] = []
    vistos: set[str] = set()
    for termo in termos:
        original = str(termo or "").strip()
        canonico = normalizar(original)
        if not canonico or canonico in vistos:
            continue
        vistos.add(canonico)
        especiais = _PADROES_ESPECIAIS.get(canonico)
        if especiais:
            resultado.append(Intencao(original, especiais))
            continue
        # Correspondência literal por frase ou conjunto de palavras relevantes.
        # Não transforma o termo em busca por qualquer palavra isolada.
        tokens = [t for t in canonico.split() if len(t) > 1]
        if not tokens:
            padroes = (rf"\b{re.escape(canonico)}\b",)
        else:
            frase = r"\b" + r"\s+".join(re.escape(t) for t in tokens) + r"\b"
            padroes = (frase,)
        resultado.append(Intencao(original, padroes))
    return resultado


def vaga_corresponde(vaga, intencoes: list[Intencao] | tuple[Intencao, ...]) -> bool:
    if not intencoes:
        return True
    # Só título e descrição. Cidade, empresa ou termo de busca são metadados e
    # podem estar contaminados; não podem validar uma vaga irrelevante.
    titulo = normalizar(getattr(vaga, "titulo", ""))
    descricao = normalizar(getattr(vaga, "descricao", ""))
    texto = f"{titulo} {descricao}".strip()
    for intencao in intencoes:
        if any(re.search(padrao, texto) for padrao in intencao.padroes):
            return True
    return False


def filtrar_por_intencao(vagas: list, termos: list[str] | tuple[str, ...]) -> tuple[list, list]:
    """Retorna (mantidas, descartadas) pela aderência aos termos selecionados."""
    intencoes = compilar_intencoes(termos)
    if not intencoes:
        return list(vagas), []
    mantidas, descartadas = [], []
    for vaga in vagas:
        (mantidas if vaga_corresponde(vaga, intencoes) else descartadas).append(vaga)
    return mantidas, descartadas
