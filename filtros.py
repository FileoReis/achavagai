"""
filtros.py
Funções "puras" (sem rede, sem IA, sem tela) que tratam a lista de vagas:
datas de publicação, região (UF), vagas duplicadas e enriquecimento de campos
vazios. Ficam aqui, separadas do main.py, para poderem ser testadas sozinhas
(veja a pasta tests/).

Todas trabalham com qualquer objeto que tenha os atributos da classe Vaga de
scrapers/base.py: titulo, empresa, cidade, descricao, link, fonte,
data_publicacao e termo_busca.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, timedelta
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from dateutil import parser as dateparser

from config import BAIRROS_RJ, CIDADES_RJ, UF_ALVO

# ---------------------------------------------------------------------------
# Texto
# ---------------------------------------------------------------------------


def normalizar_texto(texto: str) -> str:
    """Minúsculas, sem acentos, só letras/números separados por um espaço."""
    sem_acento = unicodedata.normalize("NFKD", texto or "")
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", sem_acento.lower()).strip()


def _normalizar_mantendo_mais(texto: str) -> str:
    """Igual a normalizar_texto, mas preserva o "+" (usado em "30+ dias")."""
    sem_acento = unicodedata.normalize("NFKD", texto or "")
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9+]+", " ", sem_acento.lower()).strip()


def dividir_palavras_chave(texto: str) -> list[str]:
    """Permite buscar vários cargos de uma vez, separados por vírgula."""
    termos = [t.strip() for t in texto.split(",")]
    return [t for t in termos if t]


# ---------------------------------------------------------------------------
# Datas de publicação
# ---------------------------------------------------------------------------

_MESES = {
    "janeiro": 1, "fevereiro": 2, "marco": 3, "abril": 4, "maio": 5, "junho": 6,
    "julho": 7, "agosto": 8, "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12,
    "jan": 1, "fev": 2, "mar": 3, "abr": 4, "mai": 5, "jun": 6,
    "jul": 7, "ago": 8, "set": 9, "out": 10, "nov": 11, "dez": 12,
}

_UNIDADES_EM_DIAS = {
    "minuto": 1 / 1440, "min": 1 / 1440, "minute": 1 / 1440,
    "hora": 1 / 24, "hr": 1 / 24, "h": 1 / 24, "hour": 1 / 24,
    "dia": 1, "d": 1, "day": 1,
    "semana": 7, "sem": 7, "week": 7,
    "mes": 30, "meses": 30, "month": 30,
    "ano": 365, "year": 365,
}

_RELATIVA_RE = re.compile(
    r"(\d+)\s*(\+)?\s*(minutos?|min|minutes?|horas?|hr|h|hours?|dias?|d|days?|semanas?|sem|weeks?|meses|mes|months?|anos?|years?)\b"
)
_ISO_RE = re.compile(r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?")
_NUMERICA_BR_RE = re.compile(r"(?<!\d)(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4}|\d{2})(?!\d)")
_TEXTUAL_BR_RE = re.compile(r"(?<!\d)(\d{1,2})\s*(?:de\s+)?([a-z]{3,9})\.?(?:\s*(?:de\s+)?(\d{4}))?(?!\d)")


def parse_data_publicacao(texto: str, agora: datetime | None = None) -> datetime | None:
    """Converte o texto de data que os sites mostram em um datetime, ou None se
    não for possível entender (nesse caso a vaga não é descartada pelo filtro de data).

    Entende: "hoje", "ontem", "há 3 dias", "3 days ago", "há mais de 30 dias",
    "03/11/2026" (dia primeiro, como no Brasil), "2026-11-03", "3 de novembro de
    2026", "3 nov".

    Atenção: o dateutil puro lê "03/11/2026" como 11 de março (formato americano)
    e, com dayfirst=True, passa a ler datas ISO ("2026-03-11") ao contrário. Por
    isso cada formato é tratado separadamente aqui."""
    if not texto or not str(texto).strip():
        return None
    texto = str(texto).strip()
    referencia = agora or datetime.now()
    minusculo = normalizar_texto(texto)

    # 1) Datas relativas
    if re.search(r"\b(hoje|agora|instantes|today|just now|just posted|recem|recentemente)\b", minusculo):
        return referencia
    if re.search(r"\b(ontem|yesterday)\b", minusculo):
        return referencia - timedelta(days=1)
    achado = _RELATIVA_RE.search(_normalizar_mantendo_mais(texto))
    if achado and re.search(r"\b(ha|atras|ago|ultimos?|postado|publicad[oa]|active|ativa)\b", minusculo):
        quantidade = int(achado.group(1))
        unidade = achado.group(3)
        chave = next((u for u in sorted(_UNIDADES_EM_DIAS, key=len, reverse=True) if unidade.startswith(u)), None)
        if chave:
            dias = quantidade * _UNIDADES_EM_DIAS[chave]
            if achado.group(2) or "mais de" in minusculo:  # "30+ dias" / "mais de 30 dias"
                dias += 1
            return referencia - timedelta(days=dias)

    # 2) ISO (2026-11-03 ou 2026-11-03T10:00:00Z)
    iso = _ISO_RE.search(texto)
    if iso:
        try:
            return dateparser.isoparse(iso.group(0))
        except (ValueError, OverflowError):
            pass

    # 3) Numérica brasileira: dia/mês/ano
    numerica = _NUMERICA_BR_RE.search(texto)
    if numerica:
        dia, mes, ano = int(numerica.group(1)), int(numerica.group(2)), int(numerica.group(3))
        if ano < 100:
            ano += 2000
        if mes > 12 >= dia:  # veio no formato mês/dia
            dia, mes = mes, dia
        try:
            return datetime(ano, mes, dia)
        except ValueError:
            return None

    # 4) Textual em português: "3 de novembro de 2026", "3 nov"
    for textual in _TEXTUAL_BR_RE.finditer(minusculo):
        mes = _MESES.get(textual.group(2))
        if not mes:
            continue
        dia = int(textual.group(1))
        ano = int(textual.group(3)) if textual.group(3) else referencia.year
        try:
            data = datetime(ano, mes, dia)
        except ValueError:
            continue
        if not textual.group(3) and data > referencia + timedelta(days=1):
            data = data.replace(year=data.year - 1)  # "25 dez" lido em novembro = dezembro passado
        return data

    # 5) Último recurso: deixa o dateutil tentar (só formatos sem ambiguidade)
    try:
        return dateparser.parse(texto)
    except (ValueError, OverflowError, TypeError):
        return None


def idade_em_dias(data_publicacao: str, agora: datetime | None = None) -> int | None:
    """Há quantos dias a vaga foi publicada. None se a data estiver vazia ou em
    formato não reconhecido (a vaga não é descartada pelo filtro de data, já que
    não dá para confirmar que está velha)."""
    data = parse_data_publicacao(data_publicacao, agora)
    if data is None:
        return None
    if data.tzinfo:
        base = datetime.now(data.tzinfo) if agora is None else agora.replace(tzinfo=data.tzinfo)
    else:
        base = agora or datetime.now()
    return max(0, (base - data).days)


def filtrar_por_data(vagas: list, dias_maximo: int, agora: datetime | None = None) -> tuple[list, int, int]:
    """Remove vagas cuja data de publicação seja mais antiga que `dias_maximo`.
    Vagas sem data identificável são mantidas (não há como confirmar a idade),
    mas contadas separadamente para informar o usuário.
    Retorna (vagas_filtradas, quantidade_removida_por_idade, quantidade_sem_data)."""
    filtradas = []
    removidas_por_idade = 0
    sem_data = 0

    for vaga in vagas:
        idade = idade_em_dias(getattr(vaga, "data_publicacao", ""), agora)
        if idade is None:
            sem_data += 1
            filtradas.append(vaga)
        elif idade <= dias_maximo:
            filtradas.append(vaga)
        else:
            removidas_por_idade += 1

    return filtradas, removidas_por_idade, sem_data


# ---------------------------------------------------------------------------
# Vagas encerradas: "Comparecer no dia 24/08" quando 24/08 já passou
# ---------------------------------------------------------------------------
# Portais regionais costumam publicar vagas de comparecimento presencial com a data
# no próprio título ("Auxiliar de CPD, Supermercados X, Comparecer no dia 24/08") e
# quase nunca informam a data de publicação, então o filtro de idade não as pega.
# Aqui o programa procura datas ligadas a comparecimento, entrevista, inscrição ou
# prazo no título e no começo da descrição, e descarta a vaga se a data já passou.
#
# Datas sem ano: vale a ocorrência futura mais próxima SE ela estiver dentro de um
# horizonte curto (60 dias para comparecimento, 180 para prazos de inscrição); senão
# a data é tratada como passada. Assim "24/08" visto em novembro é de agosto (já
# passou), mas "05/01" visto em novembro é de janeiro do ano que vem (ainda vale).

_GATILHOS_DATA_RE = re.compile(
    r"\b(?:(?P<comparecimento>comparec\w*|entrevistas?|seletivas?|feirao|mutirao|plantao\s+de\s+vagas)"
    r"|(?P<prazo>inscric\w*|inscreva-?se|prazo|encerra\w*|validade|valid[oa]\s+ate|data\s+limite|ate\s+(?:o\s+)?dia))"
)
_DATA_BARRA_RE = re.compile(r"(?<![\d/.\-])(\d{1,2})([/\-])(\d{1,2})(?:\2(\d{4}|\d{2}))?(?!\d)")
_DATA_PONTO_RE = re.compile(r"(?<![\d/.\-])(\d{2})\.(\d{2})(?:\.(\d{4}|\d{2}))?(?!\d)")
_DATA_EXTENSO_RE = re.compile(r"(?<!\d)(\d{1,2})\s+de\s+([a-z]{3,9})\.?(?:\s+de\s+(\d{4}))?")

# Palavras que mostram que a data é de INÍCIO ou de publicação, e não de fim.
_PALAVRAS_DE_INICIO = ("desde", "a partir", "partir de", "publicad", "postad", "inicia", "inicio", "abertura")
_JANELA_DATA = 70          # caracteres lidos depois da palavra-gatilho
_TRECHO_DESCRICAO = 800    # só o começo da descrição é examinado
HORIZONTE_COMPARECIMENTO = 60
HORIZONTE_PRAZO = 180


def _hoje() -> date:
    return date.today()  # função à parte para os testes poderem fixar o "hoje"


def _sem_acentos_minusculo(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in sem_acento if not unicodedata.combining(c)).lower()


def _ano(texto: str | None) -> int | None:
    if not texto:
        return None
    ano = int(texto)
    return ano + 2000 if ano < 100 else ano


def _achar_datas(janela: str) -> list[tuple[int, int, int, int | None]]:
    """(posição, dia, mês, ano ou None) de cada data escrita no trecho."""
    achadas = []
    for m in _DATA_BARRA_RE.finditer(janela):
        achadas.append((m.start(), int(m.group(1)), int(m.group(3)), _ano(m.group(4))))
    for m in _DATA_PONTO_RE.finditer(janela):
        achadas.append((m.start(), int(m.group(1)), int(m.group(2)), _ano(m.group(3))))
    for m in _DATA_EXTENSO_RE.finditer(janela):
        mes = _MESES.get(m.group(2))
        if mes:
            achadas.append((m.start(), int(m.group(1)), mes, _ano(m.group(3))))
    return sorted(achadas)


def _resolver_data(dia: int, mes: int, ano: int | None, hoje: date, horizonte: int) -> date | None:
    if not (1 <= mes <= 12 and 1 <= dia <= 31):
        return None
    if ano is not None:
        try:
            return date(ano, mes, dia)
        except ValueError:
            return None
    candidatas = []
    for a in (hoje.year - 1, hoje.year, hoje.year + 1):
        try:
            candidatas.append(date(a, mes, dia))
        except ValueError:  # 29/02 em ano que não é bissexto
            continue
    if not candidatas:
        return None
    futuras = [d for d in candidatas if d >= hoje]
    passadas = [d for d in candidatas if d < hoje]
    if futuras and (min(futuras) - hoje).days <= horizonte:
        return min(futuras)
    return max(passadas) if passadas else min(futuras)


def data_limite_da_vaga(vaga, hoje: date | None = None) -> date | None:
    """A data mais tardia de comparecimento, entrevista, inscrição ou prazo citada no
    título ou no começo da descrição da vaga. None se a vaga não cita nenhuma."""
    hoje = hoje or _hoje()
    titulo = getattr(vaga, "titulo", "") or ""
    descricao = (getattr(vaga, "descricao", "") or "")[:_TRECHO_DESCRICAO]
    texto = _sem_acentos_minusculo(f"{titulo}\n{descricao}")

    melhor = None
    for gatilho in _GATILHOS_DATA_RE.finditer(texto):
        horizonte = HORIZONTE_COMPARECIMENTO if gatilho.group("comparecimento") else HORIZONTE_PRAZO
        janela = texto[gatilho.end(): gatilho.end() + _JANELA_DATA].split("\n")[0].split("|")[0]
        for posicao, dia, mes, ano in _achar_datas(janela):
            if any(palavra in janela[:posicao] for palavra in _PALAVRAS_DE_INICIO):
                continue
            data = _resolver_data(dia, mes, ano, hoje, horizonte)
            if data is not None and (melhor is None or data > melhor):
                melhor = data
    return melhor


def vaga_encerrada(vaga, hoje: date | None = None) -> bool:
    """True se a vaga cita uma data de comparecimento/prazo e essa data já passou."""
    hoje = hoje or _hoje()
    data = data_limite_da_vaga(vaga, hoje)
    return data is not None and data < hoje


def motivo_de_encerramento(vaga, hoje: date | None = None) -> str | None:
    """Texto curto explicando por que a vaga está encerrada, ou None se ainda vale."""
    hoje = hoje or _hoje()
    data = data_limite_da_vaga(vaga, hoje)
    if data is not None and data < hoje:
        return f"a data de comparecimento ou prazo ({data:%d/%m/%Y}) já passou"
    return None


def filtrar_encerradas(vagas: list, hoje: date | None = None) -> tuple[list, list[tuple]]:
    """Separa as vagas que ainda valem das encerradas.
    Retorna (vagas_validas, [(vaga_encerrada, data_limite), ...])."""
    hoje = hoje or _hoje()
    validas, encerradas = [], []
    for vaga in vagas:
        data = data_limite_da_vaga(vaga, hoje)
        if data is not None and data < hoje:
            encerradas.append((vaga, data))
        else:
            validas.append(vaga)
    return validas, encerradas


# ---------------------------------------------------------------------------
# Região (UF)
# ---------------------------------------------------------------------------

UFS_BRASIL = {
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG", "PA",
    "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO",
}

_ESTADOS_POR_NOME = {
    "acre": "AC", "alagoas": "AL", "amapa": "AP", "amazonas": "AM", "bahia": "BA", "ceara": "CE",
    "distrito federal": "DF", "espirito santo": "ES", "goias": "GO", "maranhao": "MA",
    "mato grosso": "MT", "mato grosso do sul": "MS", "minas gerais": "MG", "para": "PA",
    "paraiba": "PB", "parana": "PR", "pernambuco": "PE", "piaui": "PI", "rio de janeiro": "RJ",
    "rio grande do norte": "RN", "rio grande do sul": "RS", "rondonia": "RO", "roraima": "RR",
    "santa catarina": "SC", "sao paulo": "SP", "sergipe": "SE", "tocantins": "TO",
}

_UF_SEPARADA_RE = re.compile(r"(?:/|,|\s-\s|\s–\s|\()\s*([A-Z]{2})\b")
_REMOTO_RE = re.compile(r"\b(remot[oa]|home\s*office|trabalho\s+remoto|teletrabalho|anywhere)\b", re.IGNORECASE)


def _ufs_em_ordem(local: str) -> list[str]:
    ufs: list[str] = []
    for achado in _UF_SEPARADA_RE.finditer(local or ""):
        uf = achado.group(1)
        if uf in UFS_BRASIL and uf not in ufs:
            ufs.append(uf)
    if not ufs:
        partes = [p.strip() for p in (local or "").split(",") if p.strip()]
        if len(partes) >= 2 and normalizar_texto(partes[-1]) in ("brasil", "brazil"):
            uf = _ESTADOS_POR_NOME.get(normalizar_texto(partes[-2]))
            if uf:
                ufs.append(uf)
    return ufs


def detectar_uf(local: str) -> str | None:
    """Tenta descobrir a UF citada em um texto de local. Entende "Cidade / SP",
    "Cidade, SP", "Cidade - SP", "Cidade (SP)" e o formato do LinkedIn
    "Cidade, Estado, Brasil". Retorna None quando não há UF identificável."""
    ufs = _ufs_em_ordem(local)
    return ufs[0] if ufs else None


def detectar_ufs(local: str) -> set[str]:
    """Todas as UFs citadas no texto (ex.: "Rio de Janeiro/RJ e São Paulo/SP")."""
    return set(_ufs_em_ordem(local))


def filtrar_por_regiao(vagas: list, uf_alvo: str = UF_ALVO) -> tuple[list, int]:
    """Descarta vagas cujo campo `cidade` traga explicitamente um estado (UF)
    diferente do configurado: ex.: "São Paulo / SP" é descartado se `uf_alvo` for
    "RJ". Isso é feito no código (não só confiando na IA) porque a análise de IA
    tratava localização apenas como uma preferência, não uma exclusão.

    Vagas sem UF identificável no campo cidade (a maioria, já que muitos sites não
    estruturam isso) NÃO são descartadas por este filtro: seguem para a IA/TF-IDF
    avaliar normalmente. Vagas remotas (título ou local com "remoto"/"home office")
    também são mantidas. Retorna (vagas_filtradas, quantidade_removida)."""
    if not uf_alvo:
        return list(vagas), 0
    filtradas = []
    removidas = 0
    for vaga in vagas:
        ufs = detectar_ufs(getattr(vaga, "cidade", "") or "")
        if ufs and uf_alvo.upper() not in ufs:
            if _REMOTO_RE.search(f"{getattr(vaga, 'titulo', '')} {getattr(vaga, 'cidade', '')}"):
                filtradas.append(vaga)
                continue
            removidas += 1
            continue
        filtradas.append(vaga)
    return filtradas, removidas


# ---------------------------------------------------------------------------
# Duplicadas
# ---------------------------------------------------------------------------

_PARAMETROS_RASTREIO = {
    "fbclid", "gclid", "trk", "trkinfo", "trackingid", "refid", "ref", "referrer", "from",
    "tk", "vjs", "advn", "adid", "pub", "xkcb", "xpse", "sjdu", "cmp", "cmpid", "position",
    "pagenum", "currentjobid", "lipi", "midtoken", "midsig", "originalsubdomain", "source",
}


def normalizar_link(link: str) -> str:
    """Forma canônica de um link para comparar duplicadas: sem parâmetros de
    rastreamento (utm_*, trk, refId...), sem #fragmento, sem barra final e com o
    domínio em minúsculas. Parâmetros que identificam a vaga (ex.: ?jk= do Indeed,
    ?p= de sites WordPress) são mantidos."""
    if not link:
        return ""
    link = link.strip()
    try:
        partes = urlsplit(link)
    except ValueError:
        return link
    if not partes.scheme or not partes.netloc:
        return link
    consulta = sorted(
        (k, v) for k, v in parse_qsl(partes.query, keep_blank_values=True)
        if k.lower() not in _PARAMETROS_RASTREIO and not k.lower().startswith("utm_")
    )
    dominio = partes.netloc.lower()
    if dominio.startswith("www."):
        dominio = dominio[4:]
    return urlunsplit(("https", dominio, partes.path.rstrip("/") or "/", urlencode(consulta), ""))


def _cidade_base(cidade: str) -> str:
    return normalizar_texto(re.split(r"[,/\-–(]", cidade or "")[0])


def _empresa_base_duplicata(valor: str) -> str:
    """Normaliza sufixos jurídicos comuns para comparar o mesmo empregador.

    Ex.: "Empresa Alfa Ltda." e "Empresa Alfa S/A". A remoção só ocorre no
    final do nome e a chave continua exigindo título e cidade iguais, para não
    juntar empresas apenas parecidas.
    """
    tokens = normalizar_texto(valor).split()
    sufixos = (("sociedade", "anonima"), ("s", "a"), ("s", "c"),
               ("ltda",), ("limitada",), ("eireli",), ("epp",), ("me",), ("sa",))
    alterou = True
    while tokens and alterou:
        alterou = False
        for sufixo in sufixos:
            if len(tokens) > len(sufixo) and tuple(tokens[-len(sufixo):]) == sufixo:
                tokens = tokens[:-len(sufixo)]
                alterou = True
                break
    return " ".join(tokens) or normalizar_texto(valor)


def chave_duplicata(vaga) -> tuple[str, str, str] | None:
    """Chave (título, empresa, cidade) para achar a MESMA vaga publicada em sites
    diferentes, com links diferentes. Reconhece variações de sufixos jurídicos
    do mesmo empregador. Sem empresa, só deduplica quando o link é igual, para
    evitar fundir vagas diferentes que tenham o mesmo título.
    """
    empresa = _empresa_base_duplicata(getattr(vaga, "empresa", "") or "")
    titulo = normalizar_texto(getattr(vaga, "titulo", "") or "")
    cidade = _cidade_base(getattr(vaga, "cidade", "") or "")
    if not empresa or not titulo or not cidade:
        return None
    return (titulo, empresa, cidade)


def _mesclar(principal, outra) -> None:
    """Aproveita da vaga repetida o que faltar na que ficou."""
    if len(getattr(outra, "descricao", "") or "") > len(getattr(principal, "descricao", "") or ""):
        principal.descricao = outra.descricao
    for campo in ("empresa", "cidade", "data_publicacao"):
        if not getattr(principal, campo, "") and getattr(outra, campo, ""):
            setattr(principal, campo, getattr(outra, campo))


def remover_duplicadas(vagas: list) -> list:
    """Remove vagas repetidas: mesmo link (ignorando parâmetros de rastreamento) ou
    mesmo título + empresa + cidade (a mesma vaga em sites diferentes). Da repetida,
    a vaga mantida aproveita a descrição mais completa e os campos que faltavam."""
    por_link: dict[str, object] = {}
    por_chave: dict[tuple, object] = {}
    unicas = []
    for vaga in vagas:
        link = normalizar_link(getattr(vaga, "link", "") or "")
        chave = chave_duplicata(vaga)
        existente = por_link.get(link) if link else None
        if existente is None and chave is not None:
            existente = por_chave.get(chave)
        if existente is not None:
            _mesclar(existente, vaga)
            continue
        if link:
            por_link[link] = vaga
        if chave is not None:
            por_chave[chave] = vaga
        unicas.append(vaga)
    return unicas


# ---------------------------------------------------------------------------
# Enriquecimento
# ---------------------------------------------------------------------------

SEPARADOR_TITULO_RE = re.compile(r"\s[–-]\s")


_SO_UF_RE = re.compile(r"^[A-Z]{2}$")


def _parece_local(trecho: str) -> bool:
    return bool(_SO_UF_RE.match(trecho)) or "RJ" in trecho or any(c.lower() in trecho.lower() for c in CIDADES_RJ)


def enriquecer_vaga(vaga):
    """Tenta preencher empresa/cidade quando vieram vazias, usando o padrão do próprio
    título ("Cargo – Empresa – Local") e a lista de cidades conhecidas."""
    titulo = getattr(vaga, "titulo", "") or ""
    partes = [p.strip() for p in SEPARADOR_TITULO_RE.split(titulo)]

    if not getattr(vaga, "empresa", "") and len(partes) >= 3:
        # "Cargo – Cidade – UF" não tem empresa: o 2º trecho é o local. Antes, "Motorista de
        # Ônibus Urbano – Queimados – RJ" saía com a empresa "Queimados".
        conhecidos = {c.lower() for c in CIDADES_RJ} | {b.lower() for b in BAIRROS_RJ}
        eh_local = partes[1].lower() in conhecidos or (len(partes) == 3 and bool(_SO_UF_RE.match(partes[2])))
        if not eh_local:
            vaga.empresa = partes[1]

    if not getattr(vaga, "cidade", ""):
        # Procura o local de trás para frente, ignorando o cargo: em "Cargo – Empresa –
        # Bairro RJ – Comparecer no dia 24/08" o último trecho é o aviso, não o local.
        for i in range(len(partes) - 1, 0, -1):
            if _parece_local(partes[i]):
                # "Queimados – RJ": a sigla sozinha não diz a cidade, então junta com o trecho anterior
                sozinha = bool(_SO_UF_RE.match(partes[i]))
                vaga.cidade = f"{partes[i - 1]}, {partes[i]}" if sozinha and i - 1 >= 1 else partes[i]
                break
        else:
            cidade_no_titulo = next((c for c in CIDADES_RJ if c.lower() in titulo.lower()), None)
            if cidade_no_titulo:
                vaga.cidade = cidade_no_titulo
    return vaga
