"""Consulta a API pública de vagas da Empregare (sem autenticação)."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import urljoin

import requests

from .base import Vaga
from .diagnostico import registrar_http, registrar_parser

API_URL = "https://pdv.empregare.com/api/pt-br/vagas/buscar-novo"
JOB_BASE = "https://www.empregare.com/"
_UF_ESTADO = {
    "AC": "Acre", "AL": "Alagoas", "AP": "Amapá", "AM": "Amazonas",
    "BA": "Bahia", "CE": "Ceará", "DF": "Distrito Federal", "ES": "Espírito Santo",
    "GO": "Goiás", "MA": "Maranhão", "MT": "Mato Grosso", "MS": "Mato Grosso do Sul",
    "MG": "Minas Gerais", "PA": "Pará", "PB": "Paraíba", "PR": "Paraná",
    "PE": "Pernambuco", "PI": "Piauí", "RJ": "Rio de Janeiro", "RN": "Rio Grande do Norte",
    "RS": "Rio Grande do Sul", "RO": "Rondônia", "RR": "Roraima", "SC": "Santa Catarina",
    "SP": "São Paulo", "SE": "Sergipe", "TO": "Tocantins",
}


def _normalizar_local(item: dict) -> str:
    """Extrai cidade/UF apenas dos campos efetivamente devolvidos pela API.

    O fato de a requisição conter um filtro de estado não autoriza inventar uma
    UF para um anúncio cuja resposta não informa localização.
    """
    partes: list[str] = []
    for chave in ("cidades", "cidade", "localidade", "local"):
        valor = item.get(chave)
        if not valor:
            continue
        valores = valor if isinstance(valor, list) else [valor]
        for entrada in valores:
            if isinstance(entrada, dict):
                cidade = (entrada.get("cidade") or entrada.get("nome") or entrada.get("name")
                          or entrada.get("descricao") or "")
                estado = (entrada.get("uf") or entrada.get("siglaEstado") or entrada.get("estadoSigla")
                          or entrada.get("sigla") or "")
                if not estado and isinstance(entrada.get("estado"), dict):
                    estado = entrada["estado"].get("uf") or entrada["estado"].get("sigla") or entrada["estado"].get("nome") or ""
                texto = " / ".join(str(x).strip() for x in (cidade, estado) if x)
            else:
                texto = str(entrada).strip()
            if texto and texto not in partes:
                partes.append(texto)
    # Alguns retornos expõem UF separadamente no próprio anúncio.
    uf_item = (item.get("uf") or item.get("estadoSigla") or item.get("siglaEstado") or "")
    if uf_item and partes:
        if not re.search(rf"\b{re.escape(str(uf_item))}\b", " ".join(partes), re.I):
            partes[-1] += f" / {uf_item}"
    return " / ".join(partes)


def _data_item(item: dict) -> str:
    valor = item.get("data") or item.get("dataCadastro") or ""
    if valor:
        return str(valor)
    timestamp = item.get("timestamp")
    try:
        if timestamp:
            return datetime.fromtimestamp(float(timestamp), tz=timezone.utc).date().isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        pass
    return ""


def buscar_vagas_empregare(palavra_chave: str, cidade: str = "", max_resultados: int = 30) -> list[Vaga]:
    params: list[tuple[str, str]] = [
        ("Query", palavra_chave), ("Ordenacao", "2"), ("ItensPagina", str(min(30, max_resultados))),
        ("Pagina", "1"),
    ]
    import config
    uf = str(config.UF_ALVO or "").upper()
    estado = _UF_ESTADO.get(uf, "")
    if estado:
        params.append(("Estado", estado))
    cidade_limpa = (cidade or "").strip()
    if cidade_limpa and cidade_limpa.lower() not in {"rj", "rio de janeiro - rj", "estado do rio de janeiro"}:
        params.append(("Cidade", cidade_limpa))

    try:
        resposta = requests.get(API_URL, params=params, timeout=20, headers={"Accept": "application/json"})
        registrar_http(API_URL, resposta.status_code, resposta.text[:30000], fonte="Empregare",
                       content_type=resposta.headers.get("Content-Type", ""))
        resposta.raise_for_status()
        dados = resposta.json()
    except (requests.RequestException, ValueError) as erro:
        registrar_http(API_URL, getattr(getattr(erro, "response", None), "status_code", None),
                       erro=f"{erro.__class__.__name__}: {str(erro)[:160]}", fonte="Empregare")
        return []

    model = dados.get("model", {}) if isinstance(dados, dict) else {}
    itens = model.get("dados", []) if isinstance(model, dict) else []
    vagas: list[Vaga] = []
    if isinstance(itens, list):
        for item in itens:
            if not isinstance(item, dict):
                continue
            titulo = str(item.get("titulo") or item.get("chamada") or "").strip()
            if not titulo:
                continue
            url = str(item.get("url") or "").strip()
            if not url and item.get("id"):
                url = f"v{item['id']}"
            link = urljoin(JOB_BASE, url)
            local = _normalizar_local(item)
            descricao = str(item.get("chamada") or "")
            if item.get("trabalhoRemoto") or item.get("trabalhoRemotoTexto"):
                descricao += " | Modalidade: " + str(item.get("trabalhoRemotoTexto") or "remoto")
            if item.get("pcd") is True:
                descricao += " | Vaga afirmativa para PcD."
            vagas.append(Vaga(
                titulo=titulo, empresa=str(item.get("empresa") or ""), cidade=local,
                data_publicacao=_data_item(item), link=link,
                descricao=descricao[:3000], fonte="Empregare",
            ))
            if len(vagas) >= max_resultados:
                break
    registrar_parser(API_URL, len(vagas), "API pública Empregare", str(dados)[:30000], "Empregare")
    return vagas
