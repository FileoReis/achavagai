"""Coordenadas aproximadas dos centros municipais mais comuns no RJ.

As distâncias são em linha reta entre centros municipais: não representam rota,
trânsito ou tempo de deslocamento. Cidades sem coordenada ficam sem estimativa.
"""
from __future__ import annotations
import math
import re
import unicodedata

COORDENADAS_RJ = {
    "rio de janeiro": (-22.9068, -43.1729),
    "nova iguacu": (-22.7592, -43.4511),
    "niteroi": (-22.8832, -43.1034),
    "sao goncalo": (-22.8268, -43.0634),
    "duque de caxias": (-22.7858, -43.3049),
    "belford roxo": (-22.7642, -43.3996),
    "sao joao de meriti": (-22.8039, -43.3720),
    "nilopolis": (-22.8075, -43.4137),
    "mesquita": (-22.7821, -43.4296),
    "queimados": (-22.7169, -43.5552),
    "mage": (-22.6536, -43.0408),
    "itaborai": (-22.7446, -42.8596),
    "petropolis": (-22.5050, -43.1782),
    "volta redonda": (-22.5231, -44.1040),
    "macae": (-22.3768, -41.7869),
    "cabo frio": (-22.8894, -42.0286),
    "angra dos reis": (-23.0067, -44.3180),
    "campos dos goytacazes": (-21.7622, -41.3181),
    "itaguai": (-22.8522, -43.7756),
    "barra mansa": (-22.5445, -44.1706),
    "resende": (-22.4705, -44.4509),
    "teresopolis": (-22.4165, -42.9752),
    "rio das ostras": (-22.5269, -41.9450),
}

def _norm(texto: str) -> str:
    s = unicodedata.normalize("NFD", str(texto or "").lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()

def cidade_chave(texto: str) -> str | None:
    normal = _norm(texto)
    if not normal:
        return None
    for city in sorted(COORDENADAS_RJ, key=len, reverse=True):
        if city == normal or re.search(r"(?<![a-z])" + re.escape(city) + r"(?![a-z])", normal):
            return city
    return None

def distancia_km(origem: str, destino: str) -> float | None:
    a, b = cidade_chave(origem), cidade_chave(destino)
    if not a or not b:
        return None
    lat1, lon1 = COORDENADAS_RJ[a]
    lat2, lon2 = COORDENADAS_RJ[b]
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2-lat1), math.radians(lon2-lon1)
    h = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return round(2*r*math.asin(math.sqrt(h)), 1)

def coordenada(texto: str):
    key = cidade_chave(texto)
    return COORDENADAS_RJ.get(key) if key else None


def faixa_distancia(distancia: float | None) -> str:
    """Agrupa distância em linha reta entre centros municipais, sem prometer tempo de viagem."""
    if distancia is None:
        return "Sem estimativa"
    if distancia <= 30:
        return "Até 30 km"
    if distancia <= 60:
        return "31–60 km"
    if distancia <= 100:
        return "61–100 km"
    return "Mais de 100 km"
