"""
ia.py
Camada única de acesso a modelos de IA (Gemini ou Claude), usada por matcher.py,
resume_parser.py e mensagem.py. Detecta automaticamente qual provedor está
disponível (dá preferência ao Gemini, que é gratuito) e expõe uma função simples
`chamar_ia(prompt)` que os outros módulos usam sem se preocupar com qual provedor
está por trás.
"""

import os
import json
import time
import ast

import requests

GEMINI_MODEL = "gemini-3.7-flash"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
CLAUDE_MODEL = "claude-sonnet-4-6"

ultimo_erro: str | None = None


def provedor_disponivel() -> str | None:
    if any(k.startswith("GEMINI_API_KEY") for k in os.environ):
        return "gemini"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "claude"
    return None


def _chamar_gemini(prompt: str, max_tokens: int, json_mode: bool) -> str | None:
    global ultimo_erro
    
    chaves = [v.strip() for k, v in os.environ.items() if k.startswith("GEMINI_API_KEY") and v.strip()]
    if not chaves:
        ultimo_erro = "Nenhuma chave Gemini encontrada no .env."
        return None

    corpo = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": 4096},
    }

    max_tentativas = 10
    for tentativa in range(max_tentativas):
        chave_atual = chaves[tentativa % len(chaves)]
        
        try:
            resposta = requests.post(
                GEMINI_URL,
                headers={"x-goog-api-key": chave_atual, "Content-Type": "application/json"},
                json=corpo,
                timeout=60,
            )
        except requests.RequestException as erro:
            ultimo_erro = f"Falha de rede ao chamar o Gemini: {erro}"
            time.sleep(1)
            continue

        if resposta.ok:
            break
            
        if resposta.status_code in (503, 429) and tentativa < max_tentativas - 1:
            # Removido o print poluente daqui. Agora o script tenta a próxima chave silenciosamente.
            time.sleep(1.5)
            continue
            
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
        
        texto = "".join(parte.get("text", "") for parte in partes)
        
        if finish_reason == "MAX_TOKENS":
            ultimo_erro = "Gemini cortou a resposta por exceder o limite de tokens (finishReason=MAX_TOKENS)."
            
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
    global ultimo_erro
    max_tentativas_json = 3
    
    for tentativa in range(max_tentativas_json):
        texto = chamar_ia(prompt, max_tokens=max_tokens, json_mode=True)
        if not texto:
            return None
            
        try:
            texto_limpo = texto.replace("```json", "").replace("```", "").strip()
            return json.loads(texto_limpo, strict=False)
            
        except json.JSONDecodeError as erro:
            try:
                texto_py = texto_limpo.replace("null", "None").replace("true", "True").replace("false", "False")
                resultado = ast.literal_eval(texto_py)
                if isinstance(resultado, (dict, list)):
                    return resultado
            except Exception:
                pass 
            
            texto_debug = texto_limpo.replace("\n", " ")[:150]
            ultimo_erro = f"JSON inválido ({erro}). Trecho recebido: {texto_debug}..."
            
            if tentativa < max_tentativas_json - 1:
                time.sleep(1)
                continue
                
    return None