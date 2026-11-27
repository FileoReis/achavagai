"""Validação local e conservadora da intenção da busca.

Normaliza acentos, espaços e títulos concatenados por alguns portais. Siglas curtas
como CPD continuam exigindo correspondência exata para não confundir CPD com PCD.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


def normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", str(texto or ""))
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", texto.lower()).strip()


def _compactar(texto: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", normalizar(texto))


@dataclass(frozen=True)
class Intencao:
    termo_original: str
    padroes: tuple[str, ...]
    exige_correspondencia_exata: bool = True
    compacto: tuple[str, ...] = ()


_PADROES_ESPECIAIS: dict[str, tuple[str, ...]] = {
    "cpd": (
        r"\bcpd\b",
        r"\bcentral de processamento de dados\b",
        r"\bcentro de processamento de dados\b",
    ),
    "informatica": (
        # Sufixos comuns de nível/turno que alguns portais juntam ao cargo:
        # "Técnico deInformaticaN1", "Analista InformaticaJR" etc.
        r"\binformatica(?:n[0-9]+|jr|junior|pleno|senior|sr)?\b",
        r"\btecnic[oa] de\s*informatica(?:n[0-9]+|jr|junior|pleno|senior|sr)?\b",
        r"\btecnic[oa] em\s*informatica(?:n[0-9]+|jr|junior|pleno|senior|sr)?\b",
        r"\b(?:analista|assistente|auxiliar|operador)\s*de\s*informatica(?:n[0-9]+|jr|junior|pleno|senior|sr)?\b",
        r"\btecnic[oa] de\s*ti(?:\s*(?:jr|junior|pleno|senior|sr))?\b",
        r"\btecnic[oa] em\s*ti(?:\s*(?:jr|junior|pleno|senior|sr))?\b",
        r"\banalista de\s*ti(?:\s*(?:jr|junior|pleno|senior|sr))?\b",
        r"\bassistente de\s*ti\b",
        r"\btecnic[oa] de suporte\b",
        r"\banalista de suporte(?: tecnico)?(?: de)?\s*ti\b",
        r"\bsuporte (?:tecnico )?(?:de )?ti\b",
        r"\bsuporte tecnico em informatica\b",
        r"\bhelp ?desk\b",
        r"\bservice desk\b",
        r"\bmanutencao de (?:microcomputadores|computadores|micros)\b",
        r"\binfraestrutura de ti\b",
        r"\bredes de computadores\b",
    ),
    "motorista": (
        # Prefixo deliberado: cobre "MotoristaCarga" e "Motoristade Caminhão".
        r"\bmotorista",
        r"\bcondutor(?:a)?\b",
        r"\bentregador(?:a)?\b",
        r"\bmotoboy\b",
        r"\bmotofretista\b",
    ),
    "auxiliar administrativo": (
        r"\bauxiliar\s*administrativo\b",
        r"\bassistente\s*administrativo\b",
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
            # CPD não tem busca compacta/prefixal: isso preserva a diferença CPD/PCD.
            resultado.append(Intencao(original, especiais, compacto=()))
            continue
        tokens = [t for t in canonico.split() if len(t) > 1]
        if not tokens:
            padroes = (rf"\b{re.escape(canonico)}\b",)
        else:
            frase = r"\b" + r"\s+".join(re.escape(t) for t in tokens) + r"\b"
            padroes = (frase,)
        compact = _compactar(canonico)
        # A alternativa compacta só é habilitada para frases com pelo menos 8
        # caracteres: reduz falsos positivos com siglas/termos curtos.
        compactos = (compact,) if len(compact) >= 8 else ()
        resultado.append(Intencao(original, padroes, compacto=compactos))
    return resultado


def _texto_corresponde(texto: str, intencoes: list[Intencao] | tuple[Intencao, ...]) -> bool:
    normal = normalizar(texto)
    compacto = _compactar(texto)
    for intencao in intencoes:
        if any(re.search(padrao, normal) for padrao in intencao.padroes):
            return True
        if intencao.compacto and any(p in compacto for p in intencao.compacto):
            return True
    return False


def vaga_corresponde_titulo(vaga, intencoes: list[Intencao] | tuple[Intencao, ...]) -> bool:
    """True somente quando o título da vaga corresponde ao cargo pesquisado."""
    return _texto_corresponde(getattr(vaga, "titulo", ""), intencoes)


def vaga_corresponde(vaga, intencoes: list[Intencao] | tuple[Intencao, ...]) -> bool:
    if not intencoes:
        return True
    # Só título e descrição. Cidade, empresa e termo de busca são metadados e
    # podem estar contaminados; não podem validar uma vaga irrelevante.
    titulo = getattr(vaga, "titulo", "") or ""
    descricao = getattr(vaga, "descricao", "") or ""
    return _texto_corresponde(titulo, intencoes) or _texto_corresponde(descricao, intencoes)


def filtrar_por_intencao(vagas: list, termos: list[str] | tuple[str, ...]) -> tuple[list, list]:
    """Retorna (mantidas, descartadas) pela aderência aos termos selecionados."""
    intencoes = compilar_intencoes(termos)
    if not intencoes:
        return list(vagas), []
    mantidas, descartadas = [], []
    for vaga in vagas:
        (mantidas if vaga_corresponde(vaga, intencoes) else descartadas).append(vaga)
    return mantidas, descartadas
