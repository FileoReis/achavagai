# Atualização 2026-11-27 — Painel HTML premium e seleção alinhada ao Excel

- Redesenhado o painel com identidade visual editorial premium, paleta clara sofisticada, cabeçalho escuro, métricas, cartões em grade, score circular e controles responsivos.
- Mantidos pesquisa textual, filtros por fonte/categoria, ordenação por nota/data/título, detalhes, links externos e cópia de link.
- O painel agora usa `selecionar_vagas_aba_principal()` compartilhado com o exportador Excel.
- O HTML espelha exatamente a aba principal `Vagas`: somente anúncios com data de publicação interpretável.
- Anúncios sem data permanecem na aba `Data não confirmada` do XLSX e não são incluídos no painel principal.
- Testes adicionados para comparar os títulos reais da aba `Vagas` do XLSX com os registros exibidos no HTML.
- Testes visuais automatizados em Chromium em desktop e mobile: sem overflow horizontal e sem erros JavaScript.
- HTML permanece autocontido, sem fontes ou bibliotecas externas; currículo, nome e chaves não são incorporados.
