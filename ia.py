"""
ia.py
Camada única de acesso a modelos de IA (Gemini ou Claude), usada por matcher.py,
resume_parser.py e mensagem.py. Detecta automaticamente qual provedor está
disponível (dá preferência ao Gemini, que tem plano gratuito) e expõe funções
simples (`chamar_ia` e `chamar_ia_json`) que os outros módulos usam sem se
preocupar com o provedor que está por trás.

Variáveis de ambiente (podem ficar no arquivo .env):
    GEMINI_API_KEY      chave do Google AI Studio
    GEMINI_MODEL        opcional: um modelo ou vários separados por vírgula
    ANTHROPIC_API_KEY   chave da Anthropic (uso pago)
    CLAUDE_MODEL        opcional: substitui o modelo do Claude
    IA_PROVEDOR         opcional: "gemini" ou "claude", para escolher quando as
                        duas chaves existem

O que esta camada resolve para você:
- Repete chamadas que falham por motivo passageiro (erro 429 de limite de
  requisições, erros 5xx, queda de rede), respeitando o tempo de espera que o
  servidor pede.
- Se um modelo do Gemini estiver sem cota ou não existir mais, tenta o próximo
  da lista GEMINI_MODELOS (config.py). A cota do Gemini é por modelo.
- Compensa o fato de os tokens de raciocínio contarem DENTRO do limite de saída
  do Gemini (sem isso a resposta podia vir cortada ou vazia).
- Se a API recusar o nível de raciocínio ou a instrução de sistema (isso muda de
  uma geração de modelo para outra), repete a chamada sem esse parâmetro em vez
  de falhar.
- Se a resposta JSON vier com texto solto ou cortada no meio, aproveita o que
  chegou completo (veja `decodificar_json`).
- Se `ia.aviso_callback` estiver definido, avisa o usuário quando precisar
  esperar por limite de requisições ou trocar de modelo.
- Lembra quais modelos falharam (durante a execução) e qual funcionou (entre
  execuções, veja `usar_arquivo_de_preferencia`), para não repetir a mesma falha
  a cada chamada.

Se uma chamada falhar, o motivo real fica em `ultimo_erro` (texto curto) e o
modelo que respondeu por último fica em `modelo_usado`.
"""

from __future__ import annotations

import json
import math
import os
import random
import re
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import requests

import config

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
TIMEOUT_SEGUNDOS = 90
LIMITE_MAXIMO_TOKENS = 32768

ultimo_erro: str | None = None
modelo_usado: str | None = None

# Função opcional (recebe um texto) que o main.py define para mostrar avisos ao
# usuário durante esperas e trocas de modelo. Se ficar None, tudo é silencioso.
aviso_callback = None

_desativada = False

# Existe só para os testes automáticos poderem trocar a espera real por uma falsa.
_dormir = time.sleep
_agora = time.monotonic

# Memória de modelos. Sem ela, cada chamada recomeçava pelo primeiro modelo da lista
# e repetia a mesma falha (ex.: modelo sem cota na chave gratuita) a cada lote de vagas.
_bloqueados: dict[str, tuple[float, str]] = {}  # modelo -> (bloqueado até, motivo)
_preferido: str | None = None                   # modelo que respondeu por último com sucesso
arquivo_preferencia: Path | None = None         # onde lembrar o modelo entre execuções


def _avisar(texto: str) -> None:
    if aviso_callback:
        try:
            aviso_callback(texto)
        except Exception:
            pass  # um aviso que falha nunca pode derrubar a chamada à IA


def _cfg(nome: str, padrao):
    """Lê uma configuração de config.py com valor padrão, para o script não
    quebrar se alguém atualizar este arquivo sem atualizar o config.py."""
    return getattr(config, nome, padrao)


def _limpar_chave(valor: str) -> str:
    """Tira espaços e aspas que costumam sobrar ao colar a chave no .env."""
    return (valor or "").strip().strip('"').strip("'").strip()


# ---------------------------------------------------------------------------
# Provedor e modelos
# ---------------------------------------------------------------------------

def desativar() -> None:
    """Desliga toda a IA nesta execução (usado por --sem-ia), mesmo que haja
    chave configurada."""
    global _desativada
    _desativada = True


def chaves_gemini() -> list[tuple[str, str]]:
    """Devolve as chaves Gemini configuradas, sem duplicatas e sem expor seus valores.

    Aceita GEMINI_API_KEY (legado) e GEMINI_API_KEY_1.._20. Chaves adicionais
    servem para redundância quando uma credencial é inválida; não são alternadas
    para contornar HTTP 429, pois a cota é aplicada ao projeto associado à chave.
    """
    nomes = ["GEMINI_API_KEY"] + [f"GEMINI_API_KEY_{i}" for i in range(1, 21)]
    encontrados: list[tuple[str, str]] = []
    vistos: set[str] = set()
    for nome in nomes:
        valor = _limpar_chave(os.environ.get(nome, ""))
        if valor and valor not in vistos:
            encontrados.append((nome, valor))
            vistos.add(valor)
    return encontrados


def provedor_disponivel() -> str | None:
    """Retorna "gemini", "claude" ou None, conforme as chaves de API configuradas.
    Prioriza o Gemini por ter plano gratuito (IA_PROVEDOR pode inverter isso)."""
    if _desativada:
        return None
    tem_gemini = bool(chaves_gemini())
    tem_claude = bool(_limpar_chave(os.environ.get("ANTHROPIC_API_KEY", "")))
    preferido = os.environ.get("IA_PROVEDOR", "").strip().lower()
    if preferido == "claude" and tem_claude:
        return "claude"
    if preferido == "gemini" and tem_gemini:
        return "gemini"
    if tem_gemini:
        return "gemini"
    if tem_claude:
        return "claude"
    return None


def nome_provedor() -> str | None:
    """Nome amigável do provedor ativo, para mostrar na tela."""
    return {"gemini": "Gemini", "claude": "Claude"}.get(provedor_disponivel() or "")


def modelos_gemini() -> list[str]:
    """Lista de modelos do Gemini a tentar, em ordem. GEMINI_MODEL (no .env ou no
    ambiente) substitui a lista do config.py: pode ser um modelo só ou vários
    separados por vírgula (ex.: GEMINI_MODEL=gemini-4-argon,gemini-3.8-flash)."""
    forcados = [m.strip() for m in os.environ.get("GEMINI_MODEL", "").split(",") if m.strip()]
    if forcados:
        return forcados
    return list(_cfg("GEMINI_MODELOS", ["gemini-3.8-flash"]))


def modelo_claude() -> str:
    return os.environ.get("CLAUDE_MODEL", "").strip() or _cfg("CLAUDE_MODELO", "claude-sonnet-5-5")


# ---------------------------------------------------------------------------
# Gemini
# ---------------------------------------------------------------------------

@dataclass
class _Resultado:
    texto: str | None = None
    erro: str = ""
    fatal: bool = False  # True = não adianta repetir este pedido com o mesmo modelo/chave
    motivo: str = ""     # motivo curto, para mostrar ao usuário
    bloqueio: float = 0.0  # segundos sem tentar este modelo de novo (math.inf = até o fim da execução)
    trocar_chave: bool = False  # True só quando a credencial parece inválida


def _montar_corpo_gemini(
    prompt: str,
    limite_saida: int,
    json_mode: bool,
    nivel: str | None,
    sistema: str | None = None,
    sistema_no_prompt: bool = False,
) -> dict:
    config_geracao: dict = {"maxOutputTokens": limite_saida}
    if json_mode:
        config_geracao["responseMimeType"] = "application/json"
    if nivel:
        config_geracao["thinkingConfig"] = {"thinkingLevel": nivel}

    texto = prompt
    corpo: dict = {"generationConfig": config_geracao}
    if sistema and sistema_no_prompt:
        texto = f"{sistema}\n\n{prompt}"
    elif sistema:
        corpo["systemInstruction"] = {"parts": [{"text": sistema}]}
    corpo["contents"] = [{"role": "user", "parts": [{"text": texto}]}]
    return corpo


def _detalhe_erro(resposta) -> str:
    try:
        return resposta.json().get("error", {}).get("message", "") or (resposta.text or "")[:300]
    except Exception:
        return (resposta.text or "")[:300]


def _cota_diaria(texto_bruto: str) -> bool:
    """True quando o 429 é por cota DIÁRIA esgotada (ou limite zero para o modelo):
    esperar alguns segundos não resolve, então vale trocar de modelo."""
    compacto = re.sub(r"[\s_\-]", "", texto_bruto.lower())
    return "perday" in compacto or re.search(r"limit:\s*0\b", texto_bruto) is not None


def _espera_sugerida(resposta) -> float | None:
    """Tempo (s) que o servidor pediu para aguardar, se informado."""
    cabecalhos = getattr(resposta, "headers", None) or {}
    valor = cabecalhos.get("Retry-After")
    if valor:
        try:
            return float(valor)
        except ValueError:
            pass
    try:
        dados = resposta.json()
    except Exception:
        dados = {}
    detalhes = []
    if isinstance(dados, dict):
        detalhes = (dados.get("error") or {}).get("details") or []
    for item in detalhes:
        if isinstance(item, dict) and item.get("retryDelay"):
            achado = re.match(r"\s*([\d.]+)\s*s", str(item["retryDelay"]))
            if achado:
                return float(achado.group(1))
    achado = re.search(r"retry in ([\d.]+)\s*s", getattr(resposta, "text", "") or "", re.IGNORECASE)
    return float(achado.group(1)) if achado else None


def _espera_exponencial(tentativa: int) -> float:
    return min(2 ** tentativa, 20) + random.uniform(0, 1)


def _extrair_texto_gemini(resposta) -> tuple[str | None, str, str, bool]:
    """Devolve (texto, erro, finishReason, vale_repetir)."""
    try:
        dados = resposta.json()
    except ValueError as erro:
        return None, f"Resposta do Gemini em formato inesperado: {erro}", "", True

    candidatos = dados.get("candidates") if isinstance(dados, dict) else None
    if not candidatos:
        motivo = ""
        if isinstance(dados, dict):
            motivo = (dados.get("promptFeedback") or {}).get("blockReason", "")
        mensagem = "Gemini não retornou candidatos na resposta." + (f" Motivo: {motivo}" if motivo else "")
        return None, mensagem, "", not motivo  # bloqueio de segurança não se resolve repetindo

    finish = candidatos[0].get("finishReason", "") or ""
    if finish == "MAX_TOKENS":
        return None, "Gemini cortou a resposta por exceder o limite de tokens (finishReason=MAX_TOKENS).", finish, True
    if finish in ("SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "RECITATION"):
        return None, f"Gemini bloqueou a resposta (finishReason={finish}).", finish, False

    partes = (candidatos[0].get("content") or {}).get("parts")
    if not partes:
        return None, f"Gemini retornou resposta sem conteúdo de texto (finishReason={finish}).", finish, True

    # Os modelos Gemini 3.x podem devolver várias partes: blocos de raciocínio
    # interno (marcados com "thought": true) e a resposta final. Só queremos a final.
    texto = "".join(p.get("text", "") for p in partes if isinstance(p, dict) and not p.get("thought"))
    if not texto.strip():
        return None, f"Gemini retornou só raciocínio interno, sem resposta final (finishReason={finish}).", finish, True
    return texto, "", finish, False


def _tentar_modelo_gemini(
    modelo: str, chave: str, prompt: str, max_tokens: int, json_mode: bool, sistema: str | None
) -> _Resultado:
    url = f"{GEMINI_BASE_URL}/{modelo}:generateContent"
    nivel = _cfg("GEMINI_NIVEL_PENSAMENTO", "low") or None
    limite = int(max_tokens) + int(_cfg("GEMINI_FOLGA_TOKENS", 4096))
    maximo_falhas = max(1, int(_cfg("IA_TENTATIVAS_POR_MODELO", 3)))
    espera_maxima = float(_cfg("IA_ESPERA_MAXIMA_SEGUNDOS", 45))
    sistema_no_prompt = False

    falhas = 0    # falhas passageiras (rede, 429, 5xx, resposta vazia)
    ajustes = 0   # vezes que removemos um parâmetro recusado ou aumentamos o limite
    ultima = f"Gemini ({modelo}) não respondeu."
    bloqueio, motivo_curto = 0.0, ""  # só vale se a última falha foi de limite ou instabilidade

    while falhas < maximo_falhas and ajustes <= 6:
        corpo = _montar_corpo_gemini(prompt, limite, json_mode, nivel, sistema, sistema_no_prompt)
        try:
            resposta = requests.post(
                url,
                headers={"x-goog-api-key": chave, "Content-Type": "application/json"},
                json=corpo,
                timeout=TIMEOUT_SEGUNDOS,
            )
        except requests.RequestException as erro:
            ultima = f"Falha de rede ao chamar o Gemini ({modelo}): {erro}"
            falhas += 1
            bloqueio, motivo_curto = 0.0, ""  # rede ruim afeta todos os modelos: não adianta bloquear
            if falhas < maximo_falhas:
                _dormir(_espera_exponencial(falhas))
            continue

        if resposta.ok:
            texto, erro, finish, vale_repetir = _extrair_texto_gemini(resposta)
            if texto is not None:
                return _Resultado(texto=texto)
            ultima = f"{erro} (modelo {modelo})"
            if finish == "MAX_TOKENS" and limite < LIMITE_MAXIMO_TOKENS:
                limite = min(limite * 2, LIMITE_MAXIMO_TOKENS)
                ajustes += 1
                continue
            if not vale_repetir:
                return _Resultado(erro=ultima)
            falhas += 1
            bloqueio, motivo_curto = 0.0, ""
            continue

        status = resposta.status_code
        detalhe = _detalhe_erro(resposta)
        bruto = getattr(resposta, "text", "") or ""
        baixo = detalhe.lower()
        ultima = f"Gemini ({modelo}) retornou erro HTTP {status}: {detalhe}"

        problema_de_chave = any(t in baixo for t in ("api key", "api_key", "invalid key", "leaked"))
        if status == 401 or (status in (400, 403) and problema_de_chave):
            return _Resultado(erro=ultima, fatal=True, trocar_chave=True,
                              motivo="credencial recusada pelo Google")

        if status == 400:
            # A API muda os parâmetros aceitos de uma geração de modelo para outra.
            # Em vez de depender de acompanhar cada mudança, tiramos o parâmetro
            # recusado e tentamos de novo.
            if nivel and ("thinking" in baixo or "thought" in baixo):
                nivel = None
                ajustes += 1
                continue
            if sistema and not sistema_no_prompt and "system" in baixo:
                sistema_no_prompt = True
                ajustes += 1
                continue
            return _Resultado(erro=ultima)

        if status in (403, 404):
            # modelo indisponível para esta chave: não adianta tentar de novo nesta execução
            motivo = "modelo não encontrado (HTTP 404)" if status == 404 else "sem permissão para este modelo (HTTP 403)"
            return _Resultado(erro=ultima, motivo=motivo, bloqueio=math.inf)

        if status == 429:
            if _cota_diaria(bruto):
                return _Resultado(
                    erro=ultima + " (cota diária esgotada ou sem acesso a este modelo)",
                    motivo="sem cota ou sem acesso a este modelo na sua chave (HTTP 429)",
                    bloqueio=math.inf,
                )
            espera = _espera_sugerida(resposta)
            if espera is None:
                espera = _espera_exponencial(falhas + 1)
            if espera > espera_maxima:
                return _Resultado(
                    erro=ultima + f" (o servidor pediu {espera:.0f}s de espera)",
                    motivo=f"limite de uso, o servidor pediu {espera:.0f}s de espera (HTTP 429)",
                    bloqueio=espera,
                )
            falhas += 1
            bloqueio, motivo_curto = 60.0, "limite de requisições (HTTP 429)"
            if falhas < maximo_falhas:
                _avisar(f"Limite de requisições do Gemini ({modelo}): aguardando {espera:.0f}s para tentar de novo...")
                _dormir(espera + 0.5)
            continue

        if status >= 500:
            falhas += 1
            bloqueio, motivo_curto = 60.0, f"serviço instável (HTTP {status})"
            if falhas < maximo_falhas:
                _dormir(_espera_exponencial(falhas))
            continue

        return _Resultado(erro=ultima)

    return _Resultado(erro=ultima, motivo=motivo_curto, bloqueio=bloqueio)


def usar_arquivo_de_preferencia(caminho) -> None:
    """Chamado pelo main.py. Lembra, entre uma execução e outra, qual modelo funcionou
    para a sua chave, para começar direto por ele em vez de testar o primeiro da
    lista, falhar e trocar. A lembrança vale IA_LEMBRAR_MODELO_DIAS dias: depois disso
    o programa volta a testar os modelos melhores, caso algum tenha passado a funcionar."""
    global arquivo_preferencia, _preferido
    arquivo_preferencia = Path(caminho)
    _preferido = None
    try:
        dados = json.loads(arquivo_preferencia.read_text(encoding="utf-8"))
        idade = (date.today() - date.fromisoformat(dados["data"])).days
        if (dados.get("provedor") == "gemini" and dados.get("modelo") in modelos_gemini()
                and 0 <= idade < int(_cfg("IA_LEMBRAR_MODELO_DIAS", 7))):
            _preferido = dados["modelo"]
    except (OSError, ValueError, KeyError, TypeError):
        pass  # sem arquivo, arquivo estragado ou vencido: segue a ordem normal da lista


def _lembrar_modelo(modelo: str, guardar_em_arquivo: bool) -> None:
    """Passa a começar por este modelo nesta execução e, se for seguro, nas próximas.
    A data só muda quando o modelo muda, para a lembrança poder vencer."""
    global _preferido
    mudou = modelo != _preferido
    _preferido = modelo
    if not (mudou and guardar_em_arquivo and arquivo_preferencia):
        return
    try:
        arquivo_preferencia.write_text(
            json.dumps({"provedor": "gemini", "modelo": modelo, "data": date.today().isoformat()}),
            encoding="utf-8",
        )
    except OSError:
        pass  # não conseguir gravar não pode atrapalhar a busca


def _bloquear(modelo: str, segundos: float, motivo: str) -> None:
    _bloqueados[modelo] = (math.inf if segundos == math.inf else _agora() + segundos, motivo)


def _bloqueado(modelo: str) -> bool:
    item = _bloqueados.get(modelo)
    if not item:
        return False
    if item[0] != math.inf and _agora() >= item[0]:
        del _bloqueados[modelo]  # o tempo de espera acabou: pode tentar de novo
        return False
    return True


def _modelos_na_ordem() -> tuple[list[str], list[str]]:
    """(modelos a tentar agora, motivos dos que estão de lado). O modelo que funcionou
    por último vai para a frente; os que falharam há pouco ficam de fora."""
    todos = modelos_gemini()
    livres = [m for m in todos if not _bloqueado(m)]
    if _preferido in livres:
        livres.remove(_preferido)
        livres.insert(0, _preferido)
    de_lado = [f"{m}: {_bloqueados[m][1]}" for m in todos if m in _bloqueados]
    return livres, de_lado


def _chamar_gemini(prompt: str, max_tokens: int, json_mode: bool, sistema: str | None) -> str | None:
    global ultimo_erro, modelo_usado
    chaves = chaves_gemini()
    if not chaves:
        ultimo_erro = "Nenhuma chave Gemini configurada (GEMINI_API_KEY[_2/_3...])."
        return None

    todos = modelos_gemini()
    modelos, de_lado = _modelos_na_ordem()
    if not modelos:
        ultimo_erro = "Nenhum modelo do Gemini está disponível agora: " + " | ".join(de_lado)
        return None

    problemas: list[str] = []
    todas_chaves_recusadas = False
    for posicao, modelo in enumerate(modelos):
        resultado_modelo = None
        for indice_chave, (nome_chave, chave) in enumerate(chaves, start=1):
            resultado = _tentar_modelo_gemini(modelo, chave, prompt, max_tokens, json_mode, sistema)
            resultado_modelo = resultado
            if resultado.texto is not None:
                modelo_usado = modelo
                melhores = todos[: todos.index(modelo)] if modelo in todos else []
                descartados = all(_bloqueados.get(m, (0.0, ""))[0] == math.inf for m in melhores)
                _lembrar_modelo(modelo, guardar_em_arquivo=descartados)
                return resultado.texto

            problemas.append(f"{nome_chave}: {resultado.erro}" if resultado.trocar_chave else resultado.erro)
            if resultado.trocar_chave:
                if indice_chave < len(chaves):
                    proxima_chave = chaves[indice_chave][0]
                    _avisar(f"A credencial Gemini {indice_chave} foi recusada. Testando {proxima_chave} como alternativa.")
                    continue
                todas_chaves_recusadas = True
                break
            # 429 não faz rotação de chaves: chaves do mesmo projeto compartilham cota.
            break

        if todas_chaves_recusadas:
            break
        if resultado_modelo is None:
            continue
        if resultado_modelo.bloqueio:
            _bloquear(modelo, resultado_modelo.bloqueio, resultado_modelo.motivo)
        if resultado_modelo.fatal and not resultado_modelo.trocar_chave:
            # Bloqueio de segurança / pedido inválido: não há motivo para repetir
            # o mesmo lote em modelos diferentes.
            break
        if posicao + 1 < len(modelos):
            proximo = modelos[posicao + 1]
            if resultado_modelo.bloqueio:
                _avisar(f"O modelo {modelo} está temporariamente indisponível ({resultado_modelo.motivo}). Tentando {proximo}.")
            else:
                _avisar(f"O modelo {modelo} não concluiu a solicitação. Tentando {proximo}.")

    unicos = list(dict.fromkeys(p for p in problemas if p))
    ultimo_erro = " | ".join(unicos)[:700] or "Falha desconhecida ao chamar o Gemini."
    if todas_chaves_recusadas:
        ultimo_erro = "Todas as chaves Gemini configuradas foram recusadas. Confira o .env e a situação das chaves no Google AI Studio. " + ultimo_erro
    return None


# ---------------------------------------------------------------------------
# Claude
# ---------------------------------------------------------------------------

def _chamar_claude(prompt: str, max_tokens: int, sistema: str | None) -> str | None:
    global ultimo_erro, modelo_usado
    try:
        import anthropic
    except ImportError:
        ultimo_erro = "Pacote 'anthropic' não instalado (rode: pip install anthropic)."
        return None

    modelo = modelo_claude()
    limite = int(max_tokens)
    for tentativa in (1, 2):
        pedido = {"model": modelo, "max_tokens": limite, "messages": [{"role": "user", "content": prompt}]}
        if sistema:
            pedido["system"] = sistema
        try:
            cliente = anthropic.Anthropic(api_key=_limpar_chave(os.environ.get("ANTHROPIC_API_KEY", "")) or None,
                                          max_retries=4, timeout=120.0)
            resposta = cliente.messages.create(**pedido)
        except Exception as erro:
            ultimo_erro = f"Erro ao chamar o Claude ({modelo}): {erro}"
            return None

        texto = "".join(getattr(bloco, "text", "") or "" for bloco in resposta.content)
        if getattr(resposta, "stop_reason", None) == "max_tokens":
            if tentativa == 1 and limite < LIMITE_MAXIMO_TOKENS:
                limite = min(limite * 2, LIMITE_MAXIMO_TOKENS)  # resposta cortada: tenta com mais espaço
                continue
            ultimo_erro = f"Claude cortou a resposta por exceder o limite de tokens ({modelo})."
            return None
        if not texto.strip():
            ultimo_erro = f"Claude retornou uma resposta vazia ({modelo})."
            return None
        modelo_usado = modelo
        return texto
    return None


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------

def chamar_ia(prompt: str, max_tokens: int = 1500, json_mode: bool = False, sistema: str | None = None) -> str | None:
    """Chama o provedor de IA disponível (Gemini ou Claude) com o prompt informado.
    Retorna o texto da resposta, ou None se nenhum provedor estiver configurado ou
    se a chamada falhar por qualquer motivo (rede, cota excedida etc.). Nesse caso,
    o motivo detalhado fica em `ia.ultimo_erro`.

    `max_tokens` é o tamanho da resposta que você espera; a folga para o raciocínio
    do Gemini é somada automaticamente. `sistema` é a instrução fixa (regras do
    jogo), separada do `prompt`, que deve trazer só os dados da tarefa: isso ajuda a
    IA a não obedecer ordens escritas dentro do currículo ou das vagas."""
    global ultimo_erro
    ultimo_erro = None
    provedor = provedor_disponivel()
    if provedor == "gemini":
        return _chamar_gemini(prompt, max_tokens, json_mode, sistema)
    if provedor == "claude":
        return _chamar_claude(prompt, max_tokens, sistema)
    ultimo_erro = "Nenhuma chave de IA configurada (GEMINI_API_KEY ou ANTHROPIC_API_KEY)."
    return None


def decodificar_json(texto: str):
    """Converte o texto devolvido pela IA em objeto Python. Tolera cercas de
    markdown (```json), texto solto antes ou depois do JSON e listas cortadas no
    meio (nesse caso devolve os itens que chegaram completos). Se não houver nada
    aproveitável, lança json.JSONDecodeError."""
    limpo = re.sub(r"```(?:json)?", "", texto or "", flags=re.IGNORECASE).strip()
    try:
        return json.loads(limpo, strict=False)
    except json.JSONDecodeError as erro_original:
        posicoes = [p for p in (limpo.find("["), limpo.find("{")) if p != -1]
        if not posicoes:
            raise
        inicio = min(posicoes)
        decodificador = json.JSONDecoder(strict=False)

        # 1) JSON válido com texto solto antes ou depois
        try:
            objeto, _ = decodificador.raw_decode(limpo, inicio)
            return objeto
        except json.JSONDecodeError:
            pass

        # 2) Lista cortada no meio: aproveita os objetos que vieram inteiros
        if limpo[inicio] == "[":
            itens = []
            posicao = inicio + 1
            while posicao < len(limpo):
                while posicao < len(limpo) and limpo[posicao] in " \t\r\n,":
                    posicao += 1
                if posicao >= len(limpo) or limpo[posicao] == "]":
                    break
                try:
                    item, posicao = decodificador.raw_decode(limpo, posicao)
                except json.JSONDecodeError:
                    break
                itens.append(item)
            if itens:
                return itens
        raise erro_original


def chamar_ia_json(prompt: str, max_tokens: int = 1500, sistema: str | None = None) -> dict | list | None:
    """Atalho para chamadas que esperam uma resposta em JSON já decodificada.
    Retorna None se não houver provedor disponível, se a chamada falhar, ou se o
    JSON vier inválido (nesse último caso, `ia.ultimo_erro` também é preenchido)."""
    global ultimo_erro
    texto = chamar_ia(prompt, max_tokens=max_tokens, json_mode=True, sistema=sistema)
    if not texto:
        return None
    try:
        return decodificar_json(texto)
    except json.JSONDecodeError as erro:
        ultimo_erro = f"Resposta da IA não é um JSON válido (pode ter sido cortada): {erro}"
        return None
