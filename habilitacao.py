"""
habilitacao.py
Compara a CNH do candidato com a CNH que a vaga exige, por regras (sem IA).

Por que existe: "Motorista de Ônibus Urbano, CNH categoria D válida" chegou ao ranking com
nota 75 para um candidato com CNH B. A IA nem sempre aplica essa regra (principalmente
quando a descrição não chegou), e uma exigência legal não deve depender disso. Aqui o
programa lê a categoria no currículo e a exigência na vaga e descarta, antes da IA, as
vagas que o candidato não pode ocupar.

Categorias (Código de Trânsito Brasileiro):
  A = moto | B = carro | C = caminhão | D = ônibus e transporte de passageiros (mais de 8
  lugares) | E = carreta e combinações. Quem tem D também dirige B e C; E também dirige D, C
  e B. B não habilita C, D nem E. A é independente das demais.

De onde vem a exigência da vaga:
- do texto: "CNH categoria D válida", "Hab B", "CNH C ou D", "CNH AB";
- do cargo, mesmo que o texto não cite a CNH: motorista de ônibus pede D, de caminhão pede C,
  de carreta pede E, motoboy pede A. ("Ajudante de motorista" não conta.)

Cuidados contra descartar vaga boa por engano:
- Se o currículo não informa a CNH, nada é descartado aqui (a IA e você decidem).
- Exigência escrita como "diferencial", "desejável" ou "não obrigatória" não elimina.
- Se a vaga cita mais de uma exigência e o candidato cumpre alguma, a vaga fica.
- As letras A e E sozinhas só valem depois da palavra "categoria" ou dentro de uma lista
  ("A/B", "B ou E"); senão "CNH E experiência" seria lido como categoria E, e "CNH A partir
  de..." como categoria A.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

_NIVEIS = "BCDE"  # cada categoria de quatro rodas habilita as anteriores
_TRECHO_DESCRICAO = 1500  # só o começo da descrição é examinado


@dataclass(frozen=True)
class Exigencia:
    letras: frozenset
    todas: bool      # True = precisa de todas as letras ("AB"); False = qualquer uma ("C ou D")
    origem: str      # "texto" (a vaga escreve) ou "cargo" (o cargo exige por lei)


def _sem_acentos_minusculo(texto: str) -> str:
    sem = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in sem if not unicodedata.combining(c)).lower()


# ---------------------------------------------------------------------------
# Leitura de "CNH ..." em um texto
# ---------------------------------------------------------------------------

_GATILHO_RE = re.compile(
    r"(?i:\b(?:cnh|c\.n\.h\.?|habilita[cç][aã]o|hab\.?|"
    r"carteira\s+(?:nacional\s+de\s+habilita[cç][aã]o|de\s+motorista)))(?![\wÀ-ÿ])"
)
_FORA_DE_PALAVRA = r"(?<![A-Za-zÀ-ÿ0-9])"
_SEM_LETRA_DEPOIS = r"(?![A-Za-zÀ-ÿ0-9])"
# Depois da palavra "categoria" vale qualquer letra, maiúscula ou minúscula.
_TOKEN_COM_PREFIXO_RE = re.compile(
    _FORA_DE_PALAVRA + r"(?i:categorias?|cat\.?)\s*[:\-]?\s*(?P<l>(?i:A[B-E]|[A-E]))" + _SEM_LETRA_DEPOIS
)
# Sem a palavra "categoria": B, C e D maiúsculos, pares colados como AB e, só quando vêm em
# uma lista ("A/B", "A, B", "A ou B", "A e B"), também o A e o E sozinhos.
_LISTA_DEPOIS = (
    r"(?=\s*(?:[/,+]|(?i:\b(?:ou|e)\b))\s*(?:(?i:categorias?|cat\.?)\s*)?(?:A[B-E]|[A-E])"
    + _SEM_LETRA_DEPOIS + r")"
)
_TOKEN_SOZINHO_RE = re.compile(
    _FORA_DE_PALAVRA + r"(?P<l>A[B-E]|[BCD]|[AE]" + _LISTA_DEPOIS + r")" + _SEM_LETRA_DEPOIS
)
# Depois de um conector, dentro de uma lista que já começou, o A e o E sozinhos são categorias.
_TOKEN_APOS_CONECTOR_RE = re.compile(
    _FORA_DE_PALAVRA + r"(?:(?i:categorias?|cat\.?)\s*[:\-]?\s*)?(?P<l>A[B-E]|[A-E])" + _SEM_LETRA_DEPOIS
)
# No currículo, onde o próprio candidato escreve a sua CNH, o A sozinho também vale.
_TOKEN_SOZINHO_CURRICULO_RE = re.compile(_FORA_DE_PALAVRA + r"(?P<l>A[B-E]|[A-D])" + _SEM_LETRA_DEPOIS)
_CONECTOR_RE = re.compile(r"\s*(?:/|,|\+|(?i:\bou\b)|(?i:\be\b))\s*")

_DIFERENCIAL_RE = re.compile(
    r"diferencial|desejavel|desejada|preferencia|preferencialmente|opcional|"
    r"nao\s+(?:e\s+)?obrigatori|nao\s+e\s+necessari|nao\s+(?:e\s+)?exigid"
)


def _proximo_token(janela: str, posicao: int, procurar: bool, sozinho: re.Pattern):
    achar = (lambda r: r.search(janela, posicao)) if procurar else (lambda r: r.match(janela, posicao))
    candidatos = [m for m in (achar(_TOKEN_COM_PREFIXO_RE), achar(sozinho)) if m]
    return min(candidatos, key=lambda m: m.start()) if candidatos else None


def _token_apos_conector(janela: str, posicao: int, sozinho: re.Pattern):
    return _TOKEN_APOS_CONECTOR_RE.match(janela, posicao) or _proximo_token(janela, posicao, False, sozinho)


def _separar(letras: str) -> list[str]:
    return list(letras.upper())


def _ler_categorias(janela: str, sozinho: re.Pattern) -> tuple[frozenset, bool, int] | None:
    """Lê "D", "categoria D", "B ou C", "AB", "A e B"... no começo de `janela`.
    Devolve (letras, precisa_de_todas, posição_final) ou None."""
    primeiro = _proximo_token(janela, 0, True, sozinho)
    if not primeiro:
        return None
    letras = set(_separar(primeiro.group("l")))
    todas = False  # "AB" colado é ambíguo nos anúncios ("A ou B" ou "A e B"): só descartamos se nenhuma servir
    fim = primeiro.end()
    while True:
        conector = _CONECTOR_RE.match(janela, fim)
        if not conector:
            break
        seguinte = _token_apos_conector(janela, conector.end(), sozinho)
        if not seguinte:
            break
        letras |= set(_separar(seguinte.group("l")))
        if conector.group(0).strip().lower() in ("e", "+"):
            todas = True
        fim = seguinte.end()
    return frozenset(letras), todas, fim


# ---------------------------------------------------------------------------
# CNH do candidato
# ---------------------------------------------------------------------------

def categorias_do_curriculo(texto: str) -> tuple[str, ...]:
    """Letras de CNH que o currículo informa, em ordem (ex.: ("A", "B")). Vazio se o
    currículo não cita a categoria."""
    letras: set[str] = set()
    for gatilho in _GATILHO_RE.finditer(texto or ""):
        janela = texto[gatilho.end(): gatilho.end() + 40].split("\n")[0]
        lido = _ler_categorias(janela, _TOKEN_SOZINHO_CURRICULO_RE)
        if lido:
            letras |= lido[0]
    return tuple(sorted(letras))


def _efetivas(declaradas) -> frozenset:
    """Categorias que a CNH do candidato realmente cobre (E cobre D, C e B; D cobre C e B...)."""
    efetivas = set(declaradas)
    maior = max((_NIVEIS.index(c) for c in declaradas if c in _NIVEIS), default=-1)
    efetivas.update(_NIVEIS[: maior + 1])
    return frozenset(efetivas)


def _atende(efetivas: frozenset, exigencia: Exigencia) -> bool:
    if exigencia.todas:
        return exigencia.letras <= efetivas
    return bool(exigencia.letras & efetivas)


# ---------------------------------------------------------------------------
# CNH exigida pela vaga
# ---------------------------------------------------------------------------

_AJUDANTE_RE = re.compile(r"\b(?:ajudante|auxiliar)\s+(?:de\s+)?(?:motorista|condutor)\b")
_MOTORISTA = r"\b(?:motorista|condutor)\b(?:\W+\w+){0,2}?\W+"
_CARGOS_QUE_EXIGEM = (
    (re.compile(_MOTORISTA + r"(?:micro\W?onibus|onibus|transporte\s+coletivo|transporte\s+de\s+passageiros)\b"), "D"),
    (re.compile(_MOTORISTA + r"(?:carreta|bitrem|rodotrem|cavalo\s+mecanico)\b"), "E"),
    (re.compile(_MOTORISTA + r"(?:caminhao|caminhoes|truck|toco|munck|betoneira|basculante)\b"), "C"),
    (re.compile(r"\b(?:motoboy|motofretista|mototaxista|moto\s*taxista)\b"), "A"),
)


def _exigencias_do_texto(titulo: str, descricao: str) -> list[Exigencia]:
    texto = f"{titulo}\n{descricao[:_TRECHO_DESCRICAO]}"
    achadas = []
    for gatilho in _GATILHO_RE.finditer(texto):
        janela = texto[gatilho.end(): gatilho.end() + 28].split("\n")[0]
        lido = _ler_categorias(janela, _TOKEN_SOZINHO_RE)
        if not lido:
            continue
        letras, todas, fim = lido
        contexto = _sem_acentos_minusculo(texto[max(0, gatilho.start() - 70): gatilho.end() + fim + 40])
        if _DIFERENCIAL_RE.search(contexto):
            continue  # "CNH D será um diferencial": não é exigência
        achadas.append(Exigencia(letras, todas, "texto"))
    return achadas


def _exigencias_do_cargo(titulo: str) -> list[Exigencia]:
    normalizado = _sem_acentos_minusculo(titulo)
    achadas = []
    for padrao, letra in _CARGOS_QUE_EXIGEM:
        if padrao.search(normalizado) and not (letra != "A" and _AJUDANTE_RE.search(normalizado)):
            achadas.append(Exigencia(frozenset(letra), False, "cargo"))
    return achadas


def exigencias_da_vaga(vaga) -> list[Exigencia]:
    titulo = getattr(vaga, "titulo", "") or ""
    descricao = getattr(vaga, "descricao", "") or ""
    return _exigencias_do_texto(titulo, descricao) + _exigencias_do_cargo(titulo)


def _descrever(letras: frozenset, todas: bool) -> str:
    ordenadas = sorted(letras)
    return (" e " if todas else " ou ").join(ordenadas)


def motivo_de_eliminacao(vaga, categorias) -> str | None:
    """Se a vaga exige uma CNH que o candidato não tem, devolve o motivo (texto curto);
    senão None. Sem categoria no currículo, nunca elimina."""
    if not categorias:
        return None
    exigencias = exigencias_da_vaga(vaga)
    if not exigencias:
        return None
    efetivas = _efetivas(categorias)
    if any(_atende(efetivas, e) for e in exigencias):
        return None
    principal = exigencias[0]
    onde = "pelo cargo" if principal.origem == "cargo" else "no texto da vaga"
    tem = ", ".join(sorted(categorias))
    return f"exige CNH {_descrever(principal.letras, principal.todas)} ({onde}) e o currículo informa só CNH {tem}"


def filtrar_por_habilitacao(vagas: list, categorias) -> tuple[list, list[tuple]]:
    """Separa as vagas que o candidato pode ocupar das que exigem CNH que ele não tem.
    Retorna (vagas_validas, [(vaga_descartada, motivo), ...])."""
    validas, descartadas = [], []
    for vaga in vagas:
        motivo = motivo_de_eliminacao(vaga, categorias)
        if motivo:
            descartadas.append((vaga, motivo))
        else:
            validas.append(vaga)
    return validas, descartadas
