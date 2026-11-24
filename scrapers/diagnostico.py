"""Diagnóstico de saúde dos coletores.

Diferencia ausência real de resultados, bloqueio HTTP, falha de rede e mudança
estrutural provável. Quando uma página pública muda de estrutura, guarda uma cópia
sanitizada para ajuste do parser; nunca tenta contornar CAPTCHA, login ou controles
anti-bot.
"""
from __future__ import annotations

import re
import threading
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from bs4 import BeautifulSoup

_LOCK = threading.RLock()
_ESTADOS: dict[str, dict] = {}
_PASTA_DIAGNOSTICOS = Path("diagnosticos")

_BLOQUEIO_RE = re.compile(
    r"captcha|verify you are human|checking your browser|access denied|"
    r"robot check|unusual traffic|security verification|enable javascript and cookies",
    re.IGNORECASE,
)
_SEM_RESULTADO_RE = re.compile(
    r"nenhuma vaga|nenhum resultado|não encontramos vagas|nao encontramos vagas|"
    r"sem resultados|no jobs found|no results found|no matching jobs|"
    r"nenhuma oportunidade encontrada",
    re.IGNORECASE,
)


def _url_sanitizada(url: str) -> str:
    """Remove query e fragmento antes de persistir URLs em diagnósticos."""
    try:
        partes = urlparse(str(url or ""))
        return urlunparse((partes.scheme, partes.netloc, partes.path, "", "", ""))
    except Exception:
        return ""

def _chave(fonte: str | None, url: str) -> str:
    if fonte:
        return fonte
    host = urlparse(url).netloc.lower().removeprefix("www.")
    return host or "fonte desconhecida"


def limpar(fonte: str) -> None:
    with _LOCK:
        _ESTADOS[fonte] = {
            "fonte": fonte, "status": "aguardando", "http_status": None,
            "quantidade": 0, "estrategia": "", "detalhe": "", "url": "",
            "tentativas": 0, "snapshot": "",
        }


def limpar_todos() -> None:
    """Inicia uma execução limpa, evitando misturar resultados de rodadas antigas."""
    with _LOCK:
        _ESTADOS.clear()


def registrar_http(
    url: str, status_code: int | None, texto: str = "", erro: str = "",
    fonte: str | None = None, content_type: str = "",
) -> None:
    nome = _chave(fonte, url)
    trecho = (texto or "")[:30000]
    with _LOCK:
        atual = _ESTADOS.setdefault(nome, {"fonte": nome, "tentativas": 0})
        atual["tentativas"] = int(atual.get("tentativas", 0)) + 1
        atual["url"] = _url_sanitizada(url)
        atual["http_status"] = status_code
        atual["content_type"] = content_type
        if erro:
            if "não configurada" in erro.lower() or "nao configurada" in erro.lower():
                status, detalhe = "configuracao_ausente", erro[:240]
            else:
                status, detalhe = "erro_rede", erro[:240]
            if int(atual.get("quantidade", 0)) > 0:
                atual.update(status="parcial", detalhe=f"{atual['quantidade']} vaga(s) extraída(s); {detalhe}")
            else:
                atual.update(status=status, detalhe=detalhe)
        elif status_code in (401, 403, 407, 429, 451):
            if int(atual.get("quantidade", 0)) > 0:
                atual.update(status="parcial", detalhe=f"{atual['quantidade']} vaga(s) extraída(s); bloqueio HTTP {status_code}")
            else:
                atual.update(status="bloqueio", detalhe=f"HTTP {status_code}")
        elif status_code is not None and status_code >= 400:
            atual.update(status="erro_http", detalhe=f"HTTP {status_code}")
        elif _BLOQUEIO_RE.search(trecho):
            atual.update(status="bloqueio", detalhe="Página de verificação/CAPTCHA detectada")
        else:
            atual.update(status="http_ok", detalhe="Resposta HTTP recebida")


def _salvar_snapshot(fonte: str, url: str, html: str) -> str:
    """Guarda um esqueleto DOM, sem texto, links, cookies ou dados pessoais.

    O verificador precisa das tags, classes e metadados semânticos para comparar
    mudanças de estrutura; não precisa armazenar o conteúdo dos anúncios.
    """
    try:
        soup = BeautifulSoup((html or "")[:1_500_000], "html.parser")
        for tag in soup.find_all(["script", "style", "noscript", "iframe", "form", "input", "button"]):
            tag.decompose()
        # Só preserva atributos estruturais e semânticos. Não grava href, id,
        # value, texto da vaga, telefone, e-mail ou identificadores dinâmicos.
        permitidos = {"class", "role", "itemprop", "itemtype", "itemscope", "data-testid", "aria-label"}
        for tag in soup.find_all(True):
            tag.attrs = {k: v for k, v in tag.attrs.items() if k.lower() in permitidos}
        for texto in list(soup.find_all(string=True)):
            texto.replace_with(" ")
        conteudo = str(soup)[:500_000]
        slug = re.sub(r"[^a-z0-9_-]+", "_", fonte.lower()).strip("_") or "fonte"
        pasta = _PASTA_DIAGNOSTICOS / "html"
        pasta.mkdir(parents=True, exist_ok=True)
        nome = f"{slug}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.html"
        destino = pasta / nome
        destino.write_text(
            f"<!-- Snapshot estrutural de {_url_sanitizada(url)}; valores de anúncio removidos. -->\n{conteudo}",
            encoding="utf-8",
        )
        return str(destino)
    except Exception:
        return ""


def registrar_parser(
    url: str, quantidade: int, estrategia: str, html: str = "", fonte: str | None = None
) -> None:
    nome = _chave(fonte, url)
    with _LOCK:
        atual = _ESTADOS.setdefault(nome, {"fonte": nome, "tentativas": 0})
        atual["quantidade"] = int(atual.get("quantidade", 0)) + max(0, int(quantidade))
        atual["estrategia"] = estrategia or "não identificada"
        atual["url"] = _url_sanitizada(url)
        status_http = atual.get("status")
        total = int(atual.get("quantidade", 0))
        if total > 0:
            atual.update(status="ok", detalhe=f"{total} vaga(s) extraída(s)")
            return
        if status_http in {"bloqueio", "erro_http", "erro_rede", "configuracao_ausente"}:
            return

    texto = BeautifulSoup((html or "")[:30000], "html.parser").get_text(" ", strip=True)
    if _BLOQUEIO_RE.search(html or "") or _BLOQUEIO_RE.search(texto):
        status, detalhe = "bloqueio", "Página de verificação/CAPTCHA detectada; coleta interrompida"
    elif _SEM_RESULTADO_RE.search(texto):
        status, detalhe = "sem_resultados", "Página reconhecida; o portal informou que não há resultados"
    elif not html and any(x in (estrategia or "").lower() for x in ("api", "feed", "xml")):
        status, detalhe = "sem_resultados", "Fonte estruturada respondeu corretamente, mas não encontrou vagas"
    elif len(texto) < 120:
        status, detalhe = "resposta_vazia", "Resposta muito curta para identificar a estrutura"
    else:
        status, detalhe = "estrutura_alterada", "HTML recebido, mas os extratores não reconheceram cartões de vagas"

    snapshot = _salvar_snapshot(nome, url, html) if status == "estrutura_alterada" else ""
    with _LOCK:
        atual = _ESTADOS.setdefault(nome, {"fonte": nome, "tentativas": 0})
        atual.update(status=status, detalhe=detalhe, snapshot=snapshot)



def _resumir_schema_json(valor, profundidade: int = 0):
    """Resume a forma de um JSON sem gravar valores de anúncios ou dados pessoais."""
    if profundidade >= 4:
        return type(valor).__name__
    if isinstance(valor, dict):
        return {str(chave)[:80]: _resumir_schema_json(v, profundidade + 1)
                for chave, v in list(valor.items())[:40]}
    if isinstance(valor, list):
        return [_resumir_schema_json(valor[0], profundidade + 1)] if valor else []
    return type(valor).__name__


def registrar_schema_inesperado(fonte: str, url: str, dados, detalhe: str = "Resposta JSON mudou de estrutura") -> None:
    """Registra alteração de schema de API sem persistir o conteúdo dos anúncios."""
    import json

    slug = re.sub(r"[^a-z0-9_-]+", "_", fonte.lower()).strip("_") or "fonte"
    snapshot = ""
    try:
        pasta = _PASTA_DIAGNOSTICOS / "json"
        pasta.mkdir(parents=True, exist_ok=True)
        destino = pasta / f"{slug}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.json"
        documento = {"fonte": fonte, "url": _url_sanitizada(url), "schema": _resumir_schema_json(dados)}
        destino.write_text(json.dumps(documento, ensure_ascii=False, indent=2), encoding="utf-8")
        snapshot = str(destino)
    except Exception:
        pass
    with _LOCK:
        atual = _ESTADOS.setdefault(fonte, {"fonte": fonte, "tentativas": 0})
        atual.update(status="estrutura_alterada", detalhe=detalhe[:240],
                     estrategia="verificação de schema JSON", url=_url_sanitizada(url), snapshot=snapshot)

def obter(fonte: str) -> dict:
    with _LOCK:
        return dict(_ESTADOS.get(fonte, {"fonte": fonte, "status": "sem_diagnostico"}))


def listar() -> list[dict]:
    with _LOCK:
        return [dict(v) for v in _ESTADOS.values()]
