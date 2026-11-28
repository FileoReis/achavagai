"""Geração de painel HTML premium, local e autocontido para o AchaVagAI."""
from __future__ import annotations

import html
import hashlib
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from classificacao import classificar_vaga
from exportar import selecionar_vagas_aba_principal
from filtros import idade_em_dias
from matcher import MOTIVO_SEM_IA
from geografia import coordenada, distancia_km, faixa_distancia

ROTULOS_CATEGORIA = {
    "Pesquisa direta": "Cargo pesquisado",
    "Compatível com currículo": "Compatível com o perfil",
    "Alternativa": "Oportunidade alternativa",
}


def _esc(valor) -> str:
    return html.escape("" if valor is None else str(valor), quote=True)


def _url_segura(valor: str) -> str:
    texto = str(valor or "").strip()
    if not texto or len(texto) > 4000 or any(ord(c) < 32 for c in texto):
        return ""
    try:
        partes = urlsplit(texto)
    except ValueError:
        return ""
    if partes.scheme.lower() not in {"http", "https"} or not partes.netloc:
        return ""
    if partes.username or partes.password:
        return ""
    return texto


def _texto_nota(motivo: str) -> tuple[str, str]:
    if motivo == MOTIVO_SEM_IA:
        return (
            "Pontuação por similaridade textual local. Esta oportunidade não foi avaliada individualmente pelo Gemini.",
            "local",
        )
    if motivo:
        return (str(motivo), "ia")
    return ("Não foi registrada uma justificativa para esta pontuação.", "indefinida")


def _data_label(data: str, idade: int | None) -> str:
    if idade is None:
        return "Data não confirmada"
    if idade <= 0:
        return "Publicada hoje"
    if idade == 1:
        return "Publicada ontem"
    return f"Publicada há {idade} dias"


def _inicial(empresa: str) -> str:
    palavras = [p for p in empresa.split() if p and p.casefold() not in {"ltda", "me", "eireli", "s/a"}]
    return ("".join(p[0] for p in palavras[:2]) or "V").upper()


def _inferir_modalidade(vaga) -> str:
    """Classifica modalidade apenas quando o anúncio contém indicação explícita."""
    explicit = str(getattr(vaga, "modalidade", "") or "").strip()
    if explicit:
        normal = explicit.casefold()
        if "remot" in normal or "home office" in normal or "teletrabalho" in normal:
            return "Remoto"
        if "hibr" in normal:
            return "Híbrido"
        if "presencial" in normal:
            return "Presencial"
        return explicit[:80]
    texto = " ".join((str(getattr(vaga, "titulo", "") or ""),
                       str(getattr(vaga, "descricao", "") or ""))).casefold()
    if re.search(r"\b(?:100\s*%\s*remot[oa]|totalmente remot[oa]|trabalho remot[oa]|vaga remot[oa]|regime remot[oa]|home\s*office|teletrabalho)\b", texto):
        return "Remoto"
    if re.search(r"\b(?:modelo|regime|trabalho)\s+h[ií]brid[oa]\b|\bh[ií]brid[oa]\b", texto):
        return "Híbrido"
    if re.search(r"\b(?:100\s*%\s*presencial|regime presencial|trabalho presencial|vaga presencial)\b", texto):
        return "Presencial"
    return "Não informada"


def _card(item: tuple, termos_busca, perfil, novas: set[int], job_id: str, cidade_base: str = "") -> tuple[str, str, str]:
    vaga, pontuacao, motivo = item
    titulo = str(getattr(vaga, "titulo", "") or "Vaga sem título")
    empresa = str(getattr(vaga, "empresa", "") or "Empresa não informada")
    cidade = str(getattr(vaga, "cidade", "") or "Local não informado")
    fonte = str(getattr(vaga, "fonte", "") or "Fonte não informada")
    data = str(getattr(vaga, "data_publicacao", "") or "")
    descricao = str(getattr(vaga, "descricao", "") or "").strip()
    link = _url_segura(getattr(vaga, "link", ""))
    termo = str(getattr(vaga, "termo_busca", "") or "")
    categoria = classificar_vaga(vaga, termos_busca, perfil)
    modalidade = _inferir_modalidade(vaga)
    salario = str(getattr(vaga, "salario", "") or getattr(vaga, "faixa_salarial", "") or "").strip()
    idade = idade_em_dias(data)
    # O painel recebe a mesma população da aba principal do XLSX; por segurança,
    # não deveria haver data desconhecida neste ponto.
    data_tipo = "confirmada"
    data_label = _data_label(data, idade)
    motivo_texto, base = _texto_nota(str(motivo or ""))
    try:
        nota = max(0, min(100, float(pontuacao)))
    except (TypeError, ValueError):
        nota = 0.0
    is_nova = id(vaga) in novas
    distancia = distancia_km(cidade_base, cidade) if cidade_base else None
    distancia_html = f'<span class="distance-chip">≈ {distancia:.0f} km do município-base</span>' if distancia is not None else ""
    distancia_attr = f"{distancia:.1f}" if distancia is not None else ""

    busca = " ".join((titulo, empresa, cidade, fonte, descricao, termo, data, categoria))
    descricao_curta = descricao[:9000]
    aviso_corte = '<p class="description-cut">Descrição longa: exibida parcialmente.</p>' if len(descricao) > 9000 else ""
    if descricao_curta:
        detalhe = (
            '<details class="job-details"><summary>Ver descrição e análise</summary>'
            f'<div class="description-text">{_esc(descricao_curta)}</div>{aviso_corte}'
            f'<div class="analysis-note"><span class="note-label">ANÁLISE DE COMPATIBILIDADE</span><p>{_esc(motivo_texto)}</p></div>'
            '</details>'
        )
    else:
        detalhe = (
            '<details class="job-details"><summary>Ver análise de compatibilidade</summary>'
            f'<div class="analysis-note"><span class="note-label">ANÁLISE DE COMPATIBILIDADE</span><p>{_esc(motivo_texto)}</p></div>'
            '</details>'
        )

    if base == "local":
        base_badge = '<span class="score-origin origin-local"><span class="origin-dot"></span> Similaridade local · sem IA</span>'
    elif base == "ia":
        base_badge = '<span class="score-origin origin-ai"><span class="origin-dot"></span> Avaliação IA / cache</span>'
    else:
        base_badge = '<span class="score-origin"><span class="origin-dot"></span> Origem da nota não identificada</span>'

    categoria_label = ROTULOS_CATEGORIA.get(categoria, categoria)
    cat_class = {
        "Pesquisa direta": "direct",
        "Compatível com currículo": "compatible",
        "Alternativa": "alternative",
    }.get(categoria, "alternative")
    url_attr = _esc(link)
    if link:
        actions = (
            f'<a class="action-primary" href="{url_attr}" target="_blank" rel="noopener noreferrer">'
            'Ver oportunidade <span aria-hidden="true">↗</span></a>'
            f'<button class="action-secondary copy-link" type="button" data-link="{url_attr}">Copiar link</button>'
        )
    else:
        actions = '<span class="no-link">Link não disponível</span>'

    card = f'''<article class="opportunity-card" data-job-id="{_esc(job_id)}" data-url="{url_attr}" data-company="{_esc(empresa)}" data-city="{_esc(cidade)}" data-source="{_esc(fonte)}" data-category="{_esc(categoria)}" data-date="{data_tipo}"
      data-age="{idade if idade is not None else 999999}" data-distance="{distancia_attr}" data-distance-band="{_esc(faixa_distancia(distancia))}" data-score="{nota:.2f}" data-title="{_esc(titulo)}" data-salary="{_esc(salario)}" data-has-salary="{'1' if salario else '0'}" data-modality="{_esc(modalidade)}" data-search="{_esc(busca)}">
      <div class="card-accent"></div>
      <div class="opportunity-inner">
        <div class="opportunity-top">
          <span class="category-tag tag-{cat_class}"><span class="tag-indicator"></span>{_esc(categoria_label)}</span>
          <span class="date-label">{_esc(data_label)}</span>
        </div>
        <div class="opportunity-main">
          <div class="company-mark" aria-hidden="true">{_esc(_inicial(empresa))}</div>
          <div class="role-copy">
            <h3>{_esc(titulo)}</h3>
            <p class="company-name">{_esc(empresa)}</p>
          </div>
          <div class="score-orb" style="--score-angle:{nota * 3.6:.1f}deg" aria-label="Nota {nota:.0f} de 100">
            <div class="score-orb-inner"><strong>{nota:.0f}</strong><span>de 100</span></div>
          </div>
        </div>
        <div class="opportunity-meta">
          <span><i class="meta-symbol">⌖</i>{_esc(cidade)}</span>
          {distancia_html}
          <span><i class="meta-symbol">▦</i>{_esc(fonte)}</span>
          {('<span><i class="meta-symbol">⌕</i>' + _esc(termo) + '</span>') if termo else ''}
          {('<span><i class="meta-symbol">＄</i>' + _esc(salario) + '</span>') if salario else ''}
          {('<span><i class="meta-symbol">◈</i>' + _esc(modalidade) + '</span>') if modalidade != 'Não informada' else ''}
        </div>
        <div class="card-footer">
          <div class="card-indicators">{base_badge}{'<span class="new-label">NOVA</span>' if is_nova else ''}</div>
          <div class="card-actions">{actions}</div>
        </div>
        <div class="career-actions" data-job-actions="{_esc(job_id)}">
          <button class="mini-action favorite-action" type="button" data-role="favorite" aria-pressed="false">☆ Favoritar</button>
          <label class="status-control">Etapa <select class="status-select" data-role="status" aria-label="Etapa da candidatura">
            <option>Encontrada</option><option>Quero me candidatar</option><option>Candidatura enviada</option><option>Aguardando resposta</option><option>Entrevista agendada</option><option>Aprovado</option><option>Recusado</option><option>Arquivada</option>
          </select></label>
          <label class="compare-control"><input type="checkbox" data-role="compare"> Comparar</label>
          <button class="mini-action history-action" type="button" data-role="history">Histórico</button>
        </div>
        <div class="event-history" data-role="event-history" hidden></div>
        <details class="notes-details"><summary>Minhas notas e acompanhamento</summary><div class="notes-editor"><textarea data-role="notes" maxlength="4000" placeholder="Anote contato, data da candidatura, salário conversado ou próximos passos..."></textarea><button class="mini-action save-notes" type="button" data-role="save-notes">Salvar nota</button><span class="save-feedback" aria-live="polite"></span></div></details>
        <div class="advisor-block"><button class="advisor-button" type="button" data-role="advisor">✦ Analisar requisitos com o consultor</button><div class="advisor-result" data-role="advisor-result" hidden></div></div>
        {detalhe}
      </div>
    </article>'''
    return card, categoria, base



def _perfil_publico(perfil) -> dict:
    """Campos mínimos para aconselhamento local; nunca inclui nome, contato ou PDF bruto."""
    if perfil is None:
        return {}
    experiencias = []
    for exp in getattr(perfil, "experiencias_relevantes", []) or []:
        if not isinstance(exp, dict):
            continue
        experiencias.append({
            "cargo": str(exp.get("cargo") or "")[:120],
            "periodo": str(exp.get("periodo") or "")[:80],
            "atividades": [str(x)[:180] for x in (exp.get("atividades") or [])[:5] if isinstance(x, str)],
            "evidencias": [str(x)[:220] for x in (exp.get("evidencias") or [])[:4] if isinstance(x, str)],
        })
    return {
        "habilidades": [str(x)[:100] for x in (getattr(perfil, "habilidades", []) or [])[:30]],
        "areas_atuacao": [str(x)[:120] for x in (getattr(perfil, "areas_atuacao", []) or [])[:15]],
        "formacao": [str(x)[:180] for x in (getattr(perfil, "formacao", []) or [])[:12]],
        "experiencias_relevantes": experiencias[:8],
        "cargo_sugerido": str(getattr(perfil, "cargo_sugerido", "") or "")[:120],
        "senioridade": str(getattr(perfil, "senioridade", "") or "")[:60],
        "cnh": [str(x)[:4] for x in (getattr(perfil, "cnh", []) or [])[:6]],
        "experiencia_conducao_comprovada": bool(getattr(perfil, "experiencia_conducao_comprovada", False)),
        "objetivo_conducao_declarado": bool(getattr(perfil, "objetivo_conducao_declarado", False)),
        "experiencia_cpd_comprovada": bool(getattr(perfil, "experiencia_cpd_comprovada", False)),
    }


def _id_job(vaga) -> str:
    base = str(getattr(vaga, "link", "") or "").strip()
    if not base:
        base = "|".join(str(getattr(vaga, campo, "") or "") for campo in ("titulo", "empresa", "cidade", "fonte"))
    return hashlib.sha256(base.casefold().encode("utf-8")).hexdigest()[:32]


def _dados_painel(ranking_painel, termos, perfil_publico, metadata, perfil_obj=None) -> dict:
    jobs = []
    for vaga, nota, motivo in ranking_painel:
        link = _url_segura(getattr(vaga, "link", ""))
        job_id = _id_job(vaga)
        cidade = str(getattr(vaga, "cidade", "") or "")
        coord = coordenada(cidade)
        base = "similaridade_local" if motivo == MOTIVO_SEM_IA else "ia_ou_cache"
        salario = str(getattr(vaga, "salario", "") or getattr(vaga, "faixa_salarial", "") or "")
        modalidade = _inferir_modalidade(vaga)
        jobs.append({
            "id": job_id, "url": link, "title": str(getattr(vaga, "titulo", "") or "Vaga sem título")[:240],
            "company": str(getattr(vaga, "empresa", "") or "Empresa não informada")[:180],
            "city": cidade[:160], "source": str(getattr(vaga, "fonte", "") or "")[:100],
            "date": str(getattr(vaga, "data_publicacao", "") or "")[:100], "score": round(float(nota), 1),
            "score_origin": base, "reason": str(motivo or "")[:1200],
            "description": str(getattr(vaga, "descricao", "") or "")[:12000],
            "category": classificar_vaga(vaga, termos, perfil_obj), "salary": salario[:160], "modality": modalidade[:100],
            "coordinates": {"lat": coord[0], "lon": coord[1]} if coord else None,
            "distance_km": distancia_km(str((metadata or {}).get("cidade_candidato") or ""), cidade),
        })
    return {"generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "terms": list(termos), "metadata": metadata or {}, "profile": perfil_publico, "jobs": jobs}


def _graficos_barras(contagem: Counter, max_itens: int = 7) -> str:
    if not contagem:
        return '<p class="chart-empty">Ainda não há dados suficientes.</p>'
    maximo = max(contagem.values()) or 1
    partes = []
    for label, qtd in contagem.most_common(max_itens):
        largura = max(3, qtd / maximo * 100)
        partes.append(f'<div class="bar-row"><div class="bar-label"><span>{_esc(label)}</span><b>{qtd}</b></div><div class="bar-track"><span style="width:{largura:.1f}%"></span></div></div>')
    return "".join(partes)


def _mapa_esquematico(contagem: Counter, cidade_base: str) -> str:
    pontos = []
    coords = []
    for cidade, qtd in contagem.items():
        c = coordenada(cidade)
        if c:
            coords.append((cidade, qtd, c[0], c[1], distancia_km(cidade_base, cidade) if cidade_base else None))
    if not coords:
        return '<div class="chart-empty">Não há cidades reconhecidas para posicionar no mapa esquemático.</div>'
    latitudes = [p[2] for p in coords]; longitudes = [p[3] for p in coords]
    min_lat, max_lat = min(latitudes)-.12, max(latitudes)+.12
    min_lon, max_lon = min(longitudes)-.12, max(longitudes)+.12
    if max_lat == min_lat: max_lat += .1
    if max_lon == min_lon: max_lon += .1
    for cidade, qtd, lat, lon, km in coords:
        x = 28 + (lon-min_lon)/(max_lon-min_lon)*544
        y = 25 + (max_lat-lat)/(max_lat-min_lat)*270
        r = 5 + min(9, qtd ** .5)
        label = f"{cidade} · {qtd} vagas" + (f" · aprox. {km:.0f} km" if km is not None else "")
        pontos.append(f'<g class="map-point" data-city="{_esc(cidade)}" tabindex="0" role="button" aria-label="Filtrar vagas em {_esc(cidade)}"><title>{_esc(label)} · Clique para filtrar</title><circle cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}" fill="#197c75" fill-opacity=".84" stroke="#fff" stroke-width="2"/><text x="{x+9:.1f}" y="{y-8:.1f}" font-size="10" fill="#52676a">{_esc(cidade[:20])}</text></g>')
    origem = coordenada(cidade_base) if cidade_base else None
    if origem:
        lat, lon = origem
        x = 28 + (lon-min_lon)/(max_lon-min_lon)*544
        y = 25 + (max_lat-lat)/(max_lat-min_lat)*270
        pontos.append(f'<g><title>Município-base aproximado: {_esc(cidade_base)}</title><circle cx="{x:.1f}" cy="{y:.1f}" r="9" fill="#c28b3e" stroke="#fff" stroke-width="3"/><text x="{x+12:.1f}" y="{y+16:.1f}" font-size="10" font-weight="700" fill="#9b6c2c">Base</text></g>')
    grid = ''.join(f'<line x1="0" y1="{y}" x2="600" y2="{y}" stroke="#e8e7df" stroke-dasharray="3 6"/>' for y in (65,130,195,260))
    return f'<svg viewBox="0 0 600 320" role="img" aria-label="Mapa esquemático das cidades das vagas"><rect x="0" y="0" width="600" height="320" rx="14" fill="#f8f7f2"/>{grid}{"".join(pontos)}</svg>'

def gerar_html(
    ranking: list[tuple],
    caminho: str | Path,
    novas: set[int] | None = None,
    termos_busca: list[str] | tuple[str, ...] | None = None,
    perfil=None,
    metadata: dict | None = None,
) -> Path:
    """Gera HTML local com exatamente as linhas da aba principal ``Vagas`` do XLSX.

    Anúncios sem data interpretável são intencionalmente excluídos deste painel,
    assim como da primeira aba do Excel; continuam na aba ``Data não confirmada``.
    """
    destino = Path(caminho)
    destino.parent.mkdir(parents=True, exist_ok=True)
    novas = novas or set()
    termos = list(termos_busca or [])
    metadata = metadata or {}

    # Fonte única da verdade: usa o mesmo seletor da aba principal do Excel.
    ranking_painel = selecionar_vagas_aba_principal(ranking)
    cards: list[str] = []
    categorias = Counter()
    fontes = Counter()
    cidades = Counter()
    notas_ia = 0
    notas_locais = 0
    cidade_base = str(metadata.get("cidade_candidato") or getattr(perfil, "cidade", "") or metadata.get("cidade") or "")
    perfil_publico = _perfil_publico(perfil)
    dados_painel = _dados_painel(ranking_painel, termos, perfil_publico, metadata, perfil)
    for item in ranking_painel:
        job_id = _id_job(item[0])
        card, categoria, base = _card(item, termos, perfil, novas, job_id, cidade_base)
        cards.append(card)
        categorias[categoria] += 1
        fontes[str(getattr(item[0], "fonte", "") or "Fonte não informada")] += 1
        cidade = str(getattr(item[0], "cidade", "") or "Local não informado")
        cidades[cidade] += 1
        if base == "local":
            notas_locais += 1
        elif base == "ia":
            notas_ia += 1

    total = len(ranking_painel)
    cidade = str(metadata.get("cidade") or "Local não informado")
    bairro = str(metadata.get("bairro") or "")
    uf = str(metadata.get("uf") or "")
    dias = metadata.get("dias_maximo")
    termos_label = ", ".join(termos) if termos else "Não informado"
    gerado = datetime.now().astimezone().strftime("%d/%m/%Y · %H:%M")
    local_label = " · ".join(x for x in (cidade, bairro, uf) if x)
    fontes_total = len(fontes)
    dados_path = destino.with_suffix(".json")
    dados_path.write_text(json.dumps(dados_painel, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    source_options = "".join(
        f'<option value="{_esc(fonte)}">{_esc(fonte)}</option>' for fonte in sorted(fontes)
    )
    source_chips = "".join(
        f'<span class="source-chip"><span class="source-dot"></span>{_esc(nome)}<b>{qtd:02d}</b></span>'
        for nome, qtd in fontes.most_common()
    )
    profile_tags = []
    for tag in (perfil_publico.get("areas_atuacao", []) + perfil_publico.get("habilidades", []))[:10]:
        if tag and tag not in profile_tags:
            profile_tags.append(tag)
    profile_chips = "".join(f'<span class="profile-chip">{_esc(tag)}</span>' for tag in profile_tags)
    cards_html = "\n".join(cards) if cards else '''
      <div class="empty-state">
        <div class="empty-icon">⌕</div><h3>Nenhuma oportunidade nesta lista</h3>
        <p>Não há vagas com data de publicação interpretável para a aba principal da planilha.</p>
      </div>'''

    html_doc = f'''<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light"><meta name="description" content="Painel local de oportunidades do AchaVagAI">
<title>AchaVagAI · Radar de oportunidades</title>
<style>
:root{{--ink:#142638;--ink-2:#1c3446;--paper:#f3f1ec;--surface:#fffefa;--surface-2:#f8f7f2;--line:#e4e2da;--muted:#77828a;--muted-2:#9aa1a2;--teal:#147d78;--teal-dark:#0e625e;--mint:#dcefe9;--gold:#d4a75c;--gold-soft:#f7efdf;--blue:#547b9a;--blue-soft:#e7eef3;--rose:#ac6d58;--rose-soft:#f5eae5;--shadow:0 18px 48px rgba(21,37,49,.07);--shadow-card:0 10px 28px rgba(21,37,49,.055)}}
*{{box-sizing:border-box}}html{{scroll-behavior:smooth}}body{{margin:0;background:var(--paper);color:var(--ink);font:14px/1.55 Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;-webkit-font-smoothing:antialiased}}a{{color:inherit}}button,input,select{{font:inherit}}button{{cursor:pointer}}.shell{{width:min(1320px,calc(100% - 56px));margin:0 auto}}
.hero{{position:relative;overflow:hidden;background:radial-gradient(ellipse at 82% 10%,rgba(37,132,125,.27),transparent 33%),linear-gradient(118deg,#102333 0%,#18374a 62%,#174b4a 100%);color:#f6f7f2;padding:28px 0 78px}}
.hero:before{{content:"";position:absolute;inset:0;opacity:.13;background-image:linear-gradient(rgba(255,255,255,.12) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.12) 1px,transparent 1px);background-size:54px 54px;mask-image:linear-gradient(110deg,black,transparent 76%)}}
.hero:after{{content:"";position:absolute;width:540px;height:540px;border:1px solid rgba(220,239,233,.12);border-radius:50%;right:-170px;top:-320px;box-shadow:0 0 0 48px rgba(220,239,233,.025),0 0 0 98px rgba(220,239,233,.02)}}
.hero-content{{position:relative;z-index:1}}.topbar{{display:flex;align-items:center;justify-content:space-between;gap:20px;padding-bottom:44px;border-bottom:1px solid rgba(226,239,235,.14)}}.brand{{display:flex;align-items:center;gap:12px;font-size:12px;font-weight:750;letter-spacing:.16em;text-transform:uppercase}}.brand-icon{{width:39px;height:39px;display:grid;place-items:center;border:1px solid rgba(255,255,255,.24);border-radius:13px;background:linear-gradient(145deg,#d6b16e,#a77c43);color:#122b39;font-family:Georgia,serif;font-size:22px;font-weight:700;box-shadow:0 7px 18px rgba(0,0,0,.16)}}.brand-sub{{color:rgba(238,245,240,.58);font-weight:550;letter-spacing:.12em}}.private-pill{{display:inline-flex;align-items:center;gap:8px;padding:8px 12px;border:1px solid rgba(216,239,230,.2);border-radius:999px;background:rgba(255,255,255,.07);color:#dbeae4;font-size:11px;letter-spacing:.08em;text-transform:uppercase}}.private-pill:before{{content:"";width:7px;height:7px;border-radius:50%;background:#83d6ad;box-shadow:0 0 0 4px rgba(131,214,173,.12)}}
.hero-grid{{display:grid;grid-template-columns:minmax(0,1fr) 270px;gap:48px;align-items:end;padding:42px 0 8px}}.eyebrow{{display:flex;align-items:center;gap:10px;color:#c9b17f;font-size:10px;font-weight:750;letter-spacing:.19em;text-transform:uppercase}}.eyebrow:before{{content:"";width:25px;height:1px;background:#c9b17f}}h1{{margin:16px 0 12px;font:500 clamp(38px,5.2vw,66px)/.99 Georgia,"Times New Roman",serif;letter-spacing:-.045em}}.hero-copy p{{max-width:720px;margin:0;color:rgba(237,244,239,.73);font-size:15px}}.query-line{{display:flex;flex-wrap:wrap;gap:8px;margin-top:23px}}.query-chip{{padding:7px 11px;border:1px solid rgba(237,244,239,.16);border-radius:7px;background:rgba(255,255,255,.055);color:#edf4ef;font-size:11px}}.hero-side{{padding:19px 20px;border:1px solid rgba(236,246,241,.17);border-radius:15px;background:rgba(5,24,35,.2);backdrop-filter:blur(10px)}}.side-label{{color:rgba(235,243,237,.55);font-size:10px;font-weight:700;letter-spacing:.13em;text-transform:uppercase}}.side-value{{display:block;margin:8px 0 2px;color:#fff;font:500 25px/1.2 Georgia,serif}}.side-foot{{color:rgba(235,243,237,.63);font-size:11px}}
.metrics-wrap{{position:relative;z-index:2;margin-top:-42px}}.metrics{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}}.metric{{min-height:112px;padding:19px 20px;border:1px solid rgba(224,222,214,.92);border-radius:13px;background:var(--surface);box-shadow:var(--shadow)}}.metric-label{{display:flex;align-items:center;gap:8px;color:#7c8587;font-size:10px;font-weight:750;letter-spacing:.1em;text-transform:uppercase}}.metric-label:before{{content:"";width:7px;height:7px;border-radius:2px;background:var(--teal)}}.metric-number{{display:block;margin-top:10px;color:var(--ink);font:500 34px/1 Georgia,serif;letter-spacing:-.04em}}.metric-caption{{display:block;margin-top:7px;color:#929a99;font-size:10px}}
.main{{padding:32px 0 60px}}.toolbar{{display:grid;grid-template-columns:minmax(220px,1.5fr) repeat(4,minmax(125px,.8fr));gap:10px;padding:13px;border:1px solid var(--line);border-radius:14px;background:rgba(255,254,250,.9);box-shadow:0 8px 26px rgba(21,37,49,.035)}}.clear-filters{{background:#f4f2eb;color:#657570;border-color:#e4e2da;font-weight:700}}.clear-filters:hover{{background:#e9f1ec;border-color:#c9ddd3}}.field{{width:100%;min-width:0;padding:12px 14px;border:1px solid #e5e3dc;border-radius:9px;outline:none;background:#fbfaf6;color:var(--ink);font-size:12px;transition:border-color .18s,box-shadow .18s}}.field:focus{{border-color:#6aa9a1;box-shadow:0 0 0 3px rgba(20,125,120,.1)}}.search-wrap{{position:relative}}.search-wrap:before{{content:"⌕";position:absolute;left:14px;top:7px;color:#75878a;font-size:22px;pointer-events:none}}.search-field{{padding-left:43px}}.filter-foot{{display:flex;justify-content:space-between;align-items:center;gap:16px;margin:17px 2px 20px}}.tabs{{display:flex;align-items:center;gap:7px;overflow:auto;padding-bottom:2px;scrollbar-width:thin}}.tab{{display:inline-flex;align-items:center;gap:8px;padding:9px 12px;border:1px solid transparent;border-radius:8px;background:transparent;color:#737f83;white-space:nowrap;font-size:11px;font-weight:650;transition:all .16s}}.tab:hover{{background:#ebece6;color:var(--ink)}}.tab.active{{border-color:#cfe2dc;background:#e4f0ec;color:#176f69}}.tab-count{{display:inline-grid;min-width:20px;height:20px;place-items:center;padding:0 5px;border-radius:6px;background:rgba(20,125,120,.09);font-size:10px}}.visible-count{{color:#828d8d;font-size:11px;white-space:nowrap}}.section-heading{{display:flex;justify-content:space-between;align-items:end;gap:16px;margin:18px 0 15px}}.section-title{{margin:0;font:500 26px/1.1 Georgia,"Times New Roman",serif;letter-spacing:-.025em}}.section-subtitle{{margin:5px 0 0;color:#8a9392;font-size:11px}}.sort-wrap{{display:flex;align-items:center;gap:8px;color:#84908f;font-size:11px}}.sort-wrap select{{width:auto;min-width:175px;background:var(--surface)}}
.job-grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}}.opportunity-card{{position:relative;overflow:hidden;border:1px solid #e5e3dc;border-radius:14px;background:var(--surface);box-shadow:var(--shadow-card);transition:transform .2s,border-color .2s,box-shadow .2s}}.opportunity-card:hover{{transform:translateY(-2px);border-color:#c9d8d2;box-shadow:0 17px 34px rgba(21,37,49,.085)}}.card-accent{{height:3px;background:linear-gradient(90deg,#177c76,#8cb9a6 58%,#d9b77b)}}.opportunity-inner{{padding:17px 18px 15px}}.opportunity-top{{display:flex;justify-content:space-between;align-items:center;gap:10px}}.category-tag{{display:inline-flex;align-items:center;gap:7px;max-width:70%;padding:6px 9px;border-radius:6px;font-size:10px;font-weight:750;letter-spacing:.025em}}.tag-direct{{background:#e4f1ec;color:#1a746b}}.tag-compatible{{background:#e9eef5;color:#496d8a}}.tag-alternative{{background:#f5eee1;color:#946d37}}.tag-indicator{{width:6px;height:6px;border-radius:50%;background:currentColor}}.date-label{{color:#7f8d8b;font-size:10px;white-space:nowrap}}.opportunity-main{{display:grid;grid-template-columns:43px minmax(0,1fr) 68px;gap:12px;align-items:center;margin:16px 0 13px}}.company-mark{{width:43px;height:43px;display:grid;place-items:center;border:1px solid #e6e2d6;border-radius:12px;background:linear-gradient(145deg,#f7f5ee,#efeee6);color:#3d6967;font:600 14px Georgia,serif;letter-spacing:-.04em}}.role-copy{{min-width:0}}.role-copy h3{{margin:0;color:#1a2f3d;font-size:17px;line-height:1.25;font-weight:720;letter-spacing:-.025em;overflow-wrap:anywhere}}.company-name{{margin:5px 0 0;color:#87918f;font-size:12px}}.score-orb{{width:65px;height:65px;display:grid;place-items:center;border-radius:50%;background:conic-gradient(#177f77 var(--score-angle),#e9ece6 0);padding:4px}}.score-orb-inner{{width:100%;height:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;border:1px solid #e8e9e2;border-radius:50%;background:var(--surface)}}.score-orb strong{{color:#1e746e;font:600 20px/1 Georgia,serif}}.score-orb span{{margin-top:3px;color:#98a19e;font-size:8px}}.opportunity-meta{{display:flex;flex-wrap:wrap;gap:7px 15px;padding:11px 0;border-top:1px solid #eeede7;border-bottom:1px solid #eeede7;color:#7b8887;font-size:10px}}.opportunity-meta span{{display:inline-flex;align-items:center;gap:5px}}.meta-symbol{{color:#ae986e;font-size:13px;font-style:normal}}.card-footer{{display:flex;justify-content:space-between;align-items:center;gap:10px;padding-top:12px}}.card-indicators,.card-actions{{display:flex;align-items:center;flex-wrap:wrap;gap:7px}}.score-origin{{display:inline-flex;align-items:center;gap:6px;color:#87918f;font-size:9px}}.origin-dot{{width:6px;height:6px;border-radius:50%;background:#5d9b8e}}.origin-local .origin-dot{{background:#c49a51}}.new-label{{padding:4px 6px;border-radius:4px;background:#e6f3e9;color:#3e8551;font-size:8px;font-weight:800;letter-spacing:.1em}}.action-primary,.action-secondary{{display:inline-flex;align-items:center;justify-content:center;gap:7px;min-height:32px;padding:7px 10px;border-radius:7px;text-decoration:none;font-size:10px;font-weight:700;transition:all .16s}}.action-primary{{border:1px solid #176e69;background:#176e69;color:white}}.action-primary:hover{{border-color:#0f5d59;background:#0f5d59;box-shadow:0 5px 12px rgba(23,110,105,.18)}}.action-secondary{{border:1px solid #e1e2da;background:#fffefa;color:#62716e}}.action-secondary:hover{{border-color:#b8ccc4;background:#eef4ef;color:#1b625e}}.no-link{{color:#a2a6a0;font-size:10px}}.job-details{{margin-top:12px;border-top:1px solid #eeede7}}.job-details summary{{padding-top:10px;color:#647977;font-size:10px;font-weight:700;cursor:pointer;list-style:none}}.job-details summary::-webkit-details-marker{{display:none}}.job-details summary:after{{content:"＋";float:right;color:#5f9086;font-size:12px}}.job-details[open] summary:after{{content:"−"}}.description-text{{margin-top:10px;color:#586665;font-size:11px;line-height:1.65;white-space:pre-wrap;overflow-wrap:anywhere}}.description-cut{{color:#9a927e;font-size:10px}}.analysis-note{{margin-top:12px;padding:12px 13px;border-left:2px solid #c7a66d;border-radius:0 8px 8px 0;background:#f8f5ed}}.note-label{{color:#9c865d;font-size:8px;font-weight:800;letter-spacing:.14em}}.analysis-note p{{margin:5px 0 0;color:#5c6662;font-size:11px;line-height:1.55}}
.source-panel{{display:flex;flex-wrap:wrap;gap:8px;padding:16px;border:1px solid var(--line);border-radius:12px;background:var(--surface)}}.source-chip{{display:inline-flex;align-items:center;gap:8px;padding:8px 10px;border:1px solid #e9e7df;border-radius:7px;background:#fbfaf6;color:#6e7c7a;font-size:10px}}.source-chip b{{color:#304a55;font-size:10px}}.source-dot{{width:6px;height:6px;border-radius:50%;background:#4f9a89}}.source-heading{{display:flex;justify-content:space-between;align-items:end;gap:12px;margin:36px 0 12px}}.source-heading h2{{margin:0;font:500 22px Georgia,serif}}.source-heading p{{margin:0;color:#919a96;font-size:10px}}.empty-state{{grid-column:1/-1;padding:52px 20px;border:1px dashed #cdd4cd;border-radius:14px;background:rgba(255,254,250,.7);text-align:center}}.empty-icon{{width:52px;height:52px;display:grid;place-items:center;margin:0 auto 13px;border-radius:16px;background:#e8f1ed;color:#2b7770;font-size:27px}}.empty-state h3{{margin:0;font:500 23px Georgia,serif}}.empty-state p{{margin:8px auto 0;max-width:420px;color:#83908c;font-size:12px}}.notice{{display:flex;gap:10px;align-items:flex-start;margin:19px 0 0;padding:13px 15px;border:1px solid #e7dfcc;border-radius:10px;background:#faf6eb;color:#827354;font-size:10px;line-height:1.55}}.notice strong{{color:#6d5b36}}.notice-mark{{flex:0 0 19px;width:19px;height:19px;display:grid;place-items:center;border-radius:50%;background:#f0e4c9;color:#8b6b31;font-size:11px;font-weight:800}}.footer{{display:flex;justify-content:space-between;gap:18px;margin-top:40px;padding:20px 0 8px;border-top:1px solid #dfded7;color:#8a9490;font-size:10px}}.footer strong{{color:#455c5c}}.hidden{{display:none!important}}
@media(max-width:1000px){{.hero-grid{{grid-template-columns:minmax(0,1fr) 220px;gap:25px}}.metrics{{grid-template-columns:repeat(2,minmax(0,1fr))}}}}
@media(max-width:720px){{.shell{{width:min(100% - 28px,620px)}}.hero{{padding:19px 0 65px}}.topbar{{padding-bottom:24px}}.brand-sub{{display:none}}.private-pill{{font-size:9px;padding:7px 9px}}.hero-grid{{grid-template-columns:1fr;gap:18px;padding:30px 0 4px}}h1{{font-size:43px}}.hero-side{{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:13px 15px}}.side-value{{margin:0;font-size:19px}}.side-foot{{text-align:right}}.metrics-wrap{{margin-top:-35px}}.metric{{min-height:98px;padding:14px}}.metric-number{{font-size:29px}}.main{{padding-top:23px}}.toolbar{{grid-template-columns:1fr 1fr;padding:10px;gap:8px}}.search-wrap{{grid-column:1/-1}}.field{{font-size:11px;padding:11px}}.filter-foot{{display:block;margin-top:12px}}.tabs{{padding-bottom:8px}}.visible-count{{display:block;text-align:right;margin-top:3px}}.section-heading{{align-items:start;flex-direction:column;margin-top:17px}}.sort-wrap{{width:100%;justify-content:space-between}}.sort-wrap select{{flex:1}}.job-grid{{grid-template-columns:1fr;gap:11px}}.opportunity-inner{{padding:15px}}.role-copy h3{{font-size:16px}}.card-footer{{align-items:flex-start;flex-direction:column}}.card-actions{{width:100%}}.action-primary,.action-secondary{{flex:1}}.source-heading{{align-items:flex-start;flex-direction:column}}.footer{{flex-direction:column;gap:7px}}}}
@media(max-width:380px){{.shell{{width:calc(100% - 22px)}}.metrics{{gap:7px}}.metric{{padding:11px}}.metric-label{{font-size:8px}}.metric-number{{font-size:26px}}.opportunity-main{{grid-template-columns:36px minmax(0,1fr) 58px;gap:9px}}.company-mark{{width:36px;height:36px}}.score-orb{{width:57px;height:57px}}.score-orb strong{{font-size:18px}}}}

.intelligence-grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:13px;margin:0 0 24px}}.insight-panel{{min-width:0;padding:19px 20px;border:1px solid var(--line);border-radius:14px;background:var(--surface);box-shadow:var(--shadow-card)}}.panel-heading{{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:15px}}.panel-heading h2{{margin:3px 0 0;font:500 20px Georgia,serif;letter-spacing:-.02em}}.panel-kicker{{color:#a18a60;font-size:9px;font-weight:800;letter-spacing:.16em}}.panel-icon{{width:33px;height:33px;display:grid;place-items:center;border-radius:10px;background:#edf4ef;color:#28766e;font-size:17px}}.bar-row{{margin:11px 0}}.bar-label{{display:flex;justify-content:space-between;gap:10px;color:#6f7d7c;font-size:11px}}.bar-label b{{color:#314c53}}.bar-track{{height:6px;margin-top:5px;overflow:hidden;border-radius:99px;background:#eeeee8}}.bar-track span{{display:block;height:100%;border-radius:99px;background:linear-gradient(90deg,#176f69,#7aab95)}}.chart-empty{{color:#8b9692;font-size:12px}}.map-panel svg{{display:block;width:100%;height:auto;border-radius:12px}}.map-point{{cursor:pointer;outline:none}}.map-point circle{{transition:transform .16s,fill .16s;transform-box:fill-box;transform-origin:center}}.map-point:hover circle,.map-point:focus circle{{fill:#c28b3e;stroke:#173d48;stroke-width:3;transform:scale(1.18)}}.map-point:focus text{{font-weight:800;fill:#9b6c2c}}.map-disclaimer{{margin:8px 0 0;color:#9a9487;font-size:9px;line-height:1.45}}.tracker-summary{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:7px}}.tracker-summary>div{{padding:10px 8px;border-radius:9px;background:#f5f5ef}}.tracker-summary strong{{display:block;color:#1e665f;font:500 22px Georgia,serif}}.tracker-summary span{{display:block;color:#87918e;font-size:9px}}.tracker-caption{{margin:12px 0 0;color:#8c9692;font-size:10px}}.heading-actions{{display:flex;align-items:center;gap:14px}}.compare-open{{border:1px solid #cbded6;border-radius:8px;background:#e8f2ed;color:#236f65;padding:9px 12px;font-size:10px;font-weight:750}}.compare-open:disabled{{opacity:.45;cursor:not-allowed}}.compare-open span{{margin-left:7px;color:#80948e}}.career-actions{{display:flex;align-items:center;flex-wrap:wrap;gap:8px;margin-top:12px;padding:11px 0;border-top:1px solid #eeede7}}.mini-action{{border:1px solid #dfe5df;border-radius:7px;background:#fbfaf6;color:#526d68;padding:7px 9px;font-size:10px;font-weight:700}}.mini-action:hover{{border-color:#a9c9bc;background:#edf5ef}}.favorite-action.is-favorite{{border-color:#e8d5a5;background:#faf3df;color:#99722c}}.status-control{{display:inline-flex;align-items:center;gap:6px;color:#84908b;font-size:10px}}.status-select{{max-width:155px;padding:7px;border:1px solid #e4e6df;border-radius:7px;background:#fbfaf6;color:#415d59;font-size:10px}}.compare-control{{display:inline-flex;align-items:center;gap:5px;color:#788681;font-size:10px}}.compare-control input{{accent-color:#20776e}}.notes-details,.advisor-block{{margin-top:7px;border-top:1px solid #eeede7}}.notes-details summary{{padding:9px 0 2px;color:#607b74;font-size:10px;font-weight:700;cursor:pointer}}.notes-editor{{display:grid;grid-template-columns:1fr auto;gap:8px;padding:8px 0}}.notes-editor textarea{{min-height:62px;resize:vertical;grid-column:1/-1;padding:9px;border:1px solid #e1e5de;border-radius:8px;background:#fbfaf6;color:#314b4b;font:11px/1.5 inherit}}.save-feedback{{align-self:center;color:#6c9382;font-size:9px}}.advisor-button{{margin:10px 0 0;border:1px solid #d7e5dc;border-radius:8px;background:linear-gradient(100deg,#edf5ee,#f8f5e9);color:#326e65;padding:9px 11px;font-size:10px;font-weight:750}}.advisor-button:disabled{{opacity:.55;cursor:wait}}.advisor-privacy{{margin:5px 0 0;color:#929c96;font-size:9px;line-height:1.45}}.advisor-result{{margin:8px 0 12px;padding:12px;border:1px solid #e6e5dc;border-radius:9px;background:#faf9f4;color:#596966;font-size:10px;line-height:1.55}}.advisor-result h4{{margin:8px 0 4px;color:#365951;font-size:10px}}.advisor-result ul{{margin:3px 0 7px;padding-left:17px}}.advisor-result li{{margin:3px 0}}.distance-chip{{padding:3px 6px;border:1px solid #e6e4da;border-radius:5px;background:#faf8f1;color:#98815a;font-size:9px}}.profile-panel{{grid-column:1/-1}}.profile-chips{{display:flex;flex-wrap:wrap;gap:7px;margin-top:10px}}.profile-chip{{padding:6px 9px;border:1px solid #e6e4da;border-radius:7px;background:#f7f5ed;color:#58706a;font-size:10px}}.compare-dialog{{width:min(920px,calc(100% - 28px));max-height:85vh;overflow:auto;padding:22px;border:1px solid #d9dfd7;border-radius:16px;background:#fffefa;color:#1b3442;box-shadow:0 28px 90px rgba(12,30,38,.28)}}.compare-dialog::backdrop{{background:rgba(9,25,33,.58);backdrop-filter:blur(3px)}}.dialog-top{{display:flex;justify-content:space-between;align-items:start;gap:12px;margin-bottom:16px}}.dialog-top h2{{margin:3px 0 0;font:500 27px Georgia,serif}}.dialog-close{{width:34px;height:34px;border:0;border-radius:9px;background:#f0f1eb;color:#49605e;font-size:22px}}.compare-table{{width:100%;border-collapse:collapse;font-size:11px}}.compare-table th,.compare-table td{{padding:11px 10px;border-bottom:1px solid #e9e9e1;text-align:left;vertical-align:top}}.compare-table th{{width:145px;color:#7e8b86;font-weight:650}}.compare-table td{{color:#344d4a}}.compare-table a{{color:#177b73;font-weight:700}}.compare-empty{{color:#929b94;font-size:12px}}
@media(max-width:1100px){{.toolbar{{grid-template-columns:repeat(3,minmax(0,1fr))}}.search-wrap{{grid-column:1/-1}}}}
@media(max-width:980px){{.intelligence-grid{{grid-template-columns:1fr 1fr}}}}
@media(max-width:720px){{.intelligence-grid{{grid-template-columns:1fr}}.heading-actions{{width:100%;flex-direction:column;align-items:stretch}}.compare-open{{width:100%}}.tracker-summary{{grid-template-columns:repeat(2,minmax(0,1fr))}}.career-actions{{align-items:flex-start}}.status-control{{width:100%}}.status-select{{flex:1;max-width:none}}
.favorite-filter{{display:flex;align-items:center;gap:7px;padding:0 6px;color:#788681;font-size:10px}}.favorite-filter input{{accent-color:#20776e}}.saved-history{{margin:35px 0 10px;padding:18px;border:1px solid var(--line);border-radius:14px;background:var(--surface)}}.saved-history-list{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}}.saved-history-item{{display:flex;justify-content:space-between;align-items:center;gap:10px;padding:11px;border:1px solid #ecebe4;border-radius:9px;background:#fbfaf6}}.saved-history-item strong{{display:block;color:#344c4a;font-size:11px}}.saved-history-item small{{display:block;margin-top:3px;color:#89938f;font-size:9px}}.saved-history-item a{{color:#19766f;font-size:10px;font-weight:750;text-decoration:none;white-space:nowrap}}.event-history{{margin:5px 0 10px;padding:10px;border:1px solid #e4e9e1;border-radius:8px;background:#f7f8f2;color:#66746e;font-size:9px}}.event-history p{{margin:4px 0}}.event-history strong{{color:#41645c}}
@media print{{body{{background:#fff}}.hero{{background:#18374a!important;-webkit-print-color-adjust:exact;print-color-adjust:exact;padding-bottom:34px}}.metrics-wrap{{margin-top:16px}}.toolbar,.card-actions,.job-details summary,.source-section{{display:none!important}}.job-grid{{grid-template-columns:1fr 1fr}}.opportunity-card{{break-inside:avoid;box-shadow:none}}.job-details{{display:block}}.job-details:not([open])>*:not(summary){{display:block}}.main{{padding-top:12px}}}}
</style>
</head>
<body>
<header class="hero">
  <div class="shell hero-content">
    <div class="topbar">
      <div class="brand"><span class="brand-icon">A</span><span>ACHAVAGAI <span class="brand-sub">/ INTELLIGENCE</span></span></div>
      <span class="private-pill">Relatório local e privado</span>
    </div>
    <div class="hero-grid">
      <div class="hero-copy">
        <div class="eyebrow">Seu radar profissional</div>
        <h1>Oportunidades<br>com direção.</h1>
        <p>Uma seleção organizada para você analisar oportunidades, comparar aderência e seguir direto para a candidatura.</p>
        <div class="query-line"><span class="query-chip">Cargos: <strong>{_esc(termos_label)}</strong></span><span class="query-chip">Região: <strong>{_esc(local_label)}</strong></span>{('<span class="query-chip">Janela: <strong>Últimos ' + _esc(dias) + ' dias</strong></span>') if dias else ''}</div>
      </div>
      <aside class="hero-side"><div><div class="side-label">Pesquisa concluída</div><strong class="side-value">{_esc(gerado)}</strong></div><div class="side-foot">{total} oportunidade(s)<br>na aba principal do Excel</div></aside>
    </div>
  </div>
</header>
<div class="shell metrics-wrap">
  <section class="metrics" aria-label="Resumo da pesquisa">
    <div class="metric"><span class="metric-label">Vagas na seleção</span><strong class="metric-number">{total:02d}</strong><span class="metric-caption">Mesmo conjunto da aba “Vagas”</span></div>
    <div class="metric"><span class="metric-label">Cargos pesquisados</span><strong class="metric-number">{categorias.get('Pesquisa direta', 0):02d}</strong><span class="metric-caption">Correspondência direta no título</span></div>
    <div class="metric"><span class="metric-label">Compatíveis</span><strong class="metric-number">{categorias.get('Compatível com currículo', 0):02d}</strong><span class="metric-caption">Aderência às áreas do perfil</span></div>
    <div class="metric"><span class="metric-label">Fontes</span><strong class="metric-number">{fontes_total:02d}</strong><span class="metric-caption">Portais com vaga nesta seleção</span></div>
  </section>
</div>
<main class="shell main">
  <section class="intelligence-grid" aria-label="Inteligência da pesquisa">
    <article class="insight-panel"><div class="panel-heading"><div><span class="panel-kicker">VISÃO DE MERCADO</span><h2>De onde vêm as oportunidades</h2></div><span class="panel-icon">↗</span></div><div class="chart-bars">{_graficos_barras(fontes, 7)}</div></article>
    <article class="insight-panel"><div class="panel-heading"><div><span class="panel-kicker">DISTRIBUIÇÃO</span><h2>Áreas profissionais</h2></div><span class="panel-icon">◎</span></div><div class="chart-bars">{_graficos_barras(categorias, 5)}</div></article>
    <article class="insight-panel map-panel"><div class="panel-heading"><div><span class="panel-kicker">GEOGRAFIA</span><h2>Onde estão as vagas</h2></div><span class="panel-icon">⌖</span></div>{_mapa_esquematico(cidades, cidade_base)}<p class="map-disclaimer">Mapa esquemático. Distâncias aproximadas em linha reta entre centros municipais; não representam rota ou tempo de deslocamento.</p></article>
    <article class="insight-panel"><div class="panel-heading"><div><span class="panel-kicker">MINHA JORNADA</span><h2>Acompanhamento de candidaturas</h2></div><span class="panel-icon">✓</span></div><div class="tracker-summary" id="trackerSummary"><div><strong id="trackedCount">0</strong><span>acompanhadas</span></div><div><strong id="favoriteCount">0</strong><span>favoritas</span></div><div><strong id="sentCount">0</strong><span>enviadas</span></div><div><strong id="interviewCount">0</strong><span>entrevistas</span></div></div><p class="tracker-caption" id="trackerMode">As alterações serão salvas neste navegador ou no banco local SQLite.</p></article>
    <article class="insight-panel profile-panel"><div class="panel-heading"><div><span class="panel-kicker">SEU PERFIL PROFISSIONAL</span><h2>{_esc(perfil_publico.get("cargo_sugerido") or "Perfil identificado")}</h2></div><span class="panel-icon">✦</span></div><p class="tracker-caption">{_esc(perfil_publico.get("senioridade") or "Senioridade não identificada")} · Competências e áreas extraídas do currículo, sem dados de contato.</p><div class="profile-chips">{profile_chips or '<span class="muted">Nenhuma competência estruturada disponível.</span>'}</div></article>
  </section>
  <div class="toolbar" aria-label="Filtros das oportunidades">
    <div class="search-wrap"><input id="search" class="field search-field" type="search" placeholder="Buscar cargo, empresa, cidade ou palavra..." aria-label="Buscar vagas"></div>
    <select id="source" class="field" aria-label="Filtrar por fonte"><option value="">Todas as fontes</option>{source_options}</select>
    <select id="city-filter" class="field" aria-label="Filtrar por cidade"><option value="">Todas as cidades</option>{''.join(f'<option value="{_esc(city)}">{_esc(city)}</option>' for city in sorted(cidades))}</select>
    <select id="distance-filter" class="field" aria-label="Filtrar por distância aproximada"><option value="">Todas as distâncias</option><option value="30">Até 30 km</option><option value="60">Até 60 km</option><option value="100">Até 100 km</option><option value="more100">Mais de 100 km</option><option value="unknown">Sem estimativa</option></select>
    <select id="modality-filter" class="field" aria-label="Filtrar por modalidade"><option value="">Todas as modalidades</option><option>Remoto</option><option>Híbrido</option><option>Presencial</option><option>Não informada</option></select>
    <select id="salary-filter" class="field" aria-label="Filtrar por salário"><option value="">Com ou sem salário informado</option><option value="yes">Somente com salário</option><option value="no">Sem salário informado</option></select>
    <select id="status-filter" class="field" aria-label="Filtrar por acompanhamento"><option value="">Todas as etapas</option><option>Encontrada</option><option>Quero me candidatar</option><option>Candidatura enviada</option><option>Aguardando resposta</option><option>Entrevista agendada</option><option>Aprovado</option><option>Recusado</option><option>Arquivada</option></select>
    <select id="sort" class="field" aria-label="Ordenar vagas"><option value="score">Maior pontuação primeiro</option><option value="date">Mais recentes primeiro</option><option value="title">Cargo A–Z</option></select>
    <label class="favorite-filter"><input id="favorite-filter" type="checkbox"> Apenas favoritas</label>
    <button id="clear-filters" class="field clear-filters" type="button">Limpar filtros</button>
  </div>
  <div class="filter-foot">
    <nav class="tabs" aria-label="Categorias">
      <button class="tab active" data-category="all">Todas <span class="tab-count">{total}</span></button>
      <button class="tab" data-category="Pesquisa direta">Cargos pesquisados <span class="tab-count">{categorias.get('Pesquisa direta', 0)}</span></button>
      <button class="tab" data-category="Compatível com currículo">Compatíveis <span class="tab-count">{categorias.get('Compatível com currículo', 0)}</span></button>
      <button class="tab" data-category="Alternativa">Alternativas <span class="tab-count">{categorias.get('Alternativa', 0)}</span></button>
    </nav>
    <span class="visible-count" id="resultCount">Exibindo {total} oportunidades</span>
  </div>
  <section class="section-heading"><div><h2 class="section-title">Sua lista de oportunidades</h2><p class="section-subtitle">Mesmo conjunto da aba principal “Vagas” do Excel. Escolha até três para comparar.</p></div><div class="heading-actions"><button id="compare-open" class="compare-open" type="button" disabled>Comparar selecionadas <span id="compare-count">0/3</span></button><label class="sort-wrap">Ordenação <select id="sort-compact" class="field"><option value="score">Maior pontuação</option><option value="date">Mais recentes</option><option value="title">Cargo A–Z</option></select></label></div></section>
  <section id="jobList" class="job-grid">{cards_html}</section>
  <div class="notice"><span class="notice-mark">i</span><span><strong>Sobre as pontuações:</strong> cada cartão identifica se a nota veio da avaliação IA/cache ou da similaridade local. Notas TF-IDF não são diretamente comparáveis às notas do Gemini. Confirme requisitos, salário e disponibilidade no anúncio original.</span></div>
  <section class="saved-history" id="saved-history" hidden><div class="source-heading"><h2>Oportunidades acompanhadas de pesquisas anteriores</h2><p>Somente favoritos, candidaturas e vagas com notas são exibidos aqui; registros preservados no banco local SQLite.</p></div><div id="saved-history-list" class="saved-history-list"></div></section>
  <section class="saved-history research-history" id="research-history" hidden><div class="source-heading"><h2>Pesquisas recentes</h2><p>Histórico das execuções realizadas nesta pasta de resultados.</p></div><div id="research-history-list" class="saved-history-list"></div></section>
  <dialog id="compare-dialog" class="compare-dialog"><div class="dialog-top"><div><span class="panel-kicker">ANÁLISE LADO A LADO</span><h2>Comparar oportunidades</h2></div><button id="compare-close" class="dialog-close" type="button" aria-label="Fechar">×</button></div><div id="compare-content" class="compare-content"></div></dialog>
  <section class="source-section"><div class="source-heading"><h2>Fontes presentes nesta seleção</h2><p>Contagem baseada somente nas vagas exibidas acima.</p></div><div class="source-panel">{source_chips or '<span class="muted">Nenhuma fonte com vagas.</span>'}</div></section>
  <footer class="footer"><span><strong>AchaVagAI</strong> · Plataforma local e privada de carreira.</span><span>Este painel espelha a aba “Vagas” do Excel. Acompanhamento SQLite e consultor IA ficam disponíveis quando aberto pela Central de Resultados.</span></footer>
</main>
<script>
(function(){{
  const list=document.getElementById('jobList');
  const cards=Array.from(list.querySelectorAll('.opportunity-card'));
  const originalOrder=new Map(cards.map((card,index)=>[card,index]));
  const search=document.getElementById('search'), source=document.getElementById('source'), sort=document.getElementById('sort');
  const sortCompact=document.getElementById('sort-compact'), statusFilter=document.getElementById('status-filter'), cityFilter=document.getElementById('city-filter'), distanceFilter=document.getElementById('distance-filter'), modalityFilter=document.getElementById('modality-filter'), salaryFilter=document.getElementById('salary-filter'), favoriteFilter=document.getElementById('favorite-filter');
  const count=document.getElementById('resultCount');
  let category='all', serverMode=false;
  const selectedCompare=new Set();
  const uiKey='achavagai-painel-preferencias-v1';
  function saveUiPreferences(){{
    try{{localStorage.setItem(uiKey,JSON.stringify({{query:search.value,source:source.value,city:cityFilter.value,distance:distanceFilter.value,modality:modalityFilter.value,salary:salaryFilter.value,status:statusFilter.value,favorite:favoriteFilter.checked,sort:sort.value,category}}));}}catch(e){{}}
  }}
  function restoreUiPreferences(){{
    try{{
      const saved=JSON.parse(localStorage.getItem(uiKey)||'null');if(!saved||typeof saved!=='object')return;
      const setOption=(el,value)=>{{if([...el.options].some(o=>o.value===value))el.value=value;}};
      search.value=String(saved.query||'').slice(0,180);
      setOption(source,saved.source||'');setOption(cityFilter,saved.city||'');setOption(distanceFilter,saved.distance||'');
      setOption(modalityFilter,saved.modality||'');setOption(salaryFilter,saved.salary||'');setOption(statusFilter,saved.status||'');
      setOption(sort,saved.sort||'score');sortCompact.value=sort.value;favoriteFilter.checked=!!saved.favorite;
      if(['all','Pesquisa direta','Compatível com currículo','Alternativa'].includes(saved.category))category=saved.category;
      document.querySelectorAll('.tab[data-category]').forEach(x=>x.classList.toggle('active',x.dataset.category===category));
    }}catch(e){{}}
  }}
  restoreUiPreferences();
  const localKey='achavagai-candidaturas-v2';
  let localState={{}};
  try{{localState=JSON.parse(localStorage.getItem(localKey)||'{{}}')||{{}};}}catch(e){{localState={{}};}}
  const statusLabels=['Encontrada','Quero me candidatar','Candidatura enviada','Aguardando resposta','Entrevista agendada','Aprovado','Recusado','Arquivada'];
  const norm=s=>(s||'').toLocaleLowerCase('pt-BR').normalize('NFD').replace(/[\u0300-\u036f]/g,'');
  const byId=new Map(cards.map(c=>[c.dataset.jobId,c]));
  function stateFor(card){{return localState[card.dataset.jobId]||{{favorite:false,status:'Encontrada',notes:''}};}}
  function cardPayload(card,state){{return {{job_id:card.dataset.jobId,url:card.dataset.url,title:card.dataset.title,company:card.dataset.company,city:card.dataset.city,source:card.dataset.source,score:Number(card.dataset.score),favorite:!!state.favorite,status:state.status||'Encontrada',notes:state.notes||''}};}}
  function updateState(card,patch){{
    const id=card.dataset.jobId, previous=stateFor(card), state={{...previous,...patch}};
    const eventos=Array.isArray(previous.history)?previous.history.slice(0,20):[];
    if(patch.status && patch.status!==previous.status)eventos.unshift({{detail:'Etapa alterada',old_status:previous.status||'Encontrada',new_status:patch.status,created_at:new Date().toISOString()}});
    if(Object.prototype.hasOwnProperty.call(patch,'favorite') && !!patch.favorite!==!!previous.favorite)eventos.unshift({{detail:patch.favorite?'Adicionada aos favoritos':'Removida dos favoritos',old_status:previous.status||'Encontrada',new_status:previous.status||'Encontrada',created_at:new Date().toISOString()}});
    state.history=eventos.slice(0,20); localState[id]=state;
    try{{localStorage.setItem(localKey,JSON.stringify(localState));}}catch(e){{}}
    renderState(card,state); updateTrackerSummary();
    if(serverMode){{fetch('/api/tracker',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(cardPayload(card,state))}}).catch(()=>{{}});}}
  }}
  function renderState(card,state){{
    const fav=card.querySelector('[data-role="favorite"]'); if(fav){{fav.classList.toggle('is-favorite',!!state.favorite);fav.setAttribute('aria-pressed',String(!!state.favorite));fav.textContent=state.favorite?'★ Favoritada':'☆ Favoritar';}}
    const st=card.querySelector('[data-role="status"]'); if(st)st.value=statusLabels.includes(state.status)?state.status:'Encontrada';
    const notes=card.querySelector('[data-role="notes"]'); if(notes&&notes.value!==state.notes)notes.value=state.notes||'';
  }}
  function updateTrackerSummary(){{
    const values=Object.values(localState), countStatus=s=>values.filter(v=>v.status===s).length;
    const acompanhadas=values.filter(v=>v.favorite||((v.status||'Encontrada')!=='Encontrada')||!!(v.notes||'')).length;
    const fav=values.filter(v=>v.favorite).length;
    document.getElementById('trackedCount').textContent=acompanhadas;
    document.getElementById('favoriteCount').textContent=fav;
    document.getElementById('sentCount').textContent=countStatus('Candidatura enviada');
    document.getElementById('interviewCount').textContent=countStatus('Entrevista agendada');
  }}
  async function bootTracker(){{
    try{{
      if(location.protocol==='http:' && ['127.0.0.1','localhost'].includes(location.hostname)){{
        const health=await fetch('/api/health',{{cache:'no-store'}}); if(health.ok){{serverMode=true;}}
      }}
      if(serverMode){{
        document.getElementById('trackerMode').textContent='Salvamento permanente ativo: favoritos, etapas, notas e histórico ficam no banco local SQLite.';
        const res=await fetch('/api/tracker',{{cache:'no-store'}}); const data=await res.json();
        Object.entries(data.items||{{}}).forEach(([id,item])=>{{localState[id]={{...localState[id],favorite:!!item.favorite,status:item.status||'Encontrada',notes:item.notes||''}};}});
        renderPreviousJobs(data.items||{{}});
        try{{const rh=await fetch('/api/research-history',{{cache:'no-store'}});if(rh.ok)renderResearchHistory((await rh.json()).items||[]);}}catch(e){{}}
        try{{localStorage.setItem(localKey,JSON.stringify(localState));}}catch(e){{}}
      }}else{{
        document.getElementById('trackerMode').textContent='Modo arquivo: alterações salvas neste navegador. Abra pela Central de Resultados para sincronizar com SQLite e usar análises IA sob demanda.';
      }}
    }}catch(e){{serverMode=false;document.getElementById('trackerMode').textContent='Modo local do navegador: alterações guardadas neste perfil do Chrome.';}}
    cards.forEach(c=>renderState(c,stateFor(c)));updateTrackerSummary();
  }}
  function renderPreviousJobs(items){{
    const previous=Object.entries(items).filter(([id,item])=>!byId.has(id)&&(!!item.favorite||(item.status&&item.status!=='Encontrada')||!!String(item.notes||'').trim()));
    if(!previous.length)return;
    const wrap=document.getElementById('saved-history'), target=document.getElementById('saved-history-list');wrap.hidden=false;
    target.innerHTML=previous.sort((a,b)=>String(b[1].updated_at||'').localeCompare(String(a[1].updated_at||''))).slice(0,100).map(([id,item])=>{{
      const meta=[item.company,item.city,item.status].filter(Boolean).join(' · ');
      const link=item.url&&/^https?:\\/\\//i.test(item.url)?`<a href="${{esc(item.url)}}" target="_blank" rel="noopener">Abrir ↗</a>`:'';
      return `<div class="saved-history-item"><div><strong>${{esc(item.title||'Oportunidade salva')}}</strong><small>${{esc(meta)}}</small></div>${{link}}</div>`;
    }}).join('');
  }}
  function renderResearchHistory(items){{
    if(!Array.isArray(items)||!items.length)return;
    const wrap=document.getElementById('research-history'),target=document.getElementById('research-history-list');
    wrap.hidden=false;
    target.innerHTML=items.slice(0,20).map(item=>{{
      const date=item.generated_at?new Date(item.generated_at).toLocaleString('pt-BR'):'';
      const detail=[item.city,item.job_count+' vagas',(item.terms||[]).join(', ')].filter(Boolean).join(' · ');
      return `<div class="saved-history-item"><div><strong>${{esc(date||'Pesquisa anterior')}}</strong><small>${{esc(detail)}}</small></div><span>${{esc(item.session_id||'')}}</span></div>`;
    }}).join('');
  }}
  function apply(){{
    const q=norm(search.value),src=source.value,st=statusFilter.value; let visible=0;
    cards.forEach(card=>{{
      const state=stateFor(card);
      const okCat=category==='all'||card.dataset.category===category;
      const okSource=!src||card.dataset.source===src;
      const okText=!q||norm(card.dataset.search).includes(q);
      const okStatus=!st||state.status===st;
      const okCity=!cityFilter.value||card.dataset.city===cityFilter.value;
      const km=card.dataset.distance===''?null:Number(card.dataset.distance), df=distanceFilter.value;
      const okDistance=!df||(df==='unknown'?km===null:(df==='more100'?km!==null&&km>100:km!==null&&km<=Number(df)));
      const okModality=!modalityFilter.value||card.dataset.modality===modalityFilter.value;
      const okSalary=!salaryFilter.value||(salaryFilter.value==='yes'?card.dataset.hasSalary==='1':card.dataset.hasSalary==='0');
      const okFavorite=!favoriteFilter.checked||!!state.favorite;
      const show=okCat&&okSource&&okText&&okStatus&&okCity&&okDistance&&okModality&&okSalary&&okFavorite;card.classList.toggle('hidden',!show);if(show)visible++;
    }});
    count.textContent=`Exibindo ${{visible}} de ${{cards.length}} oportunidades`;
  }}
  document.querySelectorAll('.tab[data-category]').forEach(btn=>btn.addEventListener('click',()=>{{category=btn.dataset.category;document.querySelectorAll('.tab[data-category]').forEach(x=>x.classList.toggle('active',x===btn));apply();saveUiPreferences();}}));
  [search,source,statusFilter,cityFilter,distanceFilter,modalityFilter,salaryFilter,favoriteFilter].forEach(el=>{{el.addEventListener('input',()=>{{apply();saveUiPreferences();}});el.addEventListener('change',()=>{{apply();saveUiPreferences();}});}});
  function ordenar(mode){{cards.sort((a,b)=>{{if(mode==='title')return a.dataset.title.localeCompare(b.dataset.title,'pt-BR');if(mode==='date')return Number(a.dataset.age)-Number(b.dataset.age);return Number(b.dataset.score)-Number(a.dataset.score)||originalOrder.get(a)-originalOrder.get(b);}}).forEach(c=>list.appendChild(c));apply();}}
  sort.addEventListener('change',()=>{{sortCompact.value=sort.value;ordenar(sort.value);saveUiPreferences();}});sortCompact.addEventListener('change',()=>{{sort.value=sortCompact.value;ordenar(sortCompact.value);saveUiPreferences();}});
  document.getElementById('clear-filters').addEventListener('click',()=>{{search.value='';source.value='';statusFilter.value='';cityFilter.value='';distanceFilter.value='';modalityFilter.value='';salaryFilter.value='';favoriteFilter.checked=false;category='all';document.querySelectorAll('.tab[data-category]').forEach(x=>x.classList.toggle('active',x.dataset.category==='all'));apply();saveUiPreferences();}});
  document.querySelectorAll('.map-point[data-city]').forEach(point=>{{
    const selectCity=()=>{{cityFilter.value=point.dataset.city;apply();saveUiPreferences();document.getElementById('jobList').scrollIntoView({{behavior:'smooth',block:'start'}});}};
    point.addEventListener('click',selectCity);
    point.addEventListener('keydown',event=>{{if(event.key==='Enter'||event.key===' '){{event.preventDefault();selectCity();}}}});
  }});
  cards.forEach(card=>{{
    card.querySelector('[data-role="favorite"]').addEventListener('click',()=>updateState(card,{{favorite:!stateFor(card).favorite}}));
    card.querySelector('[data-role="status"]').addEventListener('change',e=>updateState(card,{{status:e.target.value}}));
    card.querySelector('[data-role="save-notes"]').addEventListener('click',()=>{{updateState(card,{{notes:card.querySelector('[data-role="notes"]').value}});card.querySelector('.save-feedback').textContent='Nota salva';setTimeout(()=>card.querySelector('.save-feedback').textContent='',1800);}});
    card.querySelector('[data-role="compare"]').addEventListener('change',e=>{{
      const id=card.dataset.jobId;
      if(e.target.checked&&selectedCompare.size>=3){{e.target.checked=false;alert('Compare no máximo três oportunidades por vez.');return;}}
      if(e.target.checked)selectedCompare.add(id);else selectedCompare.delete(id);
      updateCompareCount();
    }});
    card.querySelector('[data-role="advisor"]').addEventListener('click',()=>consultAdvisor(card));
    card.querySelector('[data-role="history"]').addEventListener('click',()=>toggleHistory(card));
  }});
  async function toggleHistory(card){{
    const panel=card.querySelector('[data-role="event-history"]');
    if(!panel.hidden){{panel.hidden=true;return;}}
    panel.hidden=false;panel.textContent='Carregando histórico...';
    try{{
      let events=stateFor(card).history||[];
      if(serverMode){{const response=await fetch('/api/events?job_id='+encodeURIComponent(card.dataset.jobId),{{cache:'no-store'}});const payload=await response.json();events=payload.events||[];}}
      if(!events.length){{panel.textContent='Ainda não há alterações registradas para esta oportunidade.';return;}}
      panel.innerHTML=events.map(ev=>{{const date=ev.created_at?new Date(ev.created_at).toLocaleString('pt-BR'):'';const transition=[ev.old_status,ev.new_status].filter(Boolean).join(' → ');return '<p><strong>'+esc(ev.detail||transition||'Atualização')+'</strong> '+esc(transition)+' <span>'+esc(date)+'</span></p>';}}).join('');
    }}catch(error){{panel.textContent='Não foi possível carregar o histórico desta oportunidade.';}}
  }}
  function updateCompareCount(){{const n=selectedCompare.size,btn=document.getElementById('compare-open');document.getElementById('compare-count').textContent=`${{n}}/3`;btn.disabled=n<2;}}
  document.getElementById('compare-open').addEventListener('click',()=>{{
    const chosen=[...selectedCompare].map(id=>byId.get(id)).filter(Boolean);if(chosen.length<2)return;
    const fields=[['Cargo',c=>c.dataset.title],['Empresa',c=>c.dataset.company],['Local',c=>c.dataset.city],['Fonte',c=>c.dataset.source],['Nota',c=>`${{Number(c.dataset.score).toFixed(0)}}/100`],['Categoria',c=>c.dataset.category],['Data',c=>c.querySelector('.date-label')?.textContent||'Não informada'],['Salário',c=>c.dataset.salary||'Não informado'],['Modalidade',c=>c.dataset.modality||'Não informada'],['Distância aproximada',c=>c.dataset.distance?`${{Number(c.dataset.distance).toFixed(0)}} km em linha reta`:'Não estimada'],['Acompanhamento',c=>stateFor(c).status],['Link',c=>c.dataset.url]];
    const head='<tr><th>Critério</th>'+chosen.map(c=>`<td><strong>${{esc(c.dataset.title)}}</strong></td>`).join('')+'</tr>';
    const rows=fields.slice(1).map(([name,get])=>'<tr><th>'+esc(name)+'</th>'+chosen.map(c=>'<td>'+ (name==='Link'&&c.dataset.url?`<a href="${{esc(c.dataset.url)}}" target="_blank" rel="noopener">Abrir vaga ↗</a>`:esc(get(c)))+'</td>').join('')+'</tr>').join('');
    document.getElementById('compare-content').innerHTML='<table class="compare-table">'+head+rows+'</table>';
    document.getElementById('compare-dialog').showModal();
  }});
  document.getElementById('compare-close').addEventListener('click',()=>document.getElementById('compare-dialog').close());
  function esc(s){{return String(s??'').replace(/[&<>"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));}}
  function renderAdvice(el,data){{
    const arr=(label,items)=>items?.length?`<h4>${{label}}</h4><ul>${{items.map(x=>'<li>'+esc(typeof x==='string'?x:(x.trecho||x.cargo||JSON.stringify(x)))+'</li>').join('')}}</ul>`:'';
    el.innerHTML=`<strong>${{esc(data.origem||'Consultor AchaVagAI')}}</strong><p>${{esc(data.resumo||'')}}</p>${{arr('Evidências do currículo',data.evidencias)}}${{arr('Habilidades relacionadas',data.habilidades_relacionadas)}}${{arr('Requisitos não comprovados',data.requisitos_nao_comprovados)}}${{arr('Riscos a conferir',data.riscos)}}<p><strong>Próximo passo:</strong> ${{esc(data.recomendacao||'Confira o anúncio original.')}}</p>`;el.hidden=false;
  }}
  async function consultAdvisor(card){{
    const btn=card.querySelector('[data-role="advisor"]'),panel=card.querySelector('[data-role="advisor-result"]');btn.disabled=true;btn.textContent='Analisando evidências...';panel.hidden=false;panel.textContent='O AchaVagAI está verificando os requisitos sem presumir experiências que não estejam documentadas.';
    try{{
      if(serverMode){{const r=await fetch('/api/advice',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{job_id:card.dataset.jobId}})}});const d=await r.json();if(!r.ok)throw new Error(d.error||'Falha na análise');renderAdvice(panel,d.advice||{{}});}}
      else{{renderAdvice(panel,{{origem:'Modo local do navegador',resumo:'Para usar o consultor com IA e salvar o histórico no SQLite, abra este painel pela opção 3 da Central de Resultados (.BAT).',evidencias:[],requisitos_nao_comprovados:['A análise IA sob demanda exige que o painel seja aberto pelo servidor local.'],recomendacao:'Feche este arquivo e abra a Central de Resultados; escolha o painel interativo.'}});}}
    }}catch(e){{panel.textContent='Não foi possível concluir a análise: '+e.message;}}
    finally{{btn.disabled=false;btn.textContent='✦ Analisar requisitos com o consultor';}}
  }}
  document.querySelectorAll('.copy-link').forEach(btn=>btn.addEventListener('click',async()=>{{const url=btn.dataset.link;try{{await navigator.clipboard.writeText(url);btn.textContent='Link copiado';}}catch(e){{window.prompt('Copie o link da oportunidade:',url);}}setTimeout(()=>btn.textContent='Copiar link',1800);}}));
  bootTracker().then(apply);
}})();
</script>
</body></html>'''

    html_doc = html_doc.replace('<meta name="color-scheme" content="light">', '<meta name="color-scheme" content="light"><meta name="achavagai-data" content="' + _esc(dados_path.name) + '">')
    destino.write_text(html_doc, encoding="utf-8")
    return destino


def salvar_html(
    ranking: list[tuple],
    caminho: str | Path,
    novas: set[int] | None = None,
    termos_busca: list[str] | tuple[str, ...] | None = None,
    perfil=None,
    metadata: dict | None = None,
) -> Path:
    """Alias semântico para uso no fluxo principal do aplicativo."""
    return gerar_html(ranking, caminho, novas, termos_busca, perfil, metadata)
