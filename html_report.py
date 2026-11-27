"""Geração de painel HTML premium, local e autocontido para o AchaVagAI."""
from __future__ import annotations

import html
from collections import Counter
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from classificacao import classificar_vaga
from exportar import selecionar_vagas_aba_principal
from filtros import idade_em_dias
from matcher import MOTIVO_SEM_IA

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


def _card(item: tuple, termos_busca, perfil, novas: set[int]) -> tuple[str, str, str]:
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

    card = f'''<article class="opportunity-card" data-category="{_esc(categoria)}" data-date="{data_tipo}"
      data-source="{_esc(fonte)}" data-age="{idade if idade is not None else 999999}"
      data-score="{nota:.2f}" data-title="{_esc(titulo)}" data-search="{_esc(busca)}">
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
          <span><i class="meta-symbol">▦</i>{_esc(fonte)}</span>
          {('<span><i class="meta-symbol">⌕</i>' + _esc(termo) + '</span>') if termo else ''}
        </div>
        <div class="card-footer">
          <div class="card-indicators">{base_badge}{'<span class="new-label">NOVA</span>' if is_nova else ''}</div>
          <div class="card-actions">{actions}</div>
        </div>
        {detalhe}
      </div>
    </article>'''
    return card, categoria, base


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
    notas_ia = 0
    notas_locais = 0
    for item in ranking_painel:
        card, categoria, base = _card(item, termos, perfil, novas)
        cards.append(card)
        categorias[categoria] += 1
        fontes[str(getattr(item[0], "fonte", "") or "Fonte não informada")] += 1
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

    source_options = "".join(
        f'<option value="{_esc(fonte)}">{_esc(fonte)}</option>' for fonte in sorted(fontes)
    )
    source_chips = "".join(
        f'<span class="source-chip"><span class="source-dot"></span>{_esc(nome)}<b>{qtd:02d}</b></span>'
        for nome, qtd in fontes.most_common()
    )
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
.main{{padding:32px 0 60px}}.toolbar{{display:grid;grid-template-columns:minmax(230px,1.7fr) minmax(180px,.8fr) minmax(170px,.7fr);gap:10px;padding:13px;border:1px solid var(--line);border-radius:14px;background:rgba(255,254,250,.9);box-shadow:0 8px 26px rgba(21,37,49,.035)}}.field{{width:100%;min-width:0;padding:12px 14px;border:1px solid #e5e3dc;border-radius:9px;outline:none;background:#fbfaf6;color:var(--ink);font-size:12px;transition:border-color .18s,box-shadow .18s}}.field:focus{{border-color:#6aa9a1;box-shadow:0 0 0 3px rgba(20,125,120,.1)}}.search-wrap{{position:relative}}.search-wrap:before{{content:"⌕";position:absolute;left:14px;top:7px;color:#75878a;font-size:22px;pointer-events:none}}.search-field{{padding-left:43px}}.filter-foot{{display:flex;justify-content:space-between;align-items:center;gap:16px;margin:17px 2px 20px}}.tabs{{display:flex;align-items:center;gap:7px;overflow:auto;padding-bottom:2px;scrollbar-width:thin}}.tab{{display:inline-flex;align-items:center;gap:8px;padding:9px 12px;border:1px solid transparent;border-radius:8px;background:transparent;color:#737f83;white-space:nowrap;font-size:11px;font-weight:650;transition:all .16s}}.tab:hover{{background:#ebece6;color:var(--ink)}}.tab.active{{border-color:#cfe2dc;background:#e4f0ec;color:#176f69}}.tab-count{{display:inline-grid;min-width:20px;height:20px;place-items:center;padding:0 5px;border-radius:6px;background:rgba(20,125,120,.09);font-size:10px}}.visible-count{{color:#828d8d;font-size:11px;white-space:nowrap}}.section-heading{{display:flex;justify-content:space-between;align-items:end;gap:16px;margin:18px 0 15px}}.section-title{{margin:0;font:500 26px/1.1 Georgia,"Times New Roman",serif;letter-spacing:-.025em}}.section-subtitle{{margin:5px 0 0;color:#8a9392;font-size:11px}}.sort-wrap{{display:flex;align-items:center;gap:8px;color:#84908f;font-size:11px}}.sort-wrap select{{width:auto;min-width:175px;background:var(--surface)}}
.job-grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}}.opportunity-card{{position:relative;overflow:hidden;border:1px solid #e5e3dc;border-radius:14px;background:var(--surface);box-shadow:var(--shadow-card);transition:transform .2s,border-color .2s,box-shadow .2s}}.opportunity-card:hover{{transform:translateY(-2px);border-color:#c9d8d2;box-shadow:0 17px 34px rgba(21,37,49,.085)}}.card-accent{{height:3px;background:linear-gradient(90deg,#177c76,#8cb9a6 58%,#d9b77b)}}.opportunity-inner{{padding:17px 18px 15px}}.opportunity-top{{display:flex;justify-content:space-between;align-items:center;gap:10px}}.category-tag{{display:inline-flex;align-items:center;gap:7px;max-width:70%;padding:6px 9px;border-radius:6px;font-size:10px;font-weight:750;letter-spacing:.025em}}.tag-direct{{background:#e4f1ec;color:#1a746b}}.tag-compatible{{background:#e9eef5;color:#496d8a}}.tag-alternative{{background:#f5eee1;color:#946d37}}.tag-indicator{{width:6px;height:6px;border-radius:50%;background:currentColor}}.date-label{{color:#7f8d8b;font-size:10px;white-space:nowrap}}.opportunity-main{{display:grid;grid-template-columns:43px minmax(0,1fr) 68px;gap:12px;align-items:center;margin:16px 0 13px}}.company-mark{{width:43px;height:43px;display:grid;place-items:center;border:1px solid #e6e2d6;border-radius:12px;background:linear-gradient(145deg,#f7f5ee,#efeee6);color:#3d6967;font:600 14px Georgia,serif;letter-spacing:-.04em}}.role-copy{{min-width:0}}.role-copy h3{{margin:0;color:#1a2f3d;font-size:17px;line-height:1.25;font-weight:720;letter-spacing:-.025em;overflow-wrap:anywhere}}.company-name{{margin:5px 0 0;color:#87918f;font-size:12px}}.score-orb{{width:65px;height:65px;display:grid;place-items:center;border-radius:50%;background:conic-gradient(#177f77 var(--score-angle),#e9ece6 0);padding:4px}}.score-orb-inner{{width:100%;height:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;border:1px solid #e8e9e2;border-radius:50%;background:var(--surface)}}.score-orb strong{{color:#1e746e;font:600 20px/1 Georgia,serif}}.score-orb span{{margin-top:3px;color:#98a19e;font-size:8px}}.opportunity-meta{{display:flex;flex-wrap:wrap;gap:7px 15px;padding:11px 0;border-top:1px solid #eeede7;border-bottom:1px solid #eeede7;color:#7b8887;font-size:10px}}.opportunity-meta span{{display:inline-flex;align-items:center;gap:5px}}.meta-symbol{{color:#ae986e;font-size:13px;font-style:normal}}.card-footer{{display:flex;justify-content:space-between;align-items:center;gap:10px;padding-top:12px}}.card-indicators,.card-actions{{display:flex;align-items:center;flex-wrap:wrap;gap:7px}}.score-origin{{display:inline-flex;align-items:center;gap:6px;color:#87918f;font-size:9px}}.origin-dot{{width:6px;height:6px;border-radius:50%;background:#5d9b8e}}.origin-local .origin-dot{{background:#c49a51}}.new-label{{padding:4px 6px;border-radius:4px;background:#e6f3e9;color:#3e8551;font-size:8px;font-weight:800;letter-spacing:.1em}}.action-primary,.action-secondary{{display:inline-flex;align-items:center;justify-content:center;gap:7px;min-height:32px;padding:7px 10px;border-radius:7px;text-decoration:none;font-size:10px;font-weight:700;transition:all .16s}}.action-primary{{border:1px solid #176e69;background:#176e69;color:white}}.action-primary:hover{{border-color:#0f5d59;background:#0f5d59;box-shadow:0 5px 12px rgba(23,110,105,.18)}}.action-secondary{{border:1px solid #e1e2da;background:#fffefa;color:#62716e}}.action-secondary:hover{{border-color:#b8ccc4;background:#eef4ef;color:#1b625e}}.no-link{{color:#a2a6a0;font-size:10px}}.job-details{{margin-top:12px;border-top:1px solid #eeede7}}.job-details summary{{padding-top:10px;color:#647977;font-size:10px;font-weight:700;cursor:pointer;list-style:none}}.job-details summary::-webkit-details-marker{{display:none}}.job-details summary:after{{content:"＋";float:right;color:#5f9086;font-size:12px}}.job-details[open] summary:after{{content:"−"}}.description-text{{margin-top:10px;color:#586665;font-size:11px;line-height:1.65;white-space:pre-wrap;overflow-wrap:anywhere}}.description-cut{{color:#9a927e;font-size:10px}}.analysis-note{{margin-top:12px;padding:12px 13px;border-left:2px solid #c7a66d;border-radius:0 8px 8px 0;background:#f8f5ed}}.note-label{{color:#9c865d;font-size:8px;font-weight:800;letter-spacing:.14em}}.analysis-note p{{margin:5px 0 0;color:#5c6662;font-size:11px;line-height:1.55}}
.source-panel{{display:flex;flex-wrap:wrap;gap:8px;padding:16px;border:1px solid var(--line);border-radius:12px;background:var(--surface)}}.source-chip{{display:inline-flex;align-items:center;gap:8px;padding:8px 10px;border:1px solid #e9e7df;border-radius:7px;background:#fbfaf6;color:#6e7c7a;font-size:10px}}.source-chip b{{color:#304a55;font-size:10px}}.source-dot{{width:6px;height:6px;border-radius:50%;background:#4f9a89}}.source-heading{{display:flex;justify-content:space-between;align-items:end;gap:12px;margin:36px 0 12px}}.source-heading h2{{margin:0;font:500 22px Georgia,serif}}.source-heading p{{margin:0;color:#919a96;font-size:10px}}.empty-state{{grid-column:1/-1;padding:52px 20px;border:1px dashed #cdd4cd;border-radius:14px;background:rgba(255,254,250,.7);text-align:center}}.empty-icon{{width:52px;height:52px;display:grid;place-items:center;margin:0 auto 13px;border-radius:16px;background:#e8f1ed;color:#2b7770;font-size:27px}}.empty-state h3{{margin:0;font:500 23px Georgia,serif}}.empty-state p{{margin:8px auto 0;max-width:420px;color:#83908c;font-size:12px}}.notice{{display:flex;gap:10px;align-items:flex-start;margin:19px 0 0;padding:13px 15px;border:1px solid #e7dfcc;border-radius:10px;background:#faf6eb;color:#827354;font-size:10px;line-height:1.55}}.notice strong{{color:#6d5b36}}.notice-mark{{flex:0 0 19px;width:19px;height:19px;display:grid;place-items:center;border-radius:50%;background:#f0e4c9;color:#8b6b31;font-size:11px;font-weight:800}}.footer{{display:flex;justify-content:space-between;gap:18px;margin-top:40px;padding:20px 0 8px;border-top:1px solid #dfded7;color:#8a9490;font-size:10px}}.footer strong{{color:#455c5c}}.hidden{{display:none!important}}
@media(max-width:1000px){{.hero-grid{{grid-template-columns:minmax(0,1fr) 220px;gap:25px}}.metrics{{grid-template-columns:repeat(2,minmax(0,1fr))}}}}
@media(max-width:720px){{.shell{{width:min(100% - 28px,620px)}}.hero{{padding:19px 0 65px}}.topbar{{padding-bottom:24px}}.brand-sub{{display:none}}.private-pill{{font-size:9px;padding:7px 9px}}.hero-grid{{grid-template-columns:1fr;gap:18px;padding:30px 0 4px}}h1{{font-size:43px}}.hero-side{{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:13px 15px}}.side-value{{margin:0;font-size:19px}}.side-foot{{text-align:right}}.metrics-wrap{{margin-top:-35px}}.metric{{min-height:98px;padding:14px}}.metric-number{{font-size:29px}}.main{{padding-top:23px}}.toolbar{{grid-template-columns:1fr 1fr;padding:10px;gap:8px}}.search-wrap{{grid-column:1/-1}}.field{{font-size:11px;padding:11px}}.filter-foot{{display:block;margin-top:12px}}.tabs{{padding-bottom:8px}}.visible-count{{display:block;text-align:right;margin-top:3px}}.section-heading{{align-items:start;flex-direction:column;margin-top:17px}}.sort-wrap{{width:100%;justify-content:space-between}}.sort-wrap select{{flex:1}}.job-grid{{grid-template-columns:1fr;gap:11px}}.opportunity-inner{{padding:15px}}.role-copy h3{{font-size:16px}}.card-footer{{align-items:flex-start;flex-direction:column}}.card-actions{{width:100%}}.action-primary,.action-secondary{{flex:1}}.source-heading{{align-items:flex-start;flex-direction:column}}.footer{{flex-direction:column;gap:7px}}}}
@media(max-width:380px){{.shell{{width:calc(100% - 22px)}}.metrics{{gap:7px}}.metric{{padding:11px}}.metric-label{{font-size:8px}}.metric-number{{font-size:26px}}.opportunity-main{{grid-template-columns:36px minmax(0,1fr) 58px;gap:9px}}.company-mark{{width:36px;height:36px}}.score-orb{{width:57px;height:57px}}.score-orb strong{{font-size:18px}}}}
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
  <div class="toolbar" aria-label="Filtros das oportunidades">
    <div class="search-wrap"><input id="search" class="field search-field" type="search" placeholder="Buscar cargo, empresa, cidade ou palavra..." aria-label="Buscar vagas"></div>
    <select id="source" class="field" aria-label="Filtrar por fonte"><option value="">Todas as fontes</option>{source_options}</select>
    <select id="sort" class="field" aria-label="Ordenar vagas"><option value="score">Maior pontuação primeiro</option><option value="date">Mais recentes primeiro</option><option value="title">Cargo A–Z</option></select>
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
  <section class="section-heading"><div><h2 class="section-title">Sua lista de oportunidades</h2><p class="section-subtitle">Somente vagas presentes na primeira aba da planilha, com data interpretável.</p></div><label class="sort-wrap">Ordenação <select id="sort-compact" class="field"><option value="score">Maior pontuação</option><option value="date">Mais recentes</option><option value="title">Cargo A–Z</option></select></label></section>
  <section id="jobList" class="job-grid">{cards_html}</section>
  <div class="notice"><span class="notice-mark">i</span><span><strong>Sobre as pontuações:</strong> cada cartão identifica se a nota veio da avaliação IA/cache ou da similaridade local. Notas TF-IDF não são diretamente comparáveis às notas do Gemini. Confirme requisitos, salário e disponibilidade no anúncio original.</span></div>
  <section class="source-section"><div class="source-heading"><h2>Fontes presentes nesta seleção</h2><p>Contagem baseada somente nas vagas exibidas acima.</p></div><div class="source-panel">{source_chips or '<span class="muted">Nenhuma fonte com vagas.</span>'}</div></section>
  <footer class="footer"><span><strong>AchaVagAI</strong> · Radar de oportunidades gerado localmente.</span><span>Este painel espelha a aba “Vagas” do Excel. Anúncios sem data interpretável ficam na aba separada “Data não confirmada”.</span></footer>
</main>
<script>
(function(){{
  const list=document.getElementById('jobList');
  const cards=Array.from(list.querySelectorAll('.opportunity-card'));
  const originalOrder=new Map(cards.map((card,index)=>[card,index]));
  const search=document.getElementById('search');
  const source=document.getElementById('source');
  const sort=document.getElementById('sort');
  const sortCompact=document.getElementById('sort-compact');
  const count=document.getElementById('resultCount');
  let category='all';
  const norm=s=>(s||'').toLocaleLowerCase('pt-BR').normalize('NFD').replace(/[\\u0300-\\u036f]/g,'');
  function apply(){{
    const q=norm(search.value),src=source.value;
    let visible=0;
    cards.forEach(card=>{{
      const okCat=category==='all'||card.dataset.category===category;
      const okSource=!src||card.dataset.source===src;
      const okText=!q||norm(card.dataset.search).includes(q);
      const show=okCat&&okSource&&okText;
      card.classList.toggle('hidden',!show);if(show)visible++;
    }});
    count.textContent=`Exibindo ${{visible}} de ${{cards.length}} oportunidades`;
  }}
  document.querySelectorAll('.tab[data-category]').forEach(btn=>btn.addEventListener('click',()=>{{
    category=btn.dataset.category;
    document.querySelectorAll('.tab[data-category]').forEach(x=>x.classList.toggle('active',x===btn));apply();
  }}));
  [search,source].forEach(el=>{{el.addEventListener('input',apply);el.addEventListener('change',apply);}});
  function ordenar(mode){{
    cards.sort((a,b)=>{{
      if(mode==='title')return a.dataset.title.localeCompare(b.dataset.title,'pt-BR');
      if(mode==='date')return Number(a.dataset.age)-Number(b.dataset.age);
      return Number(b.dataset.score)-Number(a.dataset.score)||originalOrder.get(a)-originalOrder.get(b);
    }}).forEach(card=>list.appendChild(card));
    apply();
  }}
  sort.addEventListener('change',()=>{{sortCompact.value=sort.value;ordenar(sort.value);}});
  sortCompact.addEventListener('change',()=>{{sort.value=sortCompact.value;ordenar(sortCompact.value);}});
  document.querySelectorAll('.copy-link').forEach(btn=>btn.addEventListener('click',async()=>{{
    const url=btn.dataset.link;
    try{{await navigator.clipboard.writeText(url);btn.textContent='Link copiado';}}
    catch(e){{window.prompt('Copie o link da oportunidade:',url);}}
    setTimeout(()=>btn.textContent='Copiar link',1800);
  }}));
  apply();
}})();
</script>
</body></html>'''

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
