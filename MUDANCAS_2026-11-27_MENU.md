# Atualização da Central de Resultados — 27/11/2026

## Menu reorganizado
- [1] Abrir uma vaga pelo número: menu numerado; somente a URL selecionada abre no Chrome.
- [2] Abrir a planilha Excel: abre o `.xlsx` da mesma execução pelo aplicativo padrão do Windows.
- [3] Abrir o painel visual: abre o `.html` da mesma execução no Chrome.
- [4] Abrir a pasta da pesquisa.
- [0] Sair.

O `.ps1` recebe os nomes do XLSX e HTML em Base64, resolve os arquivos pela pasta do próprio atalho e não depende do diretório de trabalho atual. O `.bat` continua como iniciador.

## Mensagem final do CLI
Ao concluir uma busca interativa, o CLI mostra de forma destacada o nome do `.bat`, explica as opções e aceita `B` + Enter para abrir o atalho imediatamente no Windows. Com `--sim` ou entrada não interativa, não bloqueia a execução: apenas informa que o usuário pode dar dois cliques no `.bat`.

## Sem links de candidatura
O menu também é gerado quando não há URLs válidas, para que o usuário ainda possa abrir a planilha, o HTML ou a pasta. A opção de vagas individuais informa que não há links disponíveis.
