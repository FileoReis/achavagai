"""Extratores HTML adaptáveis, independentes de um único conjunto de classes CSS.

Ordem: Schema.org JobPosting (JSON-LD/microdata) e, como fallback, links de vagas
com cartões encontrados por relações semânticas (âncoras, cabeçalhos, datas e
contêineres). CSS gerado por IA não é executado; somente parsers validados são usados.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .base import Vaga

_DATE_RE = re.compile(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b")


def _texto(valor, limite: int = 1800) -> str:
    if valor is None:
        return ""
    if isinstance(valor, (dict, list)):
        return _texto_json(valor, limite)
    soup = BeautifulSoup(str(valor), "html.parser")
    return re.sub(r"\s+", " ", soup.get_text(" ", strip=True)).strip()[:limite]


def _texto_json(valor, limite: int = 1800) -> str:
    if isinstance(valor, list):
        return ", ".join(_texto_json(x, limite) for x in valor[:5])[:limite]
    if isinstance(valor, dict):
        return _texto_json(valor.get("name") or valor.get("@id") or "", limite)
    return str(valor or "")[:limite]


def _tipos(obj: dict) -> set[str]:
    tipo = obj.get("@type", [])
    if isinstance(tipo, str):
        tipo = [tipo]
    return {str(x).split("/")[-1].lower() for x in tipo}


def _iterar_jsonld(dado):
    if isinstance(dado, list):
        for item in dado:
            yield from _iterar_jsonld(item)
    elif isinstance(dado, dict):
        if "jobposting" in _tipos(dado):
            yield dado
        if "@graph" in dado:
            yield from _iterar_jsonld(dado["@graph"])
        for chave, valor in dado.items():
            if chave not in {"@graph", "@context"} and isinstance(valor, (list, dict)):
                yield from _iterar_jsonld(valor)


def _local_jsonld(item: dict) -> str:
    lugares = item.get("jobLocation") or item.get("applicantLocationRequirements") or []
    if isinstance(lugares, dict):
        lugares = [lugares]
    partes = []
    for local in lugares[:4] if isinstance(lugares, list) else []:
        endereco = local.get("address", local) if isinstance(local, dict) else {}
        if not isinstance(endereco, dict):
            continue
        cidade = endereco.get("addressLocality") or endereco.get("name") or ""
        regiao = endereco.get("addressRegion") or ""
        pais = endereco.get("addressCountry") or ""
        if isinstance(pais, dict):
            pais = pais.get("name") or pais.get("@id") or ""
        texto = ", ".join(x for x in (cidade, regiao, pais) if x)
        if texto and texto not in partes:
            partes.append(texto)
    if str(item.get("jobLocationType", "")).upper().endswith("TELECOMMUTE"):
        partes.insert(0, "Remoto")
    return " / ".join(partes)


def extrair_jsonld(html: str, fonte: str, base_url: str) -> list[Vaga]:
    soup = BeautifulSoup(html or "", "html.parser")
    encontrados: list[Vaga] = []
    vistos: set[str] = set()
    for script in soup.find_all("script", attrs={"type": re.compile(r"ld\+json", re.I)}):
        bruto = script.string or script.get_text()
        if not bruto or len(bruto) > 1_000_000:
            continue
        try:
            dado = json.loads(bruto.strip())
        except (json.JSONDecodeError, TypeError):
            continue
        for item in _iterar_jsonld(dado):
            titulo = _texto(item.get("title") or item.get("name"), 240)
            if not titulo:
                continue
            empresa_obj = item.get("hiringOrganization") or {}
            empresa = _texto(empresa_obj.get("name") if isinstance(empresa_obj, dict) else empresa_obj, 140)
            link = item.get("url") or item.get("sameAs") or ""
            if not link and isinstance(item.get("identifier"), dict):
                link = item["identifier"].get("value", "")
            link = urljoin(base_url, str(link)) if link else base_url
            if link in vistos:
                continue
            vistos.add(link)
            encontrados.append(Vaga(
                titulo=titulo, empresa=empresa, cidade=_local_jsonld(item),
                data_publicacao=str(item.get("datePosted") or ""), link=link,
                descricao=_texto(item.get("description"), 4000), fonte=fonte,
            ))
    return encontrados



def _prop_text(raiz, prop: str, limite: int = 1800) -> str:
    tag = raiz if raiz.get("itemprop") == prop else raiz.select_one(f'[itemprop="{prop}"]')
    if not tag:
        return ""
    valor = tag.get("content") or tag.get("datetime") or tag.get("href") or tag.get_text(" ", strip=True)
    return _texto(valor, limite)


def extrair_microdata(html: str, fonte: str, base_url: str) -> list[Vaga]:
    """Extrai JobPosting Schema.org via microdata, sem depender de classes CSS."""
    soup = BeautifulSoup(html or "", "html.parser")
    encontrados: list[Vaga] = []
    vistos: set[str] = set()
    raizes = soup.select('[itemscope][itemtype]')
    for raiz in raizes:
        tipo = str(raiz.get("itemtype") or "").lower()
        if "schema.org/jobposting" not in tipo:
            continue
        titulo = _prop_text(raiz, "title", 240) or _prop_text(raiz, "name", 240)
        if not titulo:
            continue
        org = raiz.select_one('[itemprop="hiringOrganization"]')
        empresa = _prop_text(org, "name", 140) if org else ""
        local = ""
        local_tag = raiz.select_one('[itemprop="jobLocation"]')
        if local_tag:
            endereco = local_tag.select_one('[itemprop="address"]') or local_tag
            cidade = _prop_text(endereco, "addressLocality", 120)
            regiao = _prop_text(endereco, "addressRegion", 80)
            pais = _prop_text(endereco, "addressCountry", 80)
            local = ", ".join(x for x in (cidade, regiao, pais) if x)
        data = _prop_text(raiz, "datePosted", 80)
        descricao = _prop_text(raiz, "description", 4000)
        link = _prop_text(raiz, "url", 500) or str(raiz.get("itemid") or "")
        if not link:
            link_tag = raiz.select_one('[itemprop="url"][href]')
            link = str(link_tag.get("href") or "") if link_tag else ""
        link = urljoin(base_url, link) if link else base_url
        if link in vistos:
            continue
        vistos.add(link)
        encontrados.append(Vaga(
            titulo=titulo, empresa=empresa, cidade=local, data_publicacao=data,
            link=link, descricao=descricao, fonte=fonte,
        ))
    return encontrados


def mesclar_vagas(principais: list[Vaga], alternativas: list[Vaga], max_resultados: int = 60) -> list[Vaga]:
    """Une parsers conhecido/adaptativo sem duplicar links já coletados."""
    resultado: list[Vaga] = []
    vistos: set[str] = set()
    for vaga in [*(principais or []), *(alternativas or [])]:
        link = str(getattr(vaga, "link", "") or "").strip()
        if link:
            # Remove fragmentos e parâmetros de rastreamento comuns, mantendo os
            # parâmetros que identificam anúncios no Indeed (jk=).
            from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
            partes = urlsplit(link)
            query = parse_qsl(partes.query, keep_blank_values=True)
            if "indeed." in partes.netloc.lower():
                query = [(k, v) for k, v in query if k.lower() in {"jk", "vjk"}]
            else:
                query = []
            chave = urlunsplit((partes.scheme.lower(), partes.netloc.lower(), partes.path.rstrip("/"), urlencode(query), ""))
        else:
            chave = "|".join((
                re.sub(r"\s+", " ", getattr(vaga, "titulo", "")).strip().casefold(),
                re.sub(r"\s+", " ", getattr(vaga, "empresa", "")).strip().casefold(),
                re.sub(r"\s+", " ", getattr(vaga, "cidade", "")).strip().casefold(),
            ))
        if chave in vistos:
            continue
        vistos.add(chave)
        resultado.append(vaga)
        if len(resultado) >= max_resultados:
            break
    return resultado

def _ancestral_cartao(ancora):
    candidato = ancora
    for _ in range(7):
        if candidato.parent is None:
            break
        candidato = candidato.parent
        texto = candidato.get_text(" ", strip=True)
        classes = " ".join(candidato.get("class", [])).lower() if hasattr(candidato, "get") else ""
        # Cartão provável: texto com contexto, sem subir até body/documento inteiro.
        if 45 <= len(texto) <= 5000 and (
            candidato.name in {"article", "li"} or
            any(t in classes for t in ("job", "card", "result", "vacancy", "listing", "vaga"))
        ):
            return candidato
    return candidato


def _selecionar_texto(container, seletores: tuple[str, ...]) -> str:
    for seletor in seletores:
        tag = container.select_one(seletor)
        if tag:
            texto = _texto(tag.get_text(" ", strip=True), 1800)
            if texto:
                return texto
    return ""


def _link_parece_vaga(href: str, host: str) -> bool:
    h = href.lower()
    if "indeed." in host:
        return any(x in h for x in ("jk=", "/viewjob", "/rc/clk", "/pagead/clk"))
    if "linkedin." in host:
        return "/jobs/view/" in h or "currentjobid=" in h
    if "infojobs." in host:
        return bool(re.search(r"__\d+\.aspx", h))
    if "vagas.com" in host:
        return bool(re.search(r"/vagas/v\d+", h))
    return bool(re.search(r"/(?:vaga|vagas|job|jobs|oportunidade|oportunidades)/", h))


def extrair_cartoes_adaptativos(
    html: str, fonte: str, base_url: str, max_resultados: int = 60
) -> list[Vaga]:
    soup = BeautifulSoup(html or "", "html.parser")
    host = urlparse(base_url).netloc.lower()
    vagas: list[Vaga] = []
    vistos: set[str] = set()
    for ancora in soup.find_all("a", href=True):
        href = str(ancora.get("href") or "").strip()
        if not href or not _link_parece_vaga(href, host):
            continue
        link = urljoin(base_url, href).split("#", 1)[0]
        if link in vistos:
            continue
        card = _ancestral_cartao(ancora)
        titulo = _texto(ancora.get_text(" ", strip=True), 240)
        if not titulo or len(titulo) < 3:
            titulo = _selecionar_texto(card, ("h1", "h2", "h3", "h4", "[data-testid*=title]", ".title"))
        if not titulo or titulo.lower() in {"candidatar-se", "saiba mais", "ver vaga", "apply"}:
            continue

        empresa = _selecionar_texto(card, (
            '[data-testid*=company]', '[class*=company]', '[class*=employer]',
            '[itemprop=hiringOrganization]',
        ))
        local = _selecionar_texto(card, (
            '[data-testid*=location]', '[class*=location]', '[class*=local]',
            '[itemprop=jobLocation]',
        ))
        data_tag = card.find("time")
        data = (data_tag.get("datetime") or _texto(data_tag.get_text(), 80)) if data_tag else ""
        if not data:
            achado = _DATE_RE.search(card.get_text(" ", strip=True))
            data = achado.group(0) if achado else ""

        descricao = _selecionar_texto(card, (
            '[data-testid*=description]', '[class*=description]', '[class*=summary]',
            '[class*=snippet]',
        ))
        if not descricao:
            paragrafos = [
                _texto(p.get_text(" ", strip=True), 1500)
                for p in card.find_all(["p", "div"])
                if len(p.get_text(" ", strip=True)) >= 55
            ]
            descricao = max(paragrafos, key=len, default="")

        texto_cartao = card.get_text(" ", strip=True)
        if not local:
            # Heurística conservadora; só aceita padrões explícitos de cidade/UF.
            m = re.search(r"\b([A-ZÀ-Ý][\wÀ-ÿ .'-]{2,50})\s*[,/–-]\s*([A-Z]{2})\b", texto_cartao)
            local = f"{m.group(1).strip()} / {m.group(2)}" if m else ""
        vistos.add(link)
        vagas.append(Vaga(
            titulo=titulo, empresa=empresa, cidade=local, data_publicacao=data,
            link=link, descricao=descricao[:4000], fonte=fonte,
        ))
        if len(vagas) >= max_resultados:
            break
    return vagas


def extrair_vagas_adaptativo(
    html: str, fonte: str, base_url: str, max_resultados: int = 60
) -> tuple[list[Vaga], str]:
    jsonld = extrair_jsonld(html, fonte, base_url)
    microdata = extrair_microdata(html, fonte, base_url)
    cartoes = extrair_cartoes_adaptativos(html, fonte, base_url, max_resultados)
    todas = mesclar_vagas(jsonld, microdata, max_resultados)
    todas = mesclar_vagas(todas, cartoes, max_resultados)
    estrategias = []
    if jsonld:
        estrategias.append("Schema.org JobPosting JSON-LD")
    if microdata:
        estrategias.append("Schema.org JobPosting microdata")
    if cartoes:
        estrategias.append("cartões adaptativos por âncoras/cabeçalhos")
    return todas[:max_resultados], " + ".join(estrategias) if estrategias else "nenhuma estrutura de vaga reconhecida"
