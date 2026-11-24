import json
from datetime import date, timedelta

import pytest
import requests

import ia


class FakeResposta:
    def __init__(self, status=200, corpo=None, headers=None):
        self.status_code = status
        self.ok = status < 400
        self._corpo = corpo if corpo is not None else {}
        self.text = json.dumps(self._corpo)
        self.headers = headers or {}

    def json(self):
        return self._corpo


def ok(texto, finish="STOP", extras=None):
    partes = (extras or []) + [{"text": texto}]
    return FakeResposta(200, {"candidates": [{"content": {"parts": partes}, "finishReason": finish}]})


def erro(status, mensagem, detalhes=None):
    return FakeResposta(status, {"error": {"code": status, "message": mensagem, "details": detalhes or []}})


class Servidor:
    """Substitui requests.post devolvendo respostas em sequência e registrando as chamadas."""

    def __init__(self, respostas):
        self.respostas = list(respostas)
        self.chamadas = []

    def __call__(self, url, headers=None, json=None, timeout=None):
        self.chamadas.append({"url": url, "corpo": json, "headers": headers})
        item = self.respostas.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture
def com_gemini(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "chave-falsa")

    def instalar(respostas):
        servidor = Servidor(respostas)
        monkeypatch.setattr(ia.requests, "post", servidor)
        return servidor

    return instalar


# ---------------------------------------------------------------- provedor

def test_sem_chave_explica_o_motivo():
    assert ia.provedor_disponivel() is None
    assert ia.chamar_ia("oi") is None
    assert "Nenhuma chave" in ia.ultimo_erro


def test_chave_com_aspas_e_espacos_e_aceita(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", ' "abc" ')
    assert ia.provedor_disponivel() == "gemini"


def test_desativar_desliga_a_ia_mesmo_com_chave(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    ia.desativar()
    assert ia.provedor_disponivel() is None


def test_ia_provedor_escolhe_quando_ha_duas_chaves(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "y")
    assert ia.provedor_disponivel() == "gemini"
    monkeypatch.setenv("IA_PROVEDOR", "claude")
    assert ia.provedor_disponivel() == "claude"


# ----------------------------------------------------------------- Gemini

def test_sucesso_ignora_blocos_de_raciocinio(com_gemini):
    servidor = com_gemini([ok("resposta final", extras=[{"text": "pensando...", "thought": True}])])
    assert ia.chamar_ia("oi", max_tokens=100) == "resposta final"
    assert ia.modelo_usado == "gemini-3.8-flash"
    corpo = servidor.chamadas[0]["corpo"]["generationConfig"]
    assert corpo["maxOutputTokens"] == 100 + 4096          # folga para o raciocínio
    assert corpo["thinkingConfig"] == {"thinkingLevel": "high"}
    assert servidor.chamadas[0]["headers"]["x-goog-api-key"] == "chave-falsa"


def test_json_mode_pede_application_json(com_gemini):
    servidor = com_gemini([ok('{"a": 1}')])
    assert ia.chamar_ia_json("oi") == {"a": 1}
    assert servidor.chamadas[0]["corpo"]["generationConfig"]["responseMimeType"] == "application/json"


def test_texto_livre_nao_pede_json(com_gemini):
    servidor = com_gemini([ok("oi")])
    ia.chamar_ia("oi")
    assert "responseMimeType" not in servidor.chamadas[0]["corpo"]["generationConfig"]


def test_instrucao_de_sistema_vai_separada_dos_dados(com_gemini):
    servidor = com_gemini([ok("ok")])
    ia.chamar_ia("dados", sistema="regras")
    corpo = servidor.chamadas[0]["corpo"]
    assert corpo["systemInstruction"] == {"parts": [{"text": "regras"}]}
    assert corpo["contents"][0]["parts"][0]["text"] == "dados"


def test_sistema_recusado_vai_junto_do_prompt(com_gemini):
    servidor = com_gemini([erro(400, "Invalid argument: system_instruction not supported"), ok("ok")])
    assert ia.chamar_ia("dados", sistema="regras") == "ok"
    segundo = servidor.chamadas[1]["corpo"]
    assert "systemInstruction" not in segundo
    assert segundo["contents"][0]["parts"][0]["text"] == "regras\n\ndados"


def test_429_respeita_o_tempo_pedido_pelo_servidor(com_gemini, monkeypatch):
    esperas = []
    avisos = []
    monkeypatch.setattr(ia, "_dormir", esperas.append)
    monkeypatch.setattr(ia, "aviso_callback", avisos.append)
    detalhes = [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "12s"}]
    servidor = com_gemini([erro(429, "Resource exhausted", detalhes), ok("deu certo")])
    assert ia.chamar_ia("oi") == "deu certo"
    assert len(servidor.chamadas) == 2
    assert esperas and 12 <= esperas[0] <= 14
    assert avisos and "12s" in avisos[0]


def test_cota_diaria_troca_de_modelo_sem_esperar(com_gemini, monkeypatch):
    esperas = []
    avisos = []
    monkeypatch.setattr(ia, "_dormir", esperas.append)
    monkeypatch.setattr(ia, "aviso_callback", avisos.append)
    msg = "Quota exceeded: GenerateRequestsPerDayPerProjectPerModel-FreeTier"
    servidor = com_gemini([erro(429, msg), ok("do segundo modelo")])
    assert ia.chamar_ia("oi") == "do segundo modelo"
    assert ia.modelo_usado == "gemini-3.5-flash-lite"
    assert "gemini-3.8-flash" in servidor.chamadas[0]["url"]
    assert "gemini-3.5-flash-lite" in servidor.chamadas[1]["url"]
    assert esperas == []
    assert any("gemini-3.5-flash-lite" in a for a in avisos)


def test_limite_zero_no_plano_gratuito_troca_de_modelo(com_gemini):
    servidor = com_gemini([erro(429, "Quota exceeded for metric ... limit: 0, model: gemini-3.8-flash"), ok("ok")])
    assert ia.chamar_ia("oi") == "ok"
    assert ia.modelo_usado == "gemini-3.5-flash-lite"


def test_espera_muito_longa_passa_para_o_proximo_modelo(com_gemini):
    detalhes = [{"retryDelay": "300s"}]
    com_gemini([erro(429, "limite", detalhes), ok("ok")])
    assert ia.chamar_ia("oi") == "ok"
    assert ia.modelo_usado == "gemini-3.5-flash-lite"


def test_nivel_de_raciocinio_recusado_repete_sem_raciocinio(com_gemini):
    servidor = com_gemini([erro(400, "Thinking level MINIMAL is not supported for this model"), ok("ok")])
    assert ia.chamar_ia("oi") == "ok"
    assert "thinkingConfig" in servidor.chamadas[0]["corpo"]["generationConfig"]
    assert "thinkingConfig" not in servidor.chamadas[1]["corpo"]["generationConfig"]
    assert ia.modelo_usado == "gemini-3.8-flash"           # não trocou de modelo à toa


def test_max_tokens_dobra_o_limite_e_tenta_de_novo(com_gemini):
    servidor = com_gemini([ok("cort", finish="MAX_TOKENS"), ok("completo")])
    assert ia.chamar_ia("oi", max_tokens=1000) == "completo"
    primeiro = servidor.chamadas[0]["corpo"]["generationConfig"]["maxOutputTokens"]
    segundo = servidor.chamadas[1]["corpo"]["generationConfig"]["maxOutputTokens"]
    assert segundo == primeiro * 2


def test_chave_invalida_para_tudo(com_gemini):
    servidor = com_gemini([erro(400, "API key not valid. Please pass a valid API key.")])
    assert ia.chamar_ia("oi") is None
    assert len(servidor.chamadas) == 1                      # não tentou outros modelos
    assert "API key" in ia.ultimo_erro


def test_modelo_inexistente_vai_para_o_proximo(com_gemini):
    com_gemini([erro(404, "models/gemini-3.8-flash is not found"), ok("ok")])
    assert ia.chamar_ia("oi") == "ok"
    assert ia.modelo_usado == "gemini-3.5-flash-lite"


def test_falha_de_rede_tenta_de_novo(com_gemini):
    servidor = com_gemini([requests.ConnectionError("sem internet"), ok("voltou")])
    assert ia.chamar_ia("oi") == "voltou"
    assert len(servidor.chamadas) == 2


def test_erro_503_repete_no_mesmo_modelo(com_gemini):
    com_gemini([erro(503, "overloaded"), erro(503, "overloaded"), ok("ok")])
    assert ia.chamar_ia("oi") == "ok"
    assert ia.modelo_usado == "gemini-3.8-flash"


def test_todos_os_modelos_falhando_informa_o_motivo(com_gemini, monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "gemini-x")
    com_gemini([erro(500, "falha"), erro(500, "falha"), erro(500, "falha")])
    assert ia.chamar_ia("oi") is None
    assert "HTTP 500" in ia.ultimo_erro


def test_bloqueio_de_seguranca_nao_fica_repetindo(com_gemini):
    servidor = com_gemini([ok("x", finish="SAFETY")] * 3)
    assert ia.chamar_ia("oi") is None
    assert len(servidor.chamadas) == 2                      # 1 por modelo padrão disponível, sem repetir
    assert "bloqueou" in ia.ultimo_erro


def test_gemini_model_no_ambiente_forca_um_modelo(com_gemini, monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
    servidor = com_gemini([ok("ok")])
    ia.chamar_ia("oi")
    assert "gemini-3.5-flash-lite" in servidor.chamadas[0]["url"]


def test_gemini_model_aceita_lista_separada_por_virgula(monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", " a , b ")
    assert ia.modelos_gemini() == ["a", "b"]


# ------------------------------------------------------------------- JSON

@pytest.mark.parametrize("texto", [
    '```json\n[{"a": 1}]\n```',
    'Claro! Aqui está:\n[{"a": 1}]\nEspero ter ajudado.',
    '[{"a": 1}]',
])
def test_decodificar_json_tolera_cercas_e_texto_solto(texto):
    assert ia.decodificar_json(texto) == [{"a": 1}]


def test_decodificar_json_aproveita_itens_completos_de_lista_cortada():
    cortado = '[{"indice": 0, "nota": 80, "motivo": "ok"}, {"indice": 1, "nota": 40, "motivo": "meio"}, {"indice": 2, "no'
    assert ia.decodificar_json(cortado) == [
        {"indice": 0, "nota": 80, "motivo": "ok"},
        {"indice": 1, "nota": 40, "motivo": "meio"},
    ]


def test_decodificar_json_sem_nada_aproveitavel_levanta_erro():
    with pytest.raises(json.JSONDecodeError):
        ia.decodificar_json("sem json nenhum aqui")
    with pytest.raises(json.JSONDecodeError):
        ia.decodificar_json('[{"a": 1')


def test_json_quebrado_vira_erro_claro(com_gemini):
    com_gemini([ok('[{"a": 1')])
    assert ia.chamar_ia_json("oi") is None
    assert "JSON" in ia.ultimo_erro


def test_json_cortado_devolve_o_que_deu(com_gemini):
    com_gemini([ok('[{"a": 1}, {"a": 2}, {"a"')])
    assert ia.chamar_ia_json("oi") == [{"a": 1}, {"a": 2}]


# ----------------------------------------------------------------- Claude

def _instalar_claude_falso(monkeypatch, respostas):
    import sys
    import types

    chamadas = []

    class Bloco:
        def __init__(self, texto):
            self.text = texto

    class Resp:
        def __init__(self, texto, parada="end_turn"):
            self.content = [Bloco(texto)]
            self.stop_reason = parada

    class Mensagens:
        def create(self, **kw):
            chamadas.append(kw)
            texto, parada = respostas.pop(0)
            return Resp(texto, parada)

    class Cliente:
        def __init__(self, **kw):
            self.messages = Mensagens()

    monkeypatch.setitem(sys.modules, "anthropic", types.SimpleNamespace(Anthropic=Cliente))
    return chamadas


def test_claude_quando_nao_ha_gemini(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave")
    chamadas = _instalar_claude_falso(monkeypatch, [("olá do claude", "end_turn")])
    assert ia.provedor_disponivel() == "claude"
    assert ia.chamar_ia("oi", max_tokens=50, sistema="regras") == "olá do claude"
    assert chamadas[0]["model"] == "claude-sonnet-5-5"
    assert chamadas[0]["max_tokens"] == 50
    assert chamadas[0]["system"] == "regras"
    assert ia.modelo_usado == "claude-sonnet-5-5"


def test_claude_model_no_ambiente_troca_o_modelo(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave")
    monkeypatch.setenv("CLAUDE_MODEL", "claude-haiku-5-5")
    chamadas = _instalar_claude_falso(monkeypatch, [("ok", "end_turn")])
    ia.chamar_ia("oi")
    assert chamadas[0]["model"] == "claude-haiku-5-5"


def test_claude_resposta_cortada_tenta_com_mais_espaco(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave")
    chamadas = _instalar_claude_falso(monkeypatch, [("cort", "max_tokens"), ("completo", "end_turn")])
    assert ia.chamar_ia("oi", max_tokens=100) == "completo"
    assert chamadas[1]["max_tokens"] == 200


def test_claude_sem_pacote_instalado_explica(monkeypatch):
    import builtins

    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave")
    monkeypatch.delitem(__import__("sys").modules, "anthropic", raising=False)
    real = builtins.__import__

    def sem_anthropic(nome, *a, **kw):
        if nome == "anthropic":
            raise ImportError("sem pacote")
        return real(nome, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", sem_anthropic)
    assert ia.chamar_ia("oi") is None
    assert "pip install anthropic" in ia.ultimo_erro


# ---------------------------------------------------------------- memória de modelos
# Relato do usuário: o gemini-3.8-flash falhava e era tentado DE NOVO em cada lote de vagas
# ("Não consegui usar o modelo gemini-3.8-flash. Tentando gemini-3.5-flash-lite..." várias vezes).

SEM_COTA = "Quota exceeded: GenerateRequestsPerDayPerProjectPerModel-FreeTier"
INFINITO = float("inf")


def _modelos_chamados(servidor):
    return [c["url"].split("/models/")[1].split(":")[0] for c in servidor.chamadas]


def test_modelo_que_falhou_so_e_tentado_uma_vez_por_execucao(com_gemini):
    servidor = com_gemini([erro(429, SEM_COTA)] + [ok("x")] * 5)
    for _ in range(5):                       # ex.: perfil + 4 lotes de vagas
        assert ia.chamar_ia("oi") == "x"
    chamados = _modelos_chamados(servidor)
    assert chamados.count("gemini-3.8-flash") == 1       # antes: uma falha por chamada
    assert chamados[1:] == ["gemini-3.5-flash-lite"] * 5


def test_o_aviso_diz_o_motivo_e_aparece_uma_vez_so(com_gemini, monkeypatch):
    avisos = []
    monkeypatch.setattr(ia, "aviso_callback", avisos.append)
    com_gemini([erro(429, SEM_COTA)] + [ok("x")] * 4)
    for _ in range(4):
        ia.chamar_ia("oi")
    assert len(avisos) == 1
    assert "gemini-3.8-flash" in avisos[0] and "gemini-3.5-flash-lite" in avisos[0]
    assert "sem cota" in avisos[0] and "HTTP 429" in avisos[0]


@pytest.mark.parametrize("status", [403, 404])
def test_modelo_inexistente_ou_sem_permissao_fica_de_lado(com_gemini, status):
    servidor = com_gemini([erro(status, "sem acesso"), ok("a"), ok("b")])
    ia.chamar_ia("1")
    ia.chamar_ia("2")
    assert _modelos_chamados(servidor) == ["gemini-3.8-flash", "gemini-3.5-flash-lite", "gemini-3.5-flash-lite"]
    assert ia._bloqueados["gemini-3.8-flash"][0] == INFINITO


def test_limite_por_minuto_deixa_o_modelo_de_lado_so_por_um_tempo(com_gemini, monkeypatch):
    relogio = [1000.0]
    monkeypatch.setattr(ia, "_agora", lambda: relogio[0])
    servidor = com_gemini([erro(429, "limite", [{"retryDelay": "1s"}])] * 3 + [ok("a")])
    assert ia.chamar_ia("1") == "a"                    # 3.8 esgota as 3 tentativas; 3.6 responde
    livres, de_lado = ia._modelos_na_ordem()
    assert "gemini-3.8-flash" not in livres and any("gemini-3.8-flash" in d for d in de_lado)
    relogio[0] += 61                                    # passou o tempo de espera
    livres, _ = ia._modelos_na_ordem()
    assert "gemini-3.8-flash" in livres


def test_servidor_instavel_tambem_gera_pausa_curta_e_nao_definitiva(com_gemini):
    com_gemini([erro(503, "overloaded")] * 3 + [ok("a")])
    assert ia.chamar_ia("1") == "a"
    quando, motivo = ia._bloqueados["gemini-3.8-flash"]
    assert quando != INFINITO and "503" in motivo


def test_falha_de_rede_nao_bloqueia_nenhum_modelo(com_gemini):
    com_gemini([requests.ConnectionError("sem internet")] * 9)
    assert ia.chamar_ia("oi") is None
    assert ia._bloqueados == {}


def test_com_todos_os_modelos_de_lado_nem_chama_a_api(com_gemini):
    servidor = com_gemini([erro(404, "nf")] * 3)
    assert ia.chamar_ia("1") is None
    assert len(servidor.chamadas) == 2
    assert ia.chamar_ia("2") is None
    assert len(servidor.chamadas) == 2                  # nenhuma chamada nova
    assert "Nenhum modelo" in ia.ultimo_erro


def test_modelo_que_funcionou_vai_para_a_frente_da_fila(com_gemini):
    servidor = com_gemini([erro(404, "nf"), ok("a"), ok("b")])
    ia.chamar_ia("1")
    assert ia._modelos_na_ordem()[0][0] == "gemini-3.5-flash-lite"


# ------------------------------------------------ lembrança entre execuções (arquivo)

def test_lembra_o_modelo_que_funcionou_na_proxima_execucao(com_gemini, tmp_path):
    arquivo = tmp_path / "modelo.json"
    ia.usar_arquivo_de_preferencia(arquivo)
    com_gemini([erro(404, "nf"), ok("a")])
    assert ia.chamar_ia("1") == "a"
    dados = json.loads(arquivo.read_text(encoding="utf-8"))
    assert dados["provedor"] == "gemini" and dados["modelo"] == "gemini-3.5-flash-lite"

    ia._bloqueados.clear()                              # "nova execução": a memória em RAM zera
    ia._preferido = None
    ia.usar_arquivo_de_preferencia(arquivo)
    servidor = com_gemini([ok("b")])
    assert ia.chamar_ia("2") == "b"
    assert _modelos_chamados(servidor) == ["gemini-3.5-flash-lite"]   # foi direto, sem testar o 3.8


def _gravar(arquivo, modelo="gemini-3.5-flash-lite", dias_atras=0, provedor="gemini"):
    dados = {"provedor": provedor, "modelo": modelo, "data": (date.today() - timedelta(days=dias_atras)).isoformat()}
    arquivo.write_text(json.dumps(dados), encoding="utf-8")
    return dados


def test_lembranca_vencida_e_ignorada_para_voltar_a_testar_os_melhores(tmp_path):
    arquivo = tmp_path / "m.json"
    _gravar(arquivo, dias_atras=10)
    ia.usar_arquivo_de_preferencia(arquivo)
    assert ia._preferido is None


def test_lembranca_de_modelo_fora_da_lista_e_ignorada(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.8-flash")        # o usuário fixou outro modelo
    arquivo = tmp_path / "m.json"
    _gravar(arquivo, "gemini-3.5-flash-lite")
    ia.usar_arquivo_de_preferencia(arquivo)
    assert ia._preferido is None


def test_arquivo_estragado_ou_ausente_nao_derruba(tmp_path):
    arquivo = tmp_path / "m.json"
    ia.usar_arquivo_de_preferencia(arquivo)                       # não existe
    assert ia._preferido is None
    arquivo.write_text("{isto nao e json", encoding="utf-8")
    ia.usar_arquivo_de_preferencia(arquivo)
    assert ia._preferido is None


def test_prazo_zero_desliga_a_lembranca(tmp_path, monkeypatch):
    monkeypatch.setattr(ia.config, "IA_LEMBRAR_MODELO_DIAS", 0, raising=False)
    arquivo = tmp_path / "m.json"
    _gravar(arquivo)
    ia.usar_arquivo_de_preferencia(arquivo)
    assert ia._preferido is None


def test_falha_so_passageira_do_melhor_modelo_nao_vira_lembranca_em_arquivo(com_gemini, tmp_path):
    arquivo = tmp_path / "m.json"
    ia.usar_arquivo_de_preferencia(arquivo)
    com_gemini([erro(503, "overloaded")] * 3 + [ok("a")])
    assert ia.chamar_ia("1") == "a"
    assert ia._preferido == "gemini-3.5-flash-lite"                    # vale só nesta execução
    assert not arquivo.exists()


def test_nao_regrava_o_arquivo_se_o_modelo_continua_o_mesmo(com_gemini, tmp_path):
    arquivo = tmp_path / "m.json"
    antes = _gravar(arquivo, dias_atras=3)
    ia.usar_arquivo_de_preferencia(arquivo)
    com_gemini([ok("a")])
    assert ia.chamar_ia("1") == "a"
    assert json.loads(arquivo.read_text(encoding="utf-8")) == antes   # a data original fica: a lembrança pode vencer


def test_se_o_modelo_lembrado_parar_de_funcionar_o_arquivo_e_atualizado(com_gemini, tmp_path):
    arquivo = tmp_path / "m.json"
    _gravar(arquivo, "gemini-3.5-flash-lite", dias_atras=2)
    ia.usar_arquivo_de_preferencia(arquivo)
    servidor = com_gemini([erro(404, "nf"), ok("a")])
    assert ia.chamar_ia("1") == "a"
    assert _modelos_chamados(servidor) == ["gemini-3.5-flash-lite", "gemini-3.8-flash"]
    assert json.loads(arquivo.read_text(encoding="utf-8"))["modelo"] == "gemini-3.8-flash"


def test_gravar_no_arquivo_falhando_nao_atrapalha(com_gemini, tmp_path):
    ia.usar_arquivo_de_preferencia(tmp_path / "pasta_que_nao_existe" / "m.json")
    com_gemini([erro(404, "nf"), ok("a")])
    assert ia.chamar_ia("1") == "a"



def test_reconhece_tres_chaves_sem_expor_o_valor(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "base")
    monkeypatch.setenv("GEMINI_API_KEY_2", "alternativa-2")
    monkeypatch.setenv("GEMINI_API_KEY_3", "alternativa-3")
    assert ia.chaves_gemini() == [
        ("GEMINI_API_KEY", "base"),
        ("GEMINI_API_KEY_2", "alternativa-2"),
        ("GEMINI_API_KEY_3", "alternativa-3"),
    ]


def test_credencial_recusada_tenta_a_proxima_chave(monkeypatch, com_gemini):
    monkeypatch.setenv("GEMINI_API_KEY_2", "chave-alternativa")
    servidor = com_gemini([
        erro(400, "API key not valid. Please pass a valid API key."),
        ok("resposta com a chave alternativa"),
    ])
    assert ia.chamar_ia("oi") == "resposta com a chave alternativa"
    assert servidor.chamadas[0]["headers"]["x-goog-api-key"] == "chave-falsa"
    assert servidor.chamadas[1]["headers"]["x-goog-api-key"] == "chave-alternativa"


def test_429_nao_faz_rotacao_de_chaves_do_mesmo_projeto(monkeypatch, com_gemini):
    monkeypatch.setenv("GEMINI_API_KEY_2", "chave-alternativa")
    monkeypatch.setattr(ia, "_dormir", lambda _segundos: None)
    servidor = com_gemini([
        erro(429, "Quota exceeded: GenerateRequestsPerDayPerProjectPerModel-FreeTier"),
        ok("fallback para o próximo modelo"),
    ])
    assert ia.chamar_ia("oi") == "fallback para o próximo modelo"
    assert all(c["headers"]["x-goog-api-key"] == "chave-falsa" for c in servidor.chamadas)
    assert "gemini-3.8-flash" in servidor.chamadas[0]["url"]
    assert "gemini-3.5-flash-lite" in servidor.chamadas[1]["url"]


def test_modelos_padrao_nao_tentam_modelo_3_6_obsoleto(monkeypatch):
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    modelos = ia.modelos_gemini()
    assert modelos[0] == "gemini-3.8-flash"
    assert "gemini-3.6-flash" not in modelos
