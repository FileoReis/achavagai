# Atualização 2026-11-27 — Painel HTML local

- Adicionado `html_report.py`, gerador de painel HTML responsivo e autocontido.
- O painel é salvo automaticamente ao lado do Excel, usando a mesma lista `ranking_exportacao`.
- Inclui indicadores de volume, categorias profissionais, datas confirmadas/desconhecidas e fontes.
- Inclui busca textual, filtros por categoria, fonte e data, ordenação por data ou título, cartões detalhados e abertura/cópia de links.
- Identifica claramente as pontuações IA/cache e as pontuações locais TF-IDF, sem tratá-las como equivalentes.
- Não incorpora currículo, nome do candidato, chaves API, histórico, scripts externos ou bibliotecas CDN.
- A geração é feita depois da exportação XLSX e não aumenta o tempo de inicialização do programa.
- Quando a busca não encontra nenhuma vaga elegível, também gera um painel HTML vazio com explicação, em vez de encerrar sem criar o relatório.
- A ordenação padrão preserva a ordem original do AchaVagAI; há opções para ordenar por data e título. Não mistura numericamente notas de IA e TF-IDF para produzir uma nova classificação.
- Testes de navegador com Chromium: pesquisa textual, categorias, filtro de data, execução sem erros JavaScript e layout mobile sem rolagem horizontal.
- Testes automatizados: 540 aprovados.
