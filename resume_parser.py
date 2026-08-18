"""
resume_parser.py
Lê um currículo em PDF, extrai o texto e tenta identificar automaticamente:
- Nome (heurística: primeira linha "forte" do documento)
- E-mail e telefone
- Cidade / bairro (com base nas listas em config.py)
- Palavras-chave / habilidades (com base em SKILL_KEYWORDS)

O resultado é um "perfil" (dict) usado depois para gerar filtros de busca
e para comparar com as descrições das vagas encontradas.
"""

import re
from dataclasses import dataclass, field

import pdfplumber

import ia
from config import CIDADES_RJ, BAIRROS_RJ, SKILL_KEYWORDS, CARGOS_COMUNS

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_RE = re.compile(r"(\(?\d{2}\)?\s?)?9?\d{4}[-.\s]?\d{4}")

# Seções comuns de currículo que costumam indicar diretamente o cargo pretendido.
OBJETIVO_RE = re.compile(
    r"(?:objetivo|cargo pretendido|pretens[ãa]o(?: profissional)?|"
    r"[áa]rea de interesse|cargo desejado)\s*[:\-]?\s*(.+)",
    re.IGNORECASE,
)


@dataclass
class PerfilCandidato:
    texto_completo: str
    nome: str | None = None
    email: str | None = None
    telefone: str | None = None
    cidade: str | None = None
    bairro: str | None = None
    habilidades: list[str] = field(default_factory=list)
    cargo_sugerido: str | None = None
    senioridade: str | None = None
    resumo: str | None = None
    extraido_por_ia: bool = False
    erro_ia: str | None = None


def extrair_texto_pdf(caminho_pdf: str) -> str:
    """Extrai todo o texto de um PDF usando pdfplumber."""
    partes_texto = []
    with pdfplumber.open(caminho_pdf) as pdf:
        for pagina in pdf.pages:
            texto_pagina = pagina.extract_text() or ""
            partes_texto.append(texto_pagina)
    return "\n".join(partes_texto)


def _contem_palavra(item: str, texto_lower: str) -> bool:
    """Verifica se `item` aparece em `texto_lower` como palavra/expressão completa
    (evita falsos positivos, ex.: a sigla curta 'ia' não deve casar dentro de
    'experiência' ou 'manutenção')."""
    padrao = r"\b" + re.escape(item.lower()) + r"\b"
    return re.search(padrao, texto_lower) is not None


def _achar_primeiro(padroes: list[str], texto: str) -> str | None:
    """Retorna o primeiro item da lista `padroes` que aparece no texto (como
    palavra/expressão completa, case-insensitive)."""
    texto_lower = texto.lower()
    for item in padroes:
        if _contem_palavra(item, texto_lower):
            return item
    return None


def _extrair_nome(texto: str) -> str | None:
    """Heurística simples: usa a primeira linha não vazia do PDF como nome,
    desde que pareça um nome (poucas palavras, sem @, sem muitos números)."""
    for linha in texto.splitlines():
        linha = linha.strip()
        if not linha:
            continue
        if "@" in linha or any(c.isdigit() for c in linha):
            continue
        palavras = linha.split()
        if 1 < len(palavras) <= 5:
            return linha
        break
    return None


def _extrair_cargo_desejado(texto: str, habilidades: list[str]) -> str | None:
    """Tenta sugerir um cargo/função desejado, nesta ordem de prioridade:
    1) Uma seção explícita do currículo (ex.: "Objetivo: Auxiliar Administrativo").
    2) O cargo da lista CARGOS_COMUNS que mais aparece no texto do currículo
       (ex.: mencionado no histórico profissional/experiências).
    3) A primeira habilidade/área identificada, como último recurso.
    """
    # 1) Seção explícita de objetivo/cargo pretendido
    match = OBJETIVO_RE.search(texto)
    if match:
        candidato = match.group(1).strip()
        # pega só a primeira "frase curta" (até quebra de linha, ponto ou vírgula)
        candidato = re.split(r"[\n.,;]", candidato)[0].strip()
        if candidato and len(candidato.split()) <= 8:
            return candidato

    # 2) Cargo mais frequente entre os CARGOS_COMUNS mencionados no currículo
    texto_lower = texto.lower()
    contagens = []
    for cargo in CARGOS_COMUNS:
        padrao = r"\b" + re.escape(cargo.lower()) + r"\b"
        ocorrencias = len(re.findall(padrao, texto_lower))
        if ocorrencias > 0:
            contagens.append((cargo, ocorrencias))

    if contagens:
        contagens.sort(key=lambda par: par[1], reverse=True)
        return contagens[0][0]

    # 3) Último recurso: primeira habilidade/área identificada
    return habilidades[0] if habilidades else None


def analisar_curriculo(caminho_pdf: str) -> PerfilCandidato:
    """Lê o PDF e monta o PerfilCandidato com as informações identificadas.
    Tenta primeiro uma extração via IA (mais precisa: entende contexto, sinônimos
    e senioridade); se não houver IA configurada ou a chamada falhar, usa a
    extração local por palavras-chave/regex como alternativa — o script nunca
    trava por falta de IA."""
    texto = extrair_texto_pdf(caminho_pdf)

    email_match = EMAIL_RE.search(texto)
    telefone_match = PHONE_RE.search(texto)

    # Extração local (regras/palavras-chave) — sempre calculada, serve de base e
    # de fallback caso a IA não esteja disponível ou falhe.
    cidade = _achar_primeiro(CIDADES_RJ, texto)
    bairro = _achar_primeiro(BAIRROS_RJ, texto)
    habilidades = [kw for kw in SKILL_KEYWORDS if _contem_palavra(kw, texto.lower())]
    cargo_sugerido = _extrair_cargo_desejado(texto, habilidades)

    perfil = PerfilCandidato(
        texto_completo=texto,
        nome=_extrair_nome(texto),
        email=email_match.group(0) if email_match else None,
        telefone=telefone_match.group(0) if telefone_match else None,
        cidade=cidade,
        bairro=bairro,
        habilidades=habilidades,
        cargo_sugerido=cargo_sugerido,
    )

    perfil_ia = _extrair_perfil_com_ia(texto)
    if perfil_ia:
        # A IA tende a ser mais precisa que a extração por palavras-chave — usa os
        # campos dela quando disponíveis, mantendo o resultado local como reserva.
        perfil.cidade = perfil_ia.get("cidade") or perfil.cidade
        perfil.bairro = perfil_ia.get("bairro") or perfil.bairro
        perfil.cargo_sugerido = perfil_ia.get("cargo_sugerido") or perfil.cargo_sugerido
        habilidades_ia = perfil_ia.get("habilidades")
        if habilidades_ia:
            perfil.habilidades = habilidades_ia
        perfil.senioridade = perfil_ia.get("senioridade")
        perfil.resumo = perfil_ia.get("resumo")
        perfil.extraido_por_ia = True
    elif ia.provedor_disponivel():
        # Havia IA configurada, mas a chamada falhou — guarda o motivo para o
        # main.py poder avisar o usuário (em vez de silenciosamente usar a
        # extração local sem explicação).
        perfil.erro_ia = ia.ultimo_erro

    return perfil


def _extrair_perfil_com_ia(texto: str) -> dict | None:
    """Usa a IA disponível (Gemini gratuito ou Claude, via ia.py) para ler o
    currículo completo e extrair um perfil estruturado — mais preciso do que a
    lista fixa de palavras-chave, pois entende contexto e sinônimos. Retorna None
    se não houver IA configurada ou se a chamada falhar (o chamador deve manter o
    resultado da extração local nesse caso)."""
    if not ia.provedor_disponivel():
        return None

    prompt = f"""Leia o currículo abaixo e extraia um perfil estruturado do candidato.

ATENÇÃO a uma distinção importante: ter uma habilitação (CNH) ou qualquer outra
qualificação genérica NÃO significa que o candidato quer atuar naquela área.
Por exemplo, se o currículo menciona "CNH categoria B" apenas como um dado
pessoal (comum em currículos brasileiros, mesmo para vagas que nada têm a ver
com dirigir), isso NÃO é evidência de que o candidato quer ser motorista — não
inclua "motorista" ou cargos de condução em "habilidades" nem em "cargo_sugerido"
a menos que o currículo mostre EXPERIÊNCIA PROFISSIONAL como motorista/entregador
ou declare isso explicitamente como objetivo. O mesmo vale para outras
qualificações genéricas (ex.: primeiros socorros, informática básica) — não as
transforme em cargo sugerido sem evidência de que é a área de atuação real do
candidato.

Currículo:
---
{texto[:6000]}
---

Responda SOMENTE em JSON válido, sem texto antes ou depois, no formato:
{{
  "cidade": "cidade onde o candidato mora, ou null se não for possível identificar",
  "bairro": "bairro onde o candidato mora, ou null se não for possível identificar",
  "cargo_sugerido": "cargo/função mais adequado para esse candidato buscar, com base na experiência profissional e formação real dele (não em qualificações genéricas isoladas como CNH)",
  "habilidades": ["lista", "de", "principais", "habilidades", "técnicas", "e", "comportamentais", "diretamente ligadas à área de atuação do candidato, no máximo 10 itens"],
  "senioridade": "estagiário/júnior/pleno/sênior/especialista/coordenador/gerente (a que melhor descreve o nível atual do candidato)",
  "resumo": "resumo de 1 frase (máximo 25 palavras) sobre o perfil profissional do candidato"
}}"""

    dados = ia.chamar_ia_json(prompt, max_tokens=800)
    if not isinstance(dados, dict):
        return None
    return dados


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        print("Uso: python resume_parser.py caminho/para/curriculo.pdf")
        raise SystemExit(1)

    perfil = analisar_curriculo(sys.argv[1])
    print("Nome:", perfil.nome)
    print("E-mail:", perfil.email)
    print("Telefone:", perfil.telefone)
    print("Cidade detectada:", perfil.cidade)
    print("Bairro detectado:", perfil.bairro)
    print("Habilidades detectadas:", ", ".join(perfil.habilidades) or "nenhuma")
    print("Cargo sugerido:", perfil.cargo_sugerido or "nenhum")
    print("Senioridade:", perfil.senioridade or "não identificada")
    print("Resumo:", perfil.resumo or "não gerado")
    print("Extraído por IA:", perfil.extraido_por_ia)


