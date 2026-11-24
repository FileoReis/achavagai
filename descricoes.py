"""
descricoes.py
"Análise profunda": muitas vagas chegam dos sites só com o título e uma linha de
descrição. Para a IA dar uma nota confiável, este módulo abre a página de cada vaga
que veio sem descrição suficiente e extrai o texto dela. O resultado vai para
`vaga.descricao` e é usado na avaliação da IA.

Como o texto é extraído (do mais confiável ao menos):
1. JSON-LD "JobPosting" (dado estruturado que muitos portais publicam para o Google).
2. Blocos da página cujo id/classe indicam descrição da vaga.
3. Elementos <article> ou <main>.
4. Parágrafos e itens de lista da página.
5. A meta description (curta, último recurso).

Cuidados embutidos:
- Os links vêm de páginas da internet, então nunca são abertos se apontarem para o
  próprio computador ou para a rede local (veja url_segura).
- Respeita a pausa DESCRICAO_DELAY_SECONDS entre as requisições, por site.
- Sites listados em HOSTS_SEM_ANALISE_PROFUNDA (padrão: LinkedIn) são pulados.
- Qualquer falha em uma página é ignorada: a vaga continua com a descrição que tinha.

Configurações (config.py): QUANTIDADE_ANALISE_PROFUNDA, DESCRICAO_MINIMA_CARACTERES,
DESCRICAO_DELAY_SECONDS, HOSTS_SEM_ANALISE_PROFUNDA, HEADERS.
"""

from __future__ import annotations

import html as html_lib
import ipaddress
import json
import re
import socket
import time
from typing import Callable
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

import config

LIMITE_DESCRICAO = 4000          # caracteres guardados por vaga
TAMANHO_MAXIMO_PAGINA = 2_000_000
MAX_REDIRECIONAMENTOS = 3
TIMEOUT = (8, 20)                # (conexão, leitura) em segundos

_dormir = time.sleep             # os testes trocam por funções falsas
_agora = time.monotonic


def _cfg(nome: str, padrao):
    return getattr(config, nome, padrao)


# ---------------------------------------------------------------------------
# Segurança: só abrir endereços públicos
# ---------------------------------------------------------------------------

def _ip_publico(ip) -> bool:
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def _host_publico(host: str) -> bool:
    """False se o nome/endereço aponta para o próprio computador, rede local,
    endereço reservado ou não resolve. É uma proteção "melhor esforço" (o DNS pode
    mudar entre a checagem e a conexão), suficiente para um programa de uso pessoal."""
    try:  # endereço IP escrito direto na URL: confere sem perguntar ao DNS
        return _ip_publico(ipaddress.ip_address(host.strip("[]")))
    except ValueError:
        pass
    try:
        enderecos = socket.getaddrinfo(host, None)
    except (socket.gaierror, UnicodeError, OSError):
        return False
    if not enderecos:
        return False
    for info in enderecos:
        try:
            if not _ip_publico(ipaddress.ip_address(info[4][0].split("%")[0])):
                return False
        except ValueError:
            return False
    return True


def url_segura(url: str) -> bool:
    """True se a URL é http(s) e o servidor está na internet pública."""
    try:
        partes = urlsplit(url or "")
    except ValueError:
        return False
    if partes.scheme not in ("http", "https") or not partes.hostname:
        return False
    return _host_publico(partes.hostname)


def _host_ignorado(url: str, hosts: tuple[str, ...]) -> bool:
    host = (urlsplit(url or "").hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in hosts)


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

def _baixar_pagina(url: str, sessao: requests.Session) -> bytes | None:
    """Baixa o HTML seguindo até MAX_REDIRECIONAMENTOS, checando cada destino
    com url_segura. Devolve None em qualquer problema."""
    atual = url
    for _ in range(MAX_REDIRECIONAMENTOS + 1):
        if not url_segura(atual):
            return None
        try:
            resposta = sessao.get(
                atual, headers=_cfg("HEADERS", {}), timeout=TIMEOUT, allow_redirects=False, stream=True
            )
        except requests.RequestException:
            return None
        try:
            if resposta.status_code in (301, 302, 303, 307, 308):
                destino = resposta.headers.get("Location")
                if not destino:
                    return None
                atual = urljoin(atual, destino)
                continue
            if resposta.status_code != 200:
                return None
            tipo = (resposta.headers.get("Content-Type") or "").lower()
            if tipo and "html" not in tipo and "xml" not in tipo:
                return None
            pedacos, total = [], 0
            for pedaco in resposta.iter_content(65536):
                total += len(pedaco)
                if total > TAMANHO_MAXIMO_PAGINA:
                    return None
                pedacos.append(pedaco)
            return b"".join(pedacos)
        finally:
            resposta.close()
    return None


# ---------------------------------------------------------------------------
# Extração do texto
# ---------------------------------------------------------------------------

_TAGS_RUIDO = ("script", "style", "noscript", "nav", "footer", "header", "aside", "form", "svg", "iframe", "button")
_PISTA_FORTE_RE = re.compile(r"descri|job-?desc|job-?detail|posting-?desc", re.IGNORECASE)
_PISTA_FRACA_RE = re.compile(r"vaga|detalhe|requisit|posting|conteudo|content", re.IGNORECASE)
_PISTA_RUIDO_RE = re.compile(
    r"coment|comment|relacionad|related|rodape|footer|menu|nav|share|compartilh|cookie|banner|sidebar|breadcrumb",
    re.IGNORECASE,
)
_BLOQUEIO_RE = re.compile(
    r"captcha|verify you are (?:a )?human|are you (?:a )?robot|access denied|acesso negado|just a moment|"
    r"unusual traffic|attention required",
    re.IGNORECASE,
)


def _texto_de(elemento) -> str:
    return re.sub(r"\s+", " ", elemento.get_text(" ", strip=True)).strip()


def _html_para_texto(trecho: str) -> str:
    """O campo description do JSON-LD costuma ser HTML (às vezes com os sinais
    escapados como &lt;p&gt;). Devolve só o texto."""
    if "&lt;" in trecho and "<" not in trecho:
        trecho = html_lib.unescape(trecho)
    return _texto_de(BeautifulSoup(trecho, "html.parser"))


def _percorrer(dados):
    """Visita todos os dicionários de um JSON-LD (inclusive dentro de @graph)."""
    pilha = [dados]
    while pilha:
        atual = pilha.pop()
        if isinstance(atual, dict):
            yield atual
            pilha.extend(valor for valor in atual.values() if isinstance(valor, (dict, list)))
        elif isinstance(atual, list):
            pilha.extend(atual)


def _descricao_jsonld(soup: BeautifulSoup) -> str:
    for script in soup.find_all("script", type=re.compile(r"ld\+json", re.IGNORECASE)):
        try:
            dados = json.loads(script.string or script.get_text() or "", strict=False)
        except ValueError:
            continue
        for item in _percorrer(dados):
            tipos = item.get("@type")
            tipos = [tipos] if isinstance(tipos, str) else (tipos or [])
            descricao = item.get("description")
            if "JobPosting" in tipos and isinstance(descricao, str) and descricao.strip():
                return _html_para_texto(descricao)
    return ""


# Nomes de classe que temas de WordPress e portais de vagas usam para o TEXTO da vaga.
_CLASSES_DE_CONTEUDO = {
    "entry-content", "post-content", "post_content", "the-content", "entry-body", "post-body",
    "article-content", "single-content", "td-post-content", "job-description", "job_description",
    "jobdescription", "descricao-vaga", "vaga-descricao",
}


def _densidade_de_links(elemento) -> float:
    """Parte do texto do bloco que está dentro de links. Menus, listas de categorias e "vagas
    relacionadas" são quase só links (perto de 1); o texto de uma vaga quase não tem."""
    total = len(_texto_de(elemento))
    if not total:
        return 1.0
    return sum(len(_texto_de(a)) for a in elemento.find_all("a")) / total


def _bloco_de_conteudo(soup: BeautifulSoup) -> str:
    melhor = ""
    for elemento in soup.find_all(["div", "section", "article", "main"]):
        classes = {c.lower() for c in (elemento.get("class") or [])}
        if not classes & _CLASSES_DE_CONTEUDO:
            continue
        texto = _texto_de(elemento)
        if len(texto) >= 100 and len(texto) > len(melhor) and _densidade_de_links(elemento) <= 0.5:
            melhor = texto
    return melhor


def _melhor_bloco(soup: BeautifulSoup, pista: re.Pattern) -> str:
    melhor = ""
    for elemento in soup.find_all(["div", "section", "article", "main"]):
        pistas = " ".join(filter(None, [elemento.get("id") or "", " ".join(elemento.get("class") or [])]))
        if not pistas or not pista.search(pistas) or _PISTA_RUIDO_RE.search(pistas):
            continue
        texto = _texto_de(elemento)
        if 200 <= len(texto) <= 12000 and len(texto) > len(melhor) and _densidade_de_links(elemento) <= 0.5:
            melhor = texto
    return melhor


def _meta_descricao(soup: BeautifulSoup) -> str:
    for atributos in ({"property": "og:description"}, {"name": "description"}):
        meta = soup.find("meta", attrs=atributos)
        if meta and meta.get("content", "").strip():
            return re.sub(r"\s+", " ", meta["content"]).strip()
    return ""


# ---------------------------------------------------------------------------
# Data de publicação
# ---------------------------------------------------------------------------
# Portais regionais quase nunca informam a data na lista de resultados, mas a página da
# vaga mostra (ex.: "9 de abril de 2026"). Sem ela, uma vaga de sete meses atrás passa
# pelo filtro de idade, que só descarta o que tem data.

_DATA_ISO_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_DATA_POR_EXTENSO_RE = re.compile(r"\b\d{1,2}\s+de\s+[a-zA-Zçãéúí]{3,9}\.?\s+de\s+\d{4}\b")
_AREA_SECUNDARIA_RE = re.compile(r"comment|related|similar|sidebar|widget|recent", re.IGNORECASE)


def _data_do_atributo(valor) -> str:
    achou = _DATA_ISO_RE.match((valor or "").strip())
    return achou.group(0) if achou else ""


def extrair_data_publicacao(html) -> str:
    """Data em que a vaga foi publicada, lida da página ("" se não achar). Ordem de
    confiança: dados estruturados da vaga (datePosted), metadados do artigo, tag <time>
    de publicação e, por último, uma data por extenso no começo do texto do artigo.
    Devolve "AAAA-MM-DD" ou o texto da data (ex.: "9 de abril de 2026"); o filtro de
    datas entende os dois."""
    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception:
        return ""

    for script in soup.find_all("script", type=re.compile(r"ld\+json", re.IGNORECASE)):
        try:
            dados = json.loads(script.string or script.get_text() or "", strict=False)
        except ValueError:
            continue
        for item in _percorrer(dados):
            tipos = item.get("@type")
            tipos = [tipos] if isinstance(tipos, str) else (tipos or [])
            if "JobPosting" in tipos:
                data = _data_do_atributo(str(item.get("datePosted") or ""))
                if data:
                    return data

    for atributos in ({"property": "article:published_time"}, {"itemprop": "datePublished"},
                      {"name": "article:published_time"}, {"property": "og:article:published_time"}):
        meta = soup.find("meta", attrs=atributos)
        data = _data_do_atributo(meta.get("content", "")) if meta else ""
        if data:
            return data

    for tempo in soup.find_all("time", attrs={"datetime": True}):
        classes = " ".join(tempo.get("class") or []).lower()
        if "publish" in classes or "entry-date" in classes or tempo.get("itemprop") == "datePublished":
            data = _data_do_atributo(tempo["datetime"])
            if data:
                return data

    artigo = soup.find("article") or soup.find("main")
    if artigo:
        for tempo in artigo.find_all("time", attrs={"datetime": True}):
            if tempo.find_parent(class_=_AREA_SECUNDARIA_RE):
                continue
            data = _data_do_atributo(tempo["datetime"])
            if data:
                return data
        achou = _DATA_POR_EXTENSO_RE.search(_texto_de(artigo)[:600])
        if achou:
            return achou.group(0)
    return ""


def extrair_descricao(html) -> str:
    """Extrai o texto da descrição de uma vaga a partir do HTML (str ou bytes).
    Devolve "" se não achar nada confiável ou se a página parecer um bloqueio
    (captcha, "acesso negado")."""
    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception:
        return ""

    texto = _descricao_jsonld(soup)
    if not texto:
        meta = _meta_descricao(soup)  # lida antes de remover as tags de ruído
        for tag in soup.find_all(list(_TAGS_RUIDO)):
            tag.decompose()
        texto = (_bloco_de_conteudo(soup) or _melhor_bloco(soup, _PISTA_FORTE_RE)
                 or _melhor_bloco(soup, _PISTA_FRACA_RE))
        if not texto:
            for nome in ("article", "main"):
                elemento = soup.find(nome)
                if elemento and len(_texto_de(elemento)) >= 200 and _densidade_de_links(elemento) <= 0.5:
                    texto = _texto_de(elemento)
                    break
        if not texto:
            paragrafos = " ".join(_texto_de(p) for p in soup.find_all(["p", "li"]))
            texto = paragrafos if len(paragrafos) >= 200 else ""
        if not texto:
            texto = meta

    texto = re.sub(r"\s+", " ", texto).strip()
    if len(texto) < 60 or (len(texto) < 1500 and _BLOQUEIO_RE.search(texto)):
        return ""
    return texto[:LIMITE_DESCRICAO]


def buscar_descricao(url: str, sessao: requests.Session | None = None) -> str:
    """Abre a página da vaga e devolve o texto da descrição ("" se não der)."""
    sessao = sessao or requests.Session()
    conteudo = _baixar_pagina(url, sessao)
    return extrair_descricao(conteudo) if conteudo else ""


def buscar_pagina(url: str, sessao: requests.Session | None = None) -> tuple[str, str]:
    """Abre a página da vaga e devolve (descrição, data de publicação). O que não for
    encontrado volta como ""."""
    sessao = sessao or requests.Session()
    conteudo = _baixar_pagina(url, sessao)
    if not conteudo:
        return "", ""
    return extrair_descricao(conteudo), extrair_data_publicacao(conteudo)


# ---------------------------------------------------------------------------
# Etapa completa
# ---------------------------------------------------------------------------

def enriquecer_descricoes(
    vagas: list,
    limite: int | None = None,
    minimo_caracteres: int | None = None,
    atraso: float | None = None,
    hosts_ignorados: tuple[str, ...] | None = None,
    baixar: Callable[[str], str | tuple[str, str]] | None = None,
    ao_avancar: Callable[[int, int], None] | None = None,
) -> dict:
    """Busca a descrição completa das vagas que vieram com pouco texto, na ordem
    recebida, até `limite` páginas. Só substitui a descrição quando a nova é maior, e
    só preenche `data_publicacao` quando a vaga veio sem data.
    `baixar(url)` devolve o texto, ou (texto, data) (os testes usam as duas formas).
    Devolve estatísticas: {"tentadas", "enriquecidas", "falhas", "ignoradas", "datas"}."""
    limite = int(limite if limite is not None else _cfg("QUANTIDADE_ANALISE_PROFUNDA", 25))
    minimo = int(minimo_caracteres if minimo_caracteres is not None else _cfg("DESCRICAO_MINIMA_CARACTERES", 400))
    atraso = float(atraso if atraso is not None else _cfg("DESCRICAO_DELAY_SECONDS", 1.0))
    ignorados = tuple(h.lower() for h in (hosts_ignorados if hosts_ignorados is not None
                                          else _cfg("HOSTS_SEM_ANALISE_PROFUNDA", ())))
    estatisticas = {"tentadas": 0, "enriquecidas": 0, "falhas": 0, "ignoradas": 0, "datas": 0}
    if limite <= 0:
        return estatisticas

    if baixar is None:
        sessao = requests.Session()
        baixar = lambda url: buscar_pagina(url, sessao)  # noqa: E731

    alvo = [v for v in vagas if len(getattr(v, "descricao", "") or "") < minimo and getattr(v, "link", "")]
    ultimo_acesso: dict[str, float] = {}
    for vaga in alvo:
        if estatisticas["tentadas"] >= limite:
            break
        if _host_ignorado(vaga.link, ignorados):
            estatisticas["ignoradas"] += 1
            continue

        host = (urlsplit(vaga.link).hostname or "").lower()
        espera = atraso - (_agora() - ultimo_acesso.get(host, -1e9))
        if espera > 0:
            _dormir(espera)

        estatisticas["tentadas"] += 1
        if ao_avancar:
            ao_avancar(estatisticas["tentadas"], min(limite, len(alvo)))
        try:
            lido = baixar(vaga.link)
        except Exception:  # uma página com problema nunca derruba a busca
            lido = ""
        texto, data = lido if isinstance(lido, tuple) else (lido, "")
        ultimo_acesso[host] = _agora()

        if data and not (getattr(vaga, "data_publicacao", "") or "").strip():
            vaga.data_publicacao = data
            estatisticas["datas"] += 1

        if texto and len(texto) > len(getattr(vaga, "descricao", "") or ""):
            vaga.descricao = texto
            estatisticas["enriquecidas"] += 1
        else:
            estatisticas["falhas"] += 1
    return estatisticas
