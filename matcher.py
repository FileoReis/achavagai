"""
matcher.py
Compara o texto do currículo com o título+descrição de cada vaga encontrada e
calcula uma pontuação de compatibilidade (0 a 100), além de (quando há IA
disponível) uma justificativa curta explicando o motivo da nota.

Todas as funções retornam uma lista de tuplas (Vaga, pontuacao, motivo).

- ranquear_por_similaridade: TF-IDF local, sempre disponível, sem custo.
- ranquear: usa IA (Gemini grátis ou Claude, via ia.py) para uma análise profunda
  das vagas pré-selecionadas pelo TF-IDF, considerando área, senioridade e
  localização. Cai automaticamente para o TF-IDF se nenhuma IA estiver configurada
  ou se a chamada falhar.
"""

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from scrapers.base import Vaga
import ia


def ranquear_por_similaridade(texto_curriculo: str, vagas: list[Vaga]) -> list[tuple[Vaga, float, str]]:
    """Ranqueia vagas por similaridade de texto (TF-IDF) com o currículo.
    `motivo` fica vazio nesta estratégia — apenas sobreposição estatística de termos,
    sem IA explicando a nota.
    """
    if not vagas:
        return []

    textos_vagas = [f"{v.titulo} {v.descricao}" for v in vagas]
    corpus = [texto_curriculo] + textos_vagas

    vetorizador = TfidfVectorizer(stop_words=None, max_features=5000)
    matriz = vetorizador.fit_transform(corpus)

    similaridades = cosine_similarity(matriz[0:1], matriz[1:])[0]

    resultado = [(vaga, round(float(sim) * 100, 1), "") for vaga, sim in zip(vagas, similaridades)]
    resultado.sort(key=lambda item: item[1], reverse=True)
    return resultado


def _montar_prompt_ranking(texto_curriculo: str, pre_selecionadas: list[tuple[Vaga, float, str]]) -> str:
    lista_vagas_texto = "\n".join(
        f"{i}. Título: {v.titulo} | Empresa: {v.empresa or 'não informado'} | "
        f"Local: {v.cidade or 'não informado'} | Fonte: {v.fonte}\n   Descrição: {(v.descricao or '(sem descrição disponível)')[:500]}"
        for i, (v, _, _) in enumerate(pre_selecionadas)
    )

    return f"""Você é um recrutador experiente e RIGOROSO. Avalie a aderência entre o
currículo abaixo e cada uma das vagas listadas.

Preste atenção especial a REQUISITOS CONCRETOS que eliminam um candidato mesmo
que o título da vaga pareça relacionado — por exemplo:
- Categoria de CNH (carteira de motorista) exigida pela vaga vs. a que o
  candidato tem (ex.: vaga de motorista de caminhão exige CNH C/D/E; se o
  currículo só menciona CNH A/B ou não menciona CNH nenhuma, a nota deve ser
  BAIXA — não presuma que o candidato tem a habilitação certa).
- Curso técnico ou registro profissional específico (ex.: técnico em
  enfermagem, técnico em nutrição, engenheiro com CREA, contador com CRC) —
  se o currículo não menciona formação ou experiência nessa área específica,
  a nota deve ser BAIXA, mesmo que a palavra "técnico" apareça no currículo
  para uma área totalmente diferente.
- Vaga EXCLUSIVA para PCD (Pessoa com Deficiência): isso é um critério de
  elegibilidade legal, não uma preferência — se o currículo não menciona
  nenhuma deficiência, a nota deve ser MUITO BAIXA (próxima de 0), mesmo que
  o cargo em si combine perfeitamente com o perfil do candidato. NÃO dê nota
  intermediária "porque o resto combina" — a vaga exclusiva para PCD elimina
  o candidato sem deficiência declarada, ponto final.
- Não assuma que o candidato tem uma qualificação só porque não foi
  mencionada — ausência de menção = não presuma que ele tem.

Além dos requisitos concretos, considere também:
- Área de atuação e cargo (aderência direta ou próxima, não apenas palavras iguais).
- Nível de senioridade (o candidato está sobre ou subqualificado para a vaga?).
- Localização, quando informada (dê preferência a vagas na mesma cidade/região).

Currículo do candidato:
---
{texto_curriculo[:6000]}
---

Vagas encontradas (numeradas):
---
{lista_vagas_texto}
---

Para cada vaga, dê uma nota de 0 a 100 (100 = aderência excelente, 0 = nenhuma
relação ou requisito eliminatório não atendido) e uma justificativa curta
(entre 8 e 20 palavras, em português).

A justificativa é OBRIGATÓRIA e não pode ser genérica ("ok", "boa vaga", "compatível")
— precisa citar algo CONCRETO: uma habilidade, cargo anterior, requisito atendido
ou requisito que falta no currículo. Se a descrição da vaga for muito curta ou
vazia para avaliar com confiança, diga isso explicitamente na justificativa e
seja conservador na nota (não invente informação que não está no texto).

Responda SOMENTE em JSON válido, sem nenhum texto antes ou depois, no formato:
[{{"indice": 0, "nota": 85, "motivo": "Experiência direta em suporte de TI e mesma cidade."}}, ...]"""


def _selecionar_candidatas_com_representatividade(
    vagas_pontuadas: list[tuple[Vaga, float, str]], top_n: int
) -> list[tuple[Vaga, float, str]]:
    """Escolhe quais vagas (já pontuadas pelo TF-IDF) serão enviadas para a IA
    avaliar em detalhe. Se o usuário pesquisou vários cargos ao mesmo tempo
    (separados por vírgula), garante que cada cargo tenha uma cota mínima de vagas
    representadas — sem isso, um cargo com muito mais vagas disponíveis no total
    (ex.: "Motorista") pode dominar sozinho as top_n globais e deixar cargos com
    menos vagas (mas talvez mais relevantes) de fora da análise da IA."""
    grupos: dict[str, list[tuple[Vaga, float, str]]] = {}
    for item in vagas_pontuadas:
        termo = item[0].termo_busca or "_geral"
        grupos.setdefault(termo, []).append(item)

    if len(grupos) <= 1:
        return vagas_pontuadas[:top_n]

    cota_por_grupo = max(1, top_n // len(grupos))
    selecionadas: list[tuple[Vaga, float, str]] = []
    restantes: list[tuple[Vaga, float, str]] = []

    for itens_do_grupo in grupos.values():
        selecionadas.extend(itens_do_grupo[:cota_por_grupo])
        restantes.extend(itens_do_grupo[cota_por_grupo:])

    vagas_ja_selecionadas = {item[0].link for item in selecionadas}
    restantes = [item for item in restantes if item[0].link not in vagas_ja_selecionadas]
    restantes.sort(key=lambda item: item[1], reverse=True)

    faltam = top_n - len(selecionadas)
    if faltam > 0:
        selecionadas.extend(restantes[:faltam])

    selecionadas.sort(key=lambda item: item[1], reverse=True)
    return selecionadas[:top_n]


def ranquear(texto_curriculo: str, vagas: list[Vaga], top_n: int = 30) -> tuple[list[tuple[Vaga, float, str]], bool]:
    """Análise profunda via IA (Gemini gratuito, ou Claude): lê o currículo completo
    e cada vaga pré-selecionada e devolve nota + justificativa por vaga. A seleção de
    quais vagas mandar para a IA garante representatividade entre os diferentes
    cargos pesquisados (veja _selecionar_candidatas_com_representatividade). Cai
    automaticamente para o ranking TF-IDF puro se nenhuma IA estiver configurada ou
    se a chamada falhar, sem interromper o script.

    Retorna (ranking, usou_ia_com_sucesso) — o booleano permite ao chamador avisar o
    usuário quando o ranking exibido NÃO tem justificativa de IA (por falha da
    chamada), em vez de deixar parecer que a IA avaliou quando na verdade não avaliou.
    """
    vagas_pontuadas = ranquear_por_similaridade(texto_curriculo, vagas)
    pre_selecionadas = _selecionar_candidatas_com_representatividade(vagas_pontuadas, top_n)

    if not pre_selecionadas or not ia.provedor_disponivel():
        return vagas_pontuadas, False

    prompt = _montar_prompt_ranking(texto_curriculo, pre_selecionadas)
    avaliacoes = ia.chamar_ia_json(prompt, max_tokens=4000)
    if not avaliacoes:
        return pre_selecionadas, False

    mapa = {item["indice"]: (item.get("nota", 0), item.get("motivo", "")) for item in avaliacoes}
    resultado = []
    for i, (vaga, pontuacao_tfidf, _) in enumerate(pre_selecionadas):
        nota, motivo = mapa.get(i, (pontuacao_tfidf, ""))
        resultado.append((vaga, float(nota), motivo))

    resultado.sort(key=lambda item: item[1], reverse=True)
    return resultado, True
