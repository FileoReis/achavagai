"""
privacidade.py
Remove dados pessoais sensíveis do texto do currículo ANTES de enviá-lo a um
provedor de IA. A IA não precisa de CPF, RG, telefone, e-mail ou endereço de rua
para avaliar uma vaga. O que ela precisa continua no texto: nome, cidade, bairro,
experiência, formação, habilidades, a categoria da CNH e a idade.

Por que isso vem ligado por padrão: nos termos do plano gratuito da API do Gemini,
o Google pode usar o conteúdo enviado para melhorar seus produtos e pessoas podem
ler esse conteúdo. Os próprios termos pedem para não enviar informação pessoal ou
sensível nesse plano. Veja ANONIMIZAR_CURRICULO em config.py.

É uma limpeza por padrões (regex), pensada para os formatos mais comuns de
currículos brasileiros. Não é garantia absoluta: confira o seu PDF.
"""

from __future__ import annotations

import re
from datetime import date

import config

_CPF_RE = re.compile(r"(?<!\d)\d{3}\.?\d{3}\.?\d{3}-?\d{2}(?!\d)")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_URL_RE = re.compile(r"(?:https?://|www\.)\S+|(?:linkedin|github|instagram|facebook)\.com/\S+", re.IGNORECASE)
_CEP_RE = re.compile(r"(?<!\d)\d{5}-\d{3}(?!\d)")

# RG / identidade: "RG: 12.345.678-9", "Identidade 123456789"
_RG_RE = re.compile(r"\b(RG|Identidade|Carteira de Identidade)\b[\s:.nº°o-]*[\dXx][\dXx.\-/]{5,}", re.IGNORECASE)

# Número da CNH (a CATEGORIA, como "CNH B", é mantida): "CNH nº 01234567890"
_CNH_NUMERO_RE = re.compile(r"\b(CNH|Habilita[cç][aã]o)\b[\s:.nº°o-]*\d{8,}", re.IGNORECASE)

# Telefones brasileiros. Exige DDD entre parênteses, ou celular começando com 9, ou
# +55, para não confundir com períodos como "2018-2022". Reconhece o hífen depois do
# nono dígito, formato comum em currículos: "(21) 9-8765-4321". O formato "DDD sem
# parênteses + fixo" é tratado à parte, em _trocar_fixo, porque pode se parecer com
# "40 2018-2019". O resume_parser usa esta mesma regex (TELEFONE_RE).
TELEFONE_PADROES = (
    r"(?:\+?55[\s-]?)?\(\s*\d{2}\s*\)\s*(?:9[-\s.]?)?\d{4}[-\s.]?\d{4}",
    r"(?:\+?55[\s-]?)?(?<!\d)\d{2}[\s.-]?(?:9\d{4}[-\s.]?|9-\d{4}-)\d{4}(?!\d)",
    r"(?<!\d)9(?:\d{4}[-\s.]|-\d{4}-)\d{4}(?!\d)",
)
TELEFONE_RE = re.compile("|".join(TELEFONE_PADROES))
_FIXO_COM_DDD_RE = re.compile(r"(?<!\d)(\d{2})\s(\d{4})-(\d{4})(?!\d)")

# Endereço de rua: "Rua das Flores, 123 - apto 45". O bairro e a cidade que vêm
# depois ficam no texto. Os tipos de via só valem com inicial maiúscula (ou tudo em
# maiúsculas): assim a frase "trabalhei na rua 3 anos" não é apagada por engano.
_ENDERECO_RE = re.compile(
    r"\b(?:Rua|RUA|Avenida|AVENIDA|Av\.?|AV\.?|Travessa|TRAVESSA|Estrada|ESTRADA|"
    r"Alameda|ALAMEDA|Pra[cç]a|PRA[CÇ]A|Largo|LARGO|Rodovia|RODOVIA|R\.)\s+"
    r"[^,\n\-–|]{2,60}"
    r"(?:,?\s*(?:[nN][ºo°.]*\s*)?\d+[A-Za-z]?)?"
    r"(?i:(?:\s*[,\-–]\s*(?:apto?\.?|ap\.?|bloco|bl\.?|casa|sala|lote|qd\.?|quadra)\s*\w+)*)"
)

_NASCIMENTO_RE = re.compile(
    r"\b(?:data\s+de\s+nascimento|nascimento|nasc\.?|nascido\s+em)\b\s*[:\-]?\s*(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})",
    re.IGNORECASE,
)


def _idade(dia: int, mes: int, ano: int, hoje: date | None = None) -> int | None:
    hoje = hoje or date.today()
    try:
        nascimento = date(ano, mes, dia)
    except ValueError:
        return None
    idade = hoje.year - nascimento.year - ((hoje.month, hoje.day) < (nascimento.month, nascimento.day))
    return idade if 0 < idade < 100 else None


def _trocar_nascimento(match: re.Match) -> str:
    # A idade fica porque algumas vagas têm faixa etária legal (ex.: jovem aprendiz).
    idade = _idade(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    return f"Idade: {idade} anos" if idade else "[nascimento removido]"


def _parece_periodo(ddd: str, parte1: str, parte2: str) -> bool:
    """"40 2018-2019" não é telefone: são duas coisas que parecem anos."""
    def ano(texto: str) -> bool:
        return texto[:2] in ("19", "20")
    return ano(parte1) and ano(parte2) and parte1 <= parte2


def _trocar_fixo(match: re.Match) -> str:
    if _parece_periodo(*match.groups()):
        return match.group(0)
    return "[telefone removido]"


def anonimizar_curriculo(texto: str) -> str:
    """Devolve o texto sem CPF, RG, número da CNH, telefone, e-mail, endereço de
    rua, CEP, links e data de nascimento (esta vira apenas a idade)."""
    if not texto:
        return texto

    # A data de nascimento vira idade ANTES das demais regras, que mexem em números.
    resultado = _NASCIMENTO_RE.sub(_trocar_nascimento, texto)
    resultado = _EMAIL_RE.sub("[e-mail removido]", resultado)
    resultado = _URL_RE.sub("[link removido]", resultado)
    resultado = _RG_RE.sub(lambda m: f"{m.group(1)}: [removido]", resultado)
    resultado = _CNH_NUMERO_RE.sub(lambda m: f"{m.group(1)}: [nº removido]", resultado)
    resultado = _CPF_RE.sub("[CPF removido]", resultado)
    resultado = _CEP_RE.sub("[CEP removido]", resultado)
    resultado = TELEFONE_RE.sub("[telefone removido]", resultado)
    resultado = _FIXO_COM_DDD_RE.sub(_trocar_fixo, resultado)
    resultado = _ENDERECO_RE.sub("[endereço removido]", resultado)
    return resultado


def preparar_para_ia(texto: str) -> str:
    """Aplica a anonimização se estiver ligada em config.ANONIMIZAR_CURRICULO."""
    if getattr(config, "ANONIMIZAR_CURRICULO", True):
        return anonimizar_curriculo(texto)
    return texto
