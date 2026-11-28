from carreira_store import CareerStore, id_da_vaga


def test_registra_vagas_e_preserva_favoritos_status_e_notas(tmp_path):
    db = CareerStore(tmp_path / "carreira.sqlite3")
    job = {"id": "a" * 32, "url": "https://example.com/vaga", "title": "Técnico de TI",
           "company": "Empresa", "city": "Rio de Janeiro", "source": "Portal", "score": 85}
    db.registrar_vagas([job])
    saved = db.atualizar({"job_id": job["id"], **{k: v for k, v in job.items() if k != "id"},
                          "favorite": True, "status": "Candidatura enviada", "notes": "Retornar na sexta"})
    assert saved["favorite"] == 1
    assert saved["status"] == "Candidatura enviada"
    assert saved["notes"] == "Retornar na sexta"

    # Nova coleta da mesma vaga atualiza dados do anúncio, mas não apaga o acompanhamento.
    db.registrar_vagas([{**job, "title": "Técnico de TI N1", "score": 91}])
    stored = db.listar()["a" * 32]
    assert stored["title"] == "Técnico de TI N1"
    assert stored["favorite"] == 1
    assert stored["status"] == "Candidatura enviada"
    assert stored["notes"] == "Retornar na sexta"


def test_eventos_registram_etapa_favorito_e_notas(tmp_path):
    db = CareerStore(tmp_path / "carreira.sqlite3")
    job = {"job_id": "b" * 32, "url": "https://example.com/2", "title": "Auxiliar de CPD",
           "company": "Mercado", "city": "Niterói", "source": "Portal", "score": 90}
    db.atualizar({**job, "status": "Quero me candidatar", "favorite": False, "notes": ""})
    db.atualizar({**job, "status": "Quero me candidatar", "favorite": True, "notes": ""})
    db.atualizar({**job, "status": "Candidatura enviada", "favorite": True, "notes": "Currículo enviado"})
    events = db.eventos("b" * 32)
    detalhes = [event["detail"] for event in events]
    assert len(events) >= 3
    assert "Etapa da candidatura atualizada" in detalhes
    assert "Adicionada aos favoritos" in detalhes
    assert "Notas de acompanhamento atualizadas" in detalhes


def test_resumo_distingue_registradas_de_acompanhadas(tmp_path):
    db = CareerStore(tmp_path / "carreira.sqlite3")
    db.registrar_vagas([
        {"id": "c" * 32, "url": "https://example.com/3", "title": "Vaga 1"},
        {"id": "d" * 32, "url": "https://example.com/4", "title": "Vaga 2"},
    ])
    resumo = db.resumo()
    assert resumo["registradas"] == 2
    assert resumo["acompanhadas"] == 0
    db.atualizar({"job_id": "c" * 32, "url": "https://example.com/3", "title": "Vaga 1",
                  "status": "Entrevista agendada", "favorite": False})
    resumo = db.resumo()
    assert resumo["registradas"] == 2
    assert resumo["acompanhadas"] == 1


def test_id_da_vaga_e_estavel_e_sem_url_usa_campos(tmp_path):
    a = id_da_vaga("", "Analista", "Empresa", "Niterói")
    b = id_da_vaga("", "Analista", "Empresa", "Niterói")
    assert a == b and len(a) == 32


def test_historico_de_pesquisas_persiste_e_nao_duplica_abertura(tmp_path):
    db = CareerStore(tmp_path / "carreira.sqlite3")
    payload = {
        "generated_at": "2026-11-28T08:30:00-03:00",
        "terms": ["CPD", "Informática"],
        "metadata": {"cidade": "Rio de Janeiro"},
        "jobs": [{"id": "a" * 32}, {"id": "b" * 32}],
    }
    db.registrar_pesquisa(payload)
    db.registrar_pesquisa(payload)
    items = db.pesquisas_recentes()
    assert len(items) == 1
    assert items[0]["terms"] == ["CPD", "Informática"]
    assert items[0]["city"] == "Rio de Janeiro"
    assert items[0]["job_count"] == 2


def test_pesquisas_no_mesmo_instante_com_resultados_diferentes_sao_distintas(tmp_path):
    db = CareerStore(tmp_path / "carreira.sqlite3")
    base = {"generated_at": "2026-11-28T08:30:00-03:00", "terms": ["Motorista"],
            "metadata": {"cidade": "Rio de Janeiro"}}
    db.registrar_pesquisa({**base, "jobs": [{"id": "1" * 32}]})
    db.registrar_pesquisa({**base, "jobs": [{"id": "2" * 32}]})
    assert len(db.pesquisas_recentes()) == 2
