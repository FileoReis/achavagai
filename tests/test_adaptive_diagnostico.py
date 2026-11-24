from pathlib import Path

from bs4 import BeautifulSoup

from scrapers.base import Vaga
from scrapers.adaptive import extrair_microdata, extrair_vagas_adaptativo, mesclar_vagas
from scrapers import diagnostico


def test_extrai_schema_jobposting_microdata():
    html = '''
    <html><body>
      <article itemscope itemtype="https://schema.org/JobPosting">
        <h2 itemprop="title">Analista de Suporte</h2>
        <div itemprop="hiringOrganization" itemscope itemtype="https://schema.org/Organization">
          <span itemprop="name">Empresa Exemplo</span>
        </div>
        <div itemprop="jobLocation" itemscope itemtype="https://schema.org/Place">
          <div itemprop="address" itemscope itemtype="https://schema.org/PostalAddress">
            <span itemprop="addressLocality">Nova Iguaçu</span>
            <span itemprop="addressRegion">RJ</span>
          </div>
        </div>
        <meta itemprop="datePosted" content="2026-11-23" />
        <div itemprop="description">Suporte técnico, redes e atendimento de chamados.</div>
        <a itemprop="url" href="/vaga/123">Ver vaga</a>
      </article>
    </body></html>
    '''
    vagas = extrair_microdata(html, "Portal Teste", "https://portal.example/busca")
    assert len(vagas) == 1
    assert vagas[0].titulo == "Analista de Suporte"
    assert vagas[0].empresa == "Empresa Exemplo"
    assert "Nova Iguaçu" in vagas[0].cidade and "RJ" in vagas[0].cidade
    assert vagas[0].data_publicacao == "2026-11-23"
    assert vagas[0].link == "https://portal.example/vaga/123"


def test_parser_adaptativo_tenta_mais_de_uma_estrategia():
    html = '''<article itemscope itemtype="https://schema.org/JobPosting">
    <h2 itemprop="title">Auxiliar de CPD</h2><a itemprop="url" href="/vaga/1">Detalhes</a>
    </article>'''
    vagas, estrategia = extrair_vagas_adaptativo(html, "Teste", "https://example.com")
    assert len(vagas) == 1
    assert "microdata" in estrategia.lower()


def test_mesclar_vagas_remove_variacoes_de_rastreamento_e_preserva_indeed_id():
    a = Vaga("Motorista B", "Empresa", "RJ", "", "https://site.test/vaga/1?utm_source=x", "", "A")
    b = Vaga("Motorista B", "Empresa", "RJ", "", "https://site.test/vaga/1?utm_source=y", "", "B")
    c = Vaga("Motorista B", "Empresa", "RJ", "", "https://br.indeed.com/viewjob?jk=abc&from=serp", "", "Indeed")
    d = Vaga("Motorista B", "Empresa", "RJ", "", "https://br.indeed.com/viewjob?jk=def&from=serp", "", "Indeed")
    assert len(mesclar_vagas([a, c], [b, d])) == 3


def test_diagnostico_detecta_mudanca_e_salva_snapshot_sem_conteudo_pessoal(tmp_path, monkeypatch):
    monkeypatch.setattr(diagnostico, "_PASTA_DIAGNOSTICOS", tmp_path)
    diagnostico.limpar_todos()
    html = '''<html><body><main class="nova-listagem"><section class="job-card">
    <h2>Conteúdo particular</h2><p>email: teste.pessoal@example.com telefone 21999999999</p>
    <p>Esta página contém uma nova estrutura de listagem, cartões de oportunidade, metadados e vários campos adicionais para que o parser antigo já não identifique a organização anterior.</p>
    <a href="https://example.com/vaga/1?token=segredo">link</a>
    </section></main></body></html>'''
    diagnostico.registrar_http("https://example.com/jobs", 200, html, fonte="Portal Teste", content_type="text/html")
    diagnostico.registrar_parser("https://example.com/jobs", 0, "nenhuma estrutura reconhecida", html, "Portal Teste")
    estado = diagnostico.obter("Portal Teste")
    assert estado["status"] == "estrutura_alterada"
    snapshot = Path(estado["snapshot"]).read_text(encoding="utf-8")
    assert "nova-listagem" in snapshot and "job-card" in snapshot
    assert "teste.pessoal@example.com" not in snapshot
    assert "21999999999" not in snapshot
    assert "Conteúdo particular" not in snapshot
    assert "token=segredo" not in snapshot


def test_fonte_api_sem_resultado_e_diferenciada_de_html_quebrado():
    diagnostico.limpar_todos()
    diagnostico.registrar_parser("https://api.example/jobs", 0, "API REST", "", "API Teste")
    assert diagnostico.obter("API Teste")["status"] == "sem_resultados"


def test_diagnostico_remove_query_string_de_urls_persistidas():
    diagnostico.limpar_todos()
    diagnostico.registrar_http(
        "https://example.com/jobs?token=nao-persistir&email=pessoa@example.com",
        200, "", fonte="Portal URL",
    )
    estado = diagnostico.obter("Portal URL")
    assert estado["url"] == "https://example.com/jobs"
    assert "token=" not in estado["url"] and "email=" not in estado["url"]
