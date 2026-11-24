import json
from datetime import date, timedelta

from historico import DIAS_PARA_ESQUECER, Historico, chave_da_vaga, chave_do_contexto

HOJE = date(2026, 11, 10)
CTX = "contexto-a"


def abrir(caminho, hoje=HOJE, **extra):
    return Historico(caminho, hoje=hoje, **extra)


# ------------------------------------------------------------------ vagas novas

def test_na_primeira_execucao_nada_e_marcado_como_novo(tmp_path, vaga):
    historico = abrir(tmp_path / "h.json")
    assert historico.primeira_execucao
    assert not historico.eh_nova(vaga(titulo="A", link="https://x.com/1"))


def test_depois_da_primeira_execucao_so_as_nao_vistas_sao_novas(tmp_path, vaga):
    caminho = tmp_path / "h.json"
    antiga = vaga(titulo="A", link="https://x.com/1")
    primeira = abrir(caminho)
    primeira.registrar_vistas([antiga])
    assert primeira.salvar()

    segunda = abrir(caminho, hoje=HOJE + timedelta(days=1))
    assert not segunda.primeira_execucao
    assert not segunda.eh_nova(antiga)
    assert segunda.eh_nova(vaga(titulo="B", link="https://x.com/2"))


def test_link_com_parametros_de_rastreamento_e_a_mesma_vaga(tmp_path, vaga):
    caminho = tmp_path / "h.json"
    primeira = abrir(caminho)
    primeira.registrar_vistas([vaga(link="https://www.x.com/vaga/1?utm_source=google&trk=abc")])
    primeira.salvar()

    segunda = abrir(caminho)
    assert not segunda.eh_nova(vaga(link="https://x.com/vaga/1"))


def test_vaga_avaliada_mas_nunca_mostrada_continua_sendo_nova(tmp_path, vaga):
    caminho = tmp_path / "h.json"
    v = vaga(titulo="A", link="https://x.com/1")
    primeira = abrir(caminho)
    primeira.guardar_avaliacao(v, CTX, 70, "ok")
    primeira.salvar()

    assert abrir(caminho).eh_nova(v)


def test_vaga_sem_como_ser_identificada_nao_e_guardada(tmp_path, vaga):
    sem_nada = vaga()  # sem link, sem empresa
    assert chave_da_vaga(sem_nada) == ""
    historico = abrir(tmp_path / "h.json")
    historico.guardar_avaliacao(sem_nada, CTX, 50, "x")
    historico.registrar_vistas([sem_nada])
    assert historico.nota_em_cache(sem_nada, CTX) is None
    assert historico.vagas == {}


# ------------------------------------------------------------------ cache de notas

def test_nota_em_cache_volta_com_o_mesmo_contexto(tmp_path, vaga):
    caminho = tmp_path / "h.json"
    v = vaga(titulo="A", link="https://x.com/1")
    primeira = abrir(caminho)
    primeira.guardar_avaliacao(v, CTX, 72.46, "Tem experiência em estoque")
    primeira.salvar()

    assert abrir(caminho).nota_em_cache(v, CTX) == (72.5, "Tem experiência em estoque")


def test_cache_nao_vale_para_outro_contexto(tmp_path, vaga):
    caminho = tmp_path / "h.json"
    v = vaga(titulo="A", link="https://x.com/1")
    primeira = abrir(caminho)
    primeira.guardar_avaliacao(v, CTX, 70, "ok")
    primeira.salvar()

    assert abrir(caminho).nota_em_cache(v, "contexto-b") is None


def test_cache_expira_depois_da_validade(tmp_path, vaga):
    caminho = tmp_path / "h.json"
    v = vaga(titulo="A", link="https://x.com/1")
    primeira = abrir(caminho, validade_dias=14)
    primeira.guardar_avaliacao(v, CTX, 70, "ok")
    primeira.salvar()

    assert abrir(caminho, hoje=HOJE + timedelta(days=14), validade_dias=14).nota_em_cache(v, CTX) is not None
    assert abrir(caminho, hoje=HOJE + timedelta(days=15), validade_dias=14).nota_em_cache(v, CTX) is None


def test_sem_cache_ignora_notas_guardadas_mas_continua_gravando(tmp_path, vaga):
    caminho = tmp_path / "h.json"
    v = vaga(titulo="A", link="https://x.com/1")
    primeira = abrir(caminho)
    primeira.guardar_avaliacao(v, CTX, 70, "ok")
    primeira.salvar()

    refazendo = abrir(caminho, usar_cache=False)
    assert refazendo.nota_em_cache(v, CTX) is None
    refazendo.guardar_avaliacao(v, CTX, 30, "refeita")
    refazendo.salvar()
    assert abrir(caminho).nota_em_cache(v, CTX) == (30.0, "refeita")


def test_chave_do_contexto_muda_com_qualquer_ingrediente():
    base = chave_do_contexto("curriculo", {"cidade": "Rio", "bairro": "Bangu", "uf": "RJ"}, "v1")
    assert base == chave_do_contexto("curriculo", {"cidade": "Rio", "bairro": "Bangu", "uf": "RJ"}, "v1")
    assert base != chave_do_contexto("curriculo novo", {"cidade": "Rio", "bairro": "Bangu", "uf": "RJ"}, "v1")
    assert base != chave_do_contexto("curriculo", {"cidade": "Niterói", "bairro": "Bangu", "uf": "RJ"}, "v1")
    assert base != chave_do_contexto("curriculo", {"cidade": "Rio", "bairro": "Bangu", "uf": "SP"}, "v1")
    assert base != chave_do_contexto("curriculo", {"cidade": "Rio", "bairro": "Bangu", "uf": "RJ"}, "v2")


# ------------------------------------------------------------------ arquivo

def test_arquivo_nao_guarda_o_texto_do_curriculo(tmp_path, vaga):
    caminho = tmp_path / "h.json"
    historico = abrir(caminho)
    historico.guardar_avaliacao(vaga(link="https://x.com/1"), chave_do_contexto("SEGREDO DO CURRICULO", {}, "v1"), 50, "ok")
    historico.salvar()
    assert "SEGREDO" not in caminho.read_text(encoding="utf-8")


def test_arquivo_corrompido_e_ignorado_sem_quebrar(tmp_path, vaga):
    caminho = tmp_path / "h.json"
    caminho.write_text("{isto nao e json", encoding="utf-8")
    historico = abrir(caminho)
    assert historico.aviso
    assert historico.primeira_execucao
    historico.registrar_vistas([vaga(link="https://x.com/1")])
    assert historico.salvar()
    assert json.loads(caminho.read_text(encoding="utf-8"))["vagas"]


def test_formato_desconhecido_tambem_e_ignorado(tmp_path):
    caminho = tmp_path / "h.json"
    caminho.write_text(json.dumps({"versao": 0, "vagas": {}}), encoding="utf-8")
    assert abrir(caminho).aviso


def test_salvar_em_pasta_que_nao_existe_devolve_false_sem_quebrar(tmp_path):
    assert abrir(tmp_path / "nao_existe" / "h.json").salvar() is False


def test_vagas_nao_vistas_ha_muito_tempo_saem_do_arquivo(tmp_path):
    caminho = tmp_path / "h.json"
    velha = (HOJE - timedelta(days=DIAS_PARA_ESQUECER + 1)).isoformat()
    recente = (HOJE - timedelta(days=5)).isoformat()
    caminho.write_text(json.dumps({"versao": 1, "vagas": {
        "https://x.com/velha": {"primeira_vez": velha, "ultima_vez": velha},
        "https://x.com/recente": {"primeira_vez": recente, "ultima_vez": recente},
    }}), encoding="utf-8")

    historico = abrir(caminho)
    historico.salvar()
    guardadas = json.loads(caminho.read_text(encoding="utf-8"))["vagas"]
    assert list(guardadas) == ["https://x.com/recente"]


def test_gravacao_nao_deixa_arquivo_temporario(tmp_path, vaga):
    historico = abrir(tmp_path / "h.json")
    historico.registrar_vistas([vaga(link="https://x.com/1")])
    historico.salvar()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["h.json"]
