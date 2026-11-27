"""Classificação das oportunidades para separar intenção da busca e aderência ao perfil."""
from __future__ import annotations

import re
from typing import Any

from intencao_busca import compilar_intencoes, vaga_corresponde_titulo
from filtros import normalizar_texto

# Famílias profissionais que podem ser reconhecidas no título da vaga.
_FAMILIAS_TITULO: dict[str, tuple[str, ...]] = {
    "ti": (
        "suporte tecnico", "tecnico de informatica", "tecnico em informatica",
        "analista de suporte", "analista de ti", "help desk", "service desk",
        "infraestrutura de ti", "tecnico de redes", "assistente de ti",
    ),
    "administrativo": (
        "assistente administrativo", "auxiliar administrativo", "analista administrativo",
        "secretaria administrativa", "secretario administrativo", "assistente de operacoes",
        "auxiliar de escritorio", "assistente de departamento pessoal",
    ),
    "logistica_estoque": (
        "estoquista", "auxiliar de estoque", "auxiliar de almoxarifado", "almoxarife",
        "auxiliar de logistica", "assistente de logistica", "encarregado de expedicao",
        "assistente de expedicao", "ajudante de distribuicao", "operador logistico",
        "auxiliar de entrega", "assistente de transporte", "ajudante de motorista",
    ),
    "comercial": (
        "vendedor", "vendedora", "consultor de vendas", "consultora de vendas",
        "assistente comercial", "promotor de vendas", "executivo comercial",
        "representante comercial", "consultor comercial", "atendente", "recepcionista",
    ),
    "gestao": (
        "gerente", "coordenador", "coordenadora", "supervisor", "supervisora",
        "encarregado", "encarregada", "lider operacional", "lider de equipe",
    ),
    # Condução não é inferida de logística/estoque. Só é ativada quando o perfil
    # validado informa experiência ou objetivo profissional de direção.
    "conducao": ("motorista", "condutor", "entregador", "motoboy", "motofretista"),
}

_FAMILIAS_PERFIL: dict[str, tuple[str, ...]] = {
    "ti": ("ti", "tecnologia", "informatica", "suporte tecnico", "redes"),
    "administrativo": ("administrativo", "rotinas administrativas", "notas fiscais", "gestao administrativa"),
    "logistica_estoque": ("logistica", "distribuicao", "estoque", "expedicao", "almoxarifado"),
    "comercial": ("vendas", "comercial", "atendimento", "consultivo"),
    "gestao": ("gestao", "operacoes", "lideranca", "coordenacao", "supervisao", "equipes"),
}


def _contem_termo(texto: str, termo: str) -> bool:
    texto_n = normalizar_texto(texto)
    termo_n = normalizar_texto(termo)
    if not texto_n or not termo_n:
        return False
    # Frases são pesquisadas por tokens completos; para cargos concatendados,
    # a forma compacta também é considerada quando a expressão é suficientemente longa.
    if re.search(r"(?<![a-z0-9])" + re.escape(termo_n) + r"(?![a-z0-9])", texto_n):
        return True
    compact_texto = re.sub(r"[^a-z0-9]", "", texto_n)
    compact_termo = re.sub(r"[^a-z0-9]", "", termo_n)
    return len(compact_termo) >= 8 and compact_termo in compact_texto


def _cargo_exige_experiencia_de_conducao(cargo: str) -> bool:
    return bool(re.search(r"\b(motorista|condutor|entregador|motoboy|motofretista)\b", normalizar_texto(cargo)))


def classificar_vaga(vaga: Any, termos_busca: list[str] | tuple[str, ...] | None, perfil: Any = None) -> str:
    """Classifica pela função real do título, não por menção incidental na descrição."""
    intencoes = compilar_intencoes(list(termos_busca or []))
    if intencoes and vaga_corresponde_titulo(vaga, intencoes):
        return "Pesquisa direta"

    titulo = normalizar_texto(getattr(vaga, "titulo", ""))
    if not titulo:
        return "Alternativa"

    perfil_textos = []
    if perfil is not None:
        for campo in ("areas_atuacao", "habilidades", "cargos_compativeis", "cargo_sugerido"):
            valor = getattr(perfil, campo, None)
            if isinstance(valor, (list, tuple)):
                perfil_textos.extend(str(x) for x in valor)
            elif valor:
                perfil_textos.append(str(valor))

    perfil_blob = normalizar_texto(" ".join(perfil_textos))
    familias_ativas: set[str] = set()
    for familia, pistas in _FAMILIAS_PERFIL.items():
        if any(_contem_termo(perfil_blob, pista) for pista in pistas):
            familias_ativas.add(familia)

    # Exige evidência ocupacional/objetivo validado para classificar condução como
    # compatível. CNH B e logística, isoladamente, não ativam esta família.
    if perfil is not None and (
        getattr(perfil, "experiencia_conducao_comprovada", False)
        or getattr(perfil, "objetivo_conducao_declarado", False)
    ):
        familias_ativas.add("conducao")

    for familia, titulos in _FAMILIAS_TITULO.items():
        if familia not in familias_ativas:
            continue
        if any(_contem_termo(titulo, termo) for termo in titulos):
            return "Compatível com currículo"

    # Correspondência explícita com um cargo validado pelo parser, mesmo se a
    # nomenclatura não caiu em uma das famílias acima.
    if perfil is not None:
        conducao_comprovada = bool(
            getattr(perfil, "experiencia_conducao_comprovada", False)
            or getattr(perfil, "objetivo_conducao_declarado", False)
        )
        for cargo in getattr(perfil, "cargos_compativeis", []) or []:
            # Um cargo sugerido pela IA não basta para inferir experiência ao volante.
            if _cargo_exige_experiencia_de_conducao(cargo) and not conducao_comprovada:
                continue
            if _contem_termo(titulo, cargo) or _contem_termo(cargo, titulo):
                return "Compatível com currículo"

    return "Alternativa"
