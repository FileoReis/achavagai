import http.client
import json
import threading
import urllib.request

import ia
import painel_local


def _job():
    return {"id": "e" * 32, "url": "https://example.com/motorista", "title": "Motorista B",
            "company": "Transportadora", "city": "Rio de Janeiro", "source": "Portal",
            "score": 82, "description": "A vaga requer CNH B e experiência em entregas."}


def test_servidor_local_health_tracker_and_persistence(tmp_path):
    html = tmp_path / "painel.html"
    html.write_text("<!doctype html><title>AchaVagAI</title>", encoding="utf-8")
    data = tmp_path / "painel.json"
    data.write_text(json.dumps({"jobs": [_job()], "profile": {"habilidades": ["Logística"],
                         "experiencias_relevantes": [], "cnh": ["A", "B"]}}), encoding="utf-8")
    server = painel_local.criar_servidor(html, tmp_path / "carreira.sqlite3", data, port=0, ai_available=False)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        with urllib.request.urlopen(base + "/api/health") as response:
            health = json.loads(response.read())
        assert health["ok"] is True
        with urllib.request.urlopen(base + "/api/tracker") as response:
            tracker = json.loads(response.read())
        assert "e" * 32 in tracker["items"]

        payload = {"job_id": "e" * 32, "url": "https://example.com/motorista", "title": "Motorista B",
                   "company": "Transportadora", "city": "Rio de Janeiro", "source": "Portal", "score": 82,
                   "favorite": True, "status": "Quero me candidatar", "notes": "Ligar amanhã"}
        request = urllib.request.Request(base + "/api/tracker", data=json.dumps(payload).encode(),
                                         headers={"Content-Type": "application/json", "Origin": base}, method="POST")
        with urllib.request.urlopen(request) as response:
            saved = json.loads(response.read())
        assert saved["ok"] is True
        with urllib.request.urlopen(base + "/api/events?job_id=" + "e" * 32) as response:
            events = json.loads(response.read())["events"]
        assert events
        assert {event["detail"] for event in events} >= {"Etapa da candidatura atualizada", "Adicionada aos favoritos", "Notas de acompanhamento atualizadas"}
        with urllib.request.urlopen(base + "/api/summary") as response:
            summary = json.loads(response.read())
        assert summary["registradas"] == 1
        assert summary["acompanhadas"] == 1
        with urllib.request.urlopen(base + "/") as response:
            assert b"AchaVagAI" in response.read()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_servidor_rejeita_host_e_origem_externos(tmp_path):
    html = tmp_path / "painel.html"
    html.write_text("<title>Teste</title>", encoding="utf-8")
    data = tmp_path / "painel.json"
    data.write_text(json.dumps({"jobs": [], "profile": {}}), encoding="utf-8")
    server = painel_local.criar_servidor(html, tmp_path / "db.sqlite3", data, port=0, ai_available=False)
    try:
        assert server.server_address[0] == "127.0.0.1"
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
        conn.request("GET", "/api/health", headers={"Host": "evil.example"})
        response = conn.getresponse()
        assert response.status == 403
        conn.close()
        server.shutdown()
        thread.join(timeout=2)
    finally:
        server.server_close()


def test_consultor_local_nao_inventa_experiencia_de_motorista(monkeypatch):
    profile = {
        "habilidades": ["Logística", "Controle de estoque"],
        "experiencias_relevantes": [{"cargo": "Auxiliar de Logística", "periodo": "2020-2023",
                                      "atividades": ["Controle de estoque e distribuição de mercadorias"],
                                      "evidencias": ["Responsável pelo controle de estoque e distribuição"]}],
        "formacao": ["Ensino médio"], "cnh": ["A", "B"],
        "experiencia_conducao_comprovada": False, "experiencia_cpd_comprovada": False,
    }
    monkeypatch.setattr(ia, "provedor_disponivel", lambda: True)
    monkeypatch.setattr(ia, "nome_provedor", lambda: "Gemini de teste")
    monkeypatch.setattr(ia, "chamar_ia_json", lambda *a, **k: {
        "resumo": "Possui experiência comprovada como motorista profissional.",
        "evidencias": [{"cargo": "Motorista", "trecho": "Experiência prévia como motorista profissional"}],
        "requisitos_nao_comprovados": [], "riscos": [],
        "recomendacao": "Candidatar-se, pois trabalhou como motorista.", "aderencia": 99,
    })
    advice = painel_local._analisar_com_ia({"title": "Motorista B", "description": "CNH B e entregas."}, profile)
    assert "experiência comprovada como motorista" not in advice["resumo"].casefold()
    assert not any("Motorista" == item.get("cargo") for item in advice["evidencias"])
    assert any("dirigindo" in item.casefold() for item in advice["requisitos_nao_comprovados"])


def test_chave_cache_do_consultor_muda_quando_descricao_muda():
    job_a = {"title": "Motorista B", "company": "Empresa", "description": "Entregas urbanas.",
             "city": "Rio de Janeiro", "url": "https://example.com/vaga"}
    job_b = {**job_a, "description": "Entregas urbanas e conferência de mercadorias."}
    assert painel_local._advice_cache_key("perfil-fixo", job_a) != painel_local._advice_cache_key("perfil-fixo", job_b)
    assert painel_local._advice_cache_key("perfil-fixo", job_a) == painel_local._advice_cache_key("perfil-fixo", job_a)


def test_consultor_local_identifica_multiplas_categorias_cnh():
    profile = {"habilidades": [], "experiencias_relevantes": [], "formacao": [], "cnh": ["A", "B"],
               "experiencia_conducao_comprovada": False, "experiencia_cpd_comprovada": False}
    advice = painel_local._analisar_localmente(
        {"title": "Motorista", "description": "Requisito obrigatório: CNH categorias C e D."}, profile
    )
    gaps = " ".join(advice["requisitos_nao_comprovados"])
    assert "CNH C" in gaps
    assert "CNH D" in gaps
    assert "CNH A" not in gaps


def test_api_expoe_historico_de_pesquisas(tmp_path):
    html = tmp_path / "painel.html"
    html.write_text("<title>AchaVagAI</title>", encoding="utf-8")
    data = tmp_path / "painel.json"
    data.write_text(json.dumps({
        "generated_at": "2026-11-28T08:30:00-03:00", "terms": ["CPD"],
        "metadata": {"cidade": "Rio de Janeiro"}, "jobs": [_job()], "profile": {},
    }), encoding="utf-8")
    server = painel_local.criar_servidor(html, tmp_path / "db.sqlite3", data, port=0, ai_available=False)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{server.server_port}/api/research-history") as response:
            payload = json.loads(response.read())
        assert len(payload["items"]) == 1
        assert payload["items"][0]["terms"] == ["CPD"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
