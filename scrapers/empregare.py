"""Consulta a API pública de vagas da Empregare (sem autenticação)."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import urljoin

import requests

from .base import Vaga
from .diagnostico import registrar_http, registrar_parser, registrar_schema_inesperado

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


def _primeiro_valor(item: dict, *chaves: str):
    for chave in chaves:
        valor = item.get(chave)
        if valor not in (None, "", [], {}):
            return valor
    return ""


def _localizar_lista_vagas(dados):
    """Localiza a coleção de vagas na resposta sem presumir qualquer JSON arbitrário.

    A estrutura documentada é model.dados. Algumas instalações/versões podem
    encapsular o mesmo resultado em data/results/items; esses caminhos são
    aceitos apenas quando os registros têm campos reconhecíveis de título.
    Retorna (lista, caminho, reconhecida).
    """
    if isinstance(dados, list):
        if not dados:
            return [], "raiz", True
        if any(isinstance(x, dict) and _primeiro_valor(x, "titulo", "title", "nomeVaga", "cargo") for x in dados):
            return dados, "raiz", True
        return [], "raiz", False

    if not isinstance(dados, dict):
        return [], "", False

    model = dados.get("model")
    if isinstance(model, dict) and "dados" in model:
        registros = model.get("dados")
        if isinstance(registros, list):
            # Em uma resposta documentada, [] é uma resposta válida sem vagas.
            if not registros or any(
                isinstance(x, dict) and _primeiro_valor(x, "titulo", "title", "nomeVaga", "cargo")
                for x in registros
            ):
                return registros, "model.dados", True
        return [], "model.dados", False

    # Fallbacks conservadores para wrappers comuns de APIs JSON.
    for caminho in ("data", "items", "results", "vagas", "jobs", "registros"):
        registros = dados.get(caminho)
        if isinstance(registros, list):
            if not registros or any(
                isinstance(x, dict) and _primeiro_valor(x, "titulo", "title", "nomeVaga", "cargo")
                for x in registros
            ):
                return registros, caminho, True
            return [], caminho, False
        if isinstance(registros, dict):
            for subchave in ("dados", "items", "results", "vagas", "jobs"):
                sub = registros.get(subchave)
                if isinstance(sub, list):
                    if not sub or any(
                        isinstance(x, dict) and _primeiro_valor(x, "titulo", "title", "nomeVaga", "cargo")
                        for x in sub
                    ):
                        return sub, f"{caminho}.{subchave}", True
                    return [], f"{caminho}.{subchave}", False
    return [], "", False


def _normalizar_local(item: dict) -> str:
    """Extrai cidade/UF apenas dos campos efetivamente devolvidos pela API.

    O fato de a requisição conter um filtro de estado não autoriza inventar uma
    UF para um anúncio cuja resposta não informa localização.
    """
    partes: list[str] = []
    for chave in ("cidades", "cidade", "localidade", "local", "locations", "location"):
        valor = item.get(chave)
        if not valor:
            continue
        valores = valor if isinstance(valor, list) else [valor]
        for entrada in valores:
            if isinstance(entrada, dict):
                cidade = (entrada.get("cidade") or entrada.get("nome") or entrada.get("name")
                          or entrada.get("descricao") or entrada.get("localidade") or "")
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
    valor = _primeiro_valor(item, "data", "dataCadastro", "datePosted", "createdAt", "publishedAt")
    if valor:
        return str(valor)
    timestamp = item.get("timestamp")
    try:
        if timestamp:
            numero = float(timestamp)
            if numero > 10_000_000_000:  # alguns serviços entregam milissegundos
                numero /= 1000
            return datetime.fromtimestamp(numero, tz=timezone.utc).date().isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        pass
    return ""


def buscar_vagas_empregare(palavra_chave: str, cidade: str = "", max_resultados: int = 30) -> list[Vaga]:
    params: list[tuple[str, str]] = [
        ("Query", palavra_chave), ("Ordenacao", "2"), ("ItensPagina", str(min(30, max(1, max_resultados)))),
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
        # Endpoint documentado como busca pública; não adicionamos cookies,
        # tokens ou técnicas para contornar respostas 401/403.
        from config import HEADERS
        headers = dict(HEADERS)
        headers.update({
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://www.empregare.com/",
        })
        resposta = requests.get(API_URL, params=params, timeout=20, headers=headers)
        corpo = resposta.text or ""
        content_type = resposta.headers.get("Content-Type", "")
        registrar_http(API_URL, resposta.status_code, corpo[:30000], fonte="Empregare",
                       content_type=content_type, url_final=getattr(resposta, "url", "") or API_URL)
        resposta.raise_for_status()
    except requests.HTTPError:
        # O HTTP já foi registrado; 403 é acesso negado, não timeout.
        return []
    except requests.RequestException as erro:
        registrar_http(API_URL, None,
                       erro=f"{erro.__class__.__name__}: falha de comunicação com a Empregare",
                       fonte="Empregare")
        return []

    try:
        dados = resposta.json()
    except (requests.exceptions.JSONDecodeError, ValueError):
        # Se o servidor devolveu HTML, o snapshot preserva a estrutura DOM
        # (tags/classes) sem texto de anúncios, cookies ou dados pessoais.
        if "html" in content_type.lower() or corpo.lstrip().lower().startswith(("<!doctype html", "<html")):
            registrar_parser(API_URL, 0, "resposta HTML da API pública Empregare", corpo,
                             "Empregare", content_type=content_type,
                             url_final=getattr(resposta, "url", "") or API_URL)
        else:
            registrar_schema_inesperado("Empregare", API_URL,
                                        {"tipo_resposta": content_type or "desconhecido",
                                         "corpo": "texto não JSON (conteúdo omitido)"},
                                        "A API respondeu, mas o corpo não é JSON válido")
        return []

    itens, caminho, reconhecida = _localizar_lista_vagas(dados)
    if not reconhecida:
        registrar_schema_inesperado(
            "Empregare", API_URL, dados,
            "JSON recebido, mas a coleção de vagas não corresponde ao schema conhecido",
        )
        return []

    vagas: list[Vaga] = []
    for item in itens:
        if not isinstance(item, dict):
            continue
        titulo = str(_primeiro_valor(item, "titulo", "title", "nomeVaga", "cargo") or "").strip()
        if not titulo:
            continue
        url = str(_primeiro_valor(item, "url", "link", "urlVaga", "applicationUrl") or "").strip()
        if not url and item.get("id"):
            url = f"v{item['id']}"
        link = urljoin(JOB_BASE, url) if url else JOB_BASE
        local = _normalizar_local(item)
        descricao = str(_primeiro_valor(item, "chamada", "descricao", "description", "resumo") or "")
        modalidade = _primeiro_valor(item, "trabalhoRemotoTexto", "modalidade", "modalidadeTexto")
        if item.get("trabalhoRemoto") or modalidade:
            descricao += " | Modalidade: " + str(modalidade or "remoto")
        if item.get("pcd") is True or item.get("PcD") is True:
            descricao += " | Vaga afirmativa para PcD."
        vagas.append(Vaga(
            titulo=titulo,
            empresa=str(_primeiro_valor(item, "empresa", "nomeEmpresa", "empresaNome", "company") or ""),
            cidade=local,
            data_publicacao=_data_item(item),
            link=link,
            descricao=descricao[:3000],
            fonte="Empregare",
        ))
        if len(vagas) >= max_resultados:
            break

    if not vagas and itens:
        # A lista existe, mas seus registros não têm mais os campos de título.
        registrar_schema_inesperado(
            "Empregare", API_URL, dados,
            "A coleção de vagas foi localizada, mas os registros não têm campo de título reconhecido",
        )
        return []

    if not itens:
        model = dados.get("model", {}) if isinstance(dados, dict) else {}
        total = None
        if isinstance(model, dict):
            total = model.get("totalVagas", model.get("totalRegistro"))
        try:
            if total is not None and int(total) > 0:
                registrar_schema_inesperado(
                    "Empregare", API_URL, dados,
                    "API informa vagas disponíveis, mas a coleção model.dados veio vazia",
                )
                return []
        except (TypeError, ValueError):
            pass

    registrar_parser(
        API_URL, len(vagas), f"API pública Empregare ({caminho or 'coleção reconhecida'})",
        "", "Empregare", content_type=content_type,
        url_final=getattr(resposta, "url", "") or API_URL,
    )
    return vagas
