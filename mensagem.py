"""
mensagem.py
Gera uma mensagem curta de candidatura/apresentação personalizada para uma vaga
específica, com base no perfil do candidato. Usada para as vagas do topo do
ranking, prontas para copiar e colar (LinkedIn, e-mail, WhatsApp do recrutador etc.).
Requer IA configurada (Gemini ou Claude, via ia.py); retorna None se não houver.
"""

import ia
from scrapers.base import Vaga


def _montar_prompt(texto_curriculo: str, vaga: Vaga) -> str:
    return f"""Você é um candidato a emprego escrevendo uma mensagem curta de
apresentação/candidatura para a vaga abaixo, com base no currículo informado.

Currículo (resumo):
---
{texto_curriculo[:3000]}
---

Vaga:
Título: {vaga.titulo}
Empresa: {vaga.empresa or "não informado"}
Local: {vaga.cidade or "não informado"}
Descrição: {(vaga.descricao or "(sem descrição disponível)")[:800]}

Escreva uma mensagem curta (entre 60 e 100 palavras), em português, em primeira
pessoa, natural e direta — sem exageros nem clichês genéricos. Destaque 1 ou 2
pontos concretos do currículo que conectam com a vaga. Termine demonstrando
interesse em conversar. Não use saudações formais como "Prezados" — escreva como
uma mensagem que seria enviada por WhatsApp, e-mail curto ou LinkedIn.

Responda APENAS com o texto da mensagem, sem aspas, sem explicações antes ou depois."""


def gerar_mensagem_candidatura(texto_curriculo: str, vaga: Vaga) -> str | None:
    """Gera uma mensagem de candidatura personalizada para a vaga informada.
    Retorna None se não houver IA configurada ou se a chamada falhar."""
    if not ia.provedor_disponivel():
        return None
    prompt = _montar_prompt(texto_curriculo, vaga)
    resposta = ia.chamar_ia(prompt, max_tokens=400)
    return resposta.strip() if resposta else None


def gerar_mensagens_top(
    texto_curriculo: str, ranking: list[tuple[Vaga, float, str]], quantidade: int = 5
) -> list[tuple[Vaga, float, str]]:
    """Gera mensagens de candidatura para as `quantidade` melhores vagas do ranking.
    Retorna lista de tuplas (Vaga, pontuacao, mensagem) — só inclui vagas para as
    quais a geração deu certo (falhas individuais são simplesmente omitidas)."""
    resultado = []
    for vaga, pontuacao, _ in ranking[:quantidade]:
        mensagem = gerar_mensagem_candidatura(texto_curriculo, vaga)
        if mensagem:
            resultado.append((vaga, pontuacao, mensagem))
    return resultado
