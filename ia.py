"""
ia.py
Camada única de acesso a modelos de IA (Gemini ou Claude), usada por matcher.py,
resume_parser.py e mensagem.py. Detecta automaticamente qual provedor está
disponível (dá preferência ao Gemini, que é gratuito) e expõe uma função simples
`chamar_ia(prompt)` que os outros módulos usam sem se preocupar com qual provedor
está por trás.

Se uma chamada falhar, o motivo real fica disponível em `ultimo_erro` (uma string
curta), para que o script consiga te avisar o que aconteceu de verdade, em vez de
simplesmente cair pro modo sem IA sem explicação.
"""

import os
import json

import requests

GEMINI_MODEL = "gemini-3.6-flash"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
CLAUDE_MODEL = "claude-sonnet-4-6"

ultimo_erro: str | None = None


def provedor_disponivel() -> str | None:
    """Retorna "gemini", "claude" ou None, conforme as chaves de API configuradas.
    Prioriza o Gemini por ser gratuito."""
    if os.environ.get("GEMINI_API_KEY"):
        return "gemini"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "claude"
    return None


def _post_gemini(chave: str, corpo: dict) -> requests.Response | None:
    global ultimo_erro
    try:
        return requests.post(
            GEMINI_URL,
            headers={"x-goog-api-key": chave, "Content-Type": "application/json"},
            json=corpo,
            timeout=60,
        )
    except requests.RequestException as erro:
        ultimo_erro = f"Falha de rede ao chamar o Gemini: {erro}"
        return None


def _chamar_gemini(prompt: str, max_tokens: int, json_mode: bool) -> str | None:
    global ultimo_erro
    chave = os.environ["GEMINI_API_KEY"]
    corpo = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": max_tokens},
    }
    if json_mode:
        corpo["generationConfig"]["responseMimeType"] = "application/json"
        # Desativa o "raciocínio interno" para tarefas de extração/classificação
        # estruturada: elas não precisam de raciocínio profundo, e o raciocínio
        # consome parte do limite de tokens antes da resposta final, o que pode
        # cortar o JSON no meio (erro "Unterminated string"). O nome do parâmetro
        # mudou entre gerações do Gemini (2.5 usa "thinkingBudget", 3.x usa
        # "thinkingLevel") — tentamos o formato atual e, se o modelo rejeitar
        # esse parâmetro (HTTP 400), tentamos de novo sem ele, para não depender
        # de acompanhar cada mudança de API manualmente.
        corpo["generationConfig"]["thinkingConfig"] = {"thinkingLevel": "minimal"}

    resposta = _post_gemini(chave, corpo)
    if resposta is None:
        return None

    if not resposta.ok and "thinking" in resposta.text.lower():
        corpo["generationConfig"].pop("thinkingConfig", None)
        resposta = _post_gemini(chave, corpo)
        if resposta is None:
            return None

    if not resposta.ok:
        detalhe = ""
        try:
            detalhe = resposta.json().get("error", {}).get("message", "")
        except Exception:
            detalhe = resposta.text[:300]
        ultimo_erro = f"Gemini retornou erro HTTP {resposta.status_code}: {detalhe}"
        return None

    try:
        dados = resposta.json()
        candidatos = dados.get("candidates")
        if not candidatos:
            motivo_bloqueio = dados.get("promptFeedback", {}).get("blockReason", "")
            ultimo_erro = f"Gemini não retornou candidatos na resposta.{(' Motivo: ' + motivo_bloqueio) if motivo_bloqueio else ''}"
            return None
        finish_reason = candidatos[0].get("finishReason", "")
        partes = candidatos[0].get("content", {}).get("parts")
        if not partes:
            ultimo_erro = f"Gemini retornou resposta sem conteúdo de texto (finishReason={finish_reason})."
            return None
        # O Gemini 3.6 Flash usa "thinking" por padrão e pode devolver várias partes:
        # um bloco de raciocínio interno (marcado com "thought": true) seguido da
        # resposta final. Pegar só partes[0] pode pegar o raciocínio (vazio de
        # conteúdo útil) em vez da resposta — por isso juntamos todas as partes que
        # NÃO são raciocínio interno.
        texto = "".join(p.get("text", "") for p in partes if isinstance(p, dict) and not p.get("thought"))
        if not texto.strip():
            ultimo_erro = f"Gemini retornou só raciocínio interno, sem resposta final (finishReason={finish_reason})."
            return None
        if finish_reason == "MAX_TOKENS":
            # Resposta cortada no meio — inútil para JSON (fica malformado) e
            # arriscado mesmo em texto livre. Melhor falhar aqui com uma mensagem
            # clara do que deixar o chamador tentar interpretar algo truncado.
            ultimo_erro = "Gemini cortou a resposta por exceder o limite de tokens (finishReason=MAX_TOKENS). Tente novamente ou aumente max_tokens."
            return None
        return texto
    except (KeyError, IndexError, ValueError) as erro:
        ultimo_erro = f"Resposta do Gemini em formato inesperado: {erro}"
        return None


def _chamar_claude(prompt: str, max_tokens: int, json_mode: bool) -> str | None:
    global ultimo_erro
    try:
        import anthropic
    except ImportError:
        ultimo_erro = "Pacote 'anthropic' não instalado (rode: pip install anthropic)."
        return None

    try:
        cliente = anthropic.Anthropic()
        resposta = cliente.messages.create(
            model=CLAUDE_MODEL, max_tokens=max_tokens, messages=[{"role": "user", "content": prompt}]
        )
        texto = "".join(bloco.text for bloco in resposta.content if hasattr(bloco, "text"))
        if json_mode:
            texto = texto.replace("```json", "").replace("```", "").strip()
        return texto
    except Exception as erro:
        ultimo_erro = f"Erro ao chamar o Claude: {erro}"
        return None


def chamar_ia(prompt: str, max_tokens: int = 1500, json_mode: bool = False) -> str | None:
    """Chama o provedor de IA disponível (Gemini ou Claude) com o prompt informado.
    Retorna o texto da resposta, ou None se nenhum provedor estiver configurado ou
    se a chamada falhar por qualquer motivo (rede, cota excedida, etc.) — nesse
    caso, o motivo detalhado fica disponível em `ia.ultimo_erro`."""
    global ultimo_erro
    ultimo_erro = None
    provedor = provedor_disponivel()
    if provedor == "gemini":
        return _chamar_gemini(prompt, max_tokens, json_mode)
    if provedor == "claude":
        return _chamar_claude(prompt, max_tokens, json_mode)
    ultimo_erro = "Nenhuma chave de IA configurada (GEMINI_API_KEY ou ANTHROPIC_API_KEY)."
    return None


def chamar_ia_json(prompt: str, max_tokens: int = 1500) -> dict | list | None:
    """Atalho para chamadas que esperam uma resposta em JSON já decodificada.
    Retorna None se não houver provedor disponível, se a chamada falhar, ou se o
    parsing do JSON falhar (nesse último caso, `ia.ultimo_erro` também é preenchido)."""
    global ultimo_erro
    texto = chamar_ia(prompt, max_tokens=max_tokens, json_mode=True)
    if not texto:
        return None
    try:
        texto_limpo = texto.replace("```json", "").replace("```", "").strip()
        return json.loads(texto_limpo, strict=False)
    except json.JSONDecodeError as erro:
        ultimo_erro = f"Resposta da IA não é um JSON válido (pode ter sido cortada): {erro}"
        return None