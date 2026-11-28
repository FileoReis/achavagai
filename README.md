# AchaVagAI

Aplicativo local para ler um currículo em PDF, pesquisar oportunidades em vários portais, verificar requisitos eliminatórios, comparar as vagas com a experiência profissional e exportar os resultados para Excel.

## 1. Instalação no Windows

Abra o PowerShell na pasta do projeto:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

Edite o `.env` e preencha ao menos `GEMINI_API_KEY`. Crie chaves no Google AI Studio: <https://aistudio.google.com/apikey>.

Execute:

```powershell
python main.py
```

Exemplo sem perguntas:

```powershell
python main.py curriculo.pdf --sim --cidade "Rio de Janeiro" --cargo "Auxiliar de CPD, Motorista B" --dias 7
```

Python 3.11 ou superior.

## 2. Modelos Gemini e três chaves

O padrão é **Gemini 3.8 Flash**, com nível de raciocínio `high`. É a opção Flash de maior capacidade disponível na configuração padrão. Se falhar repetidamente por instabilidade/indisponibilidade ou falta de acesso, o sistema tenta `gemini-3.5-flash-lite`. O modelo 3.6 Flash não faz mais parte da lista padrão.

As três variáveis são reconhecidas:

```dotenv
GEMINI_API_KEY=...
GEMINI_API_KEY_2=...
GEMINI_API_KEY_3=...
```

As chaves adicionais servem como redundância quando o Google rejeita uma credencial inválida. O programa **não alterna chaves para contornar HTTP 429**: limites de uso são associados ao projeto Google Cloud, e chaves do mesmo projeto compartilham a cota. Ter três chaves no mesmo projeto não triplica a capacidade.

Para tentar o modelo de raciocínio de ponta, que pode gerar cobrança, habilite faturamento e defina conscientemente no `.env`:

```dotenv
GEMINI_MODEL=gemini-4-argon,gemini-3.8-flash,gemini-3.5-flash-lite
```

O projeto não habilita o modelo pago por padrão. Confira os preços e limites atuais antes de ativar: <https://ai.google.dev/gemini-api/docs/pricing>.

O modelo que funcionou pode ser lembrado por até sete dias em `.achavagai_modelo.json`. Para forçar uma lista própria, use `GEMINI_MODEL` com nomes separados por vírgula. Claude também pode ser configurado com `ANTHROPIC_API_KEY` e `CLAUDE_MODEL`; escolha o provedor com `IA_PROVEDOR=gemini` ou `IA_PROVEDOR=claude`.

## 3. Fontes de vagas

Fontes configuradas no projeto:

- Vagas.com e InfoJobs.
- Empregare, por API pública de consulta.
- Empregando Brasil, por feed XML público.
- Gupy, por endpoint JSON utilizado pelo portal público de busca. **Integração experimental**: esse endpoint público não é a API corporativa oficialmente documentada e pode mudar sem aviso.
- Jooble, por API. Precisa de uma chave própria em `JOOBLE_API_KEY` no `.env`.
  A coleta usa paginação (30 por página, até 3 páginas por termo por padrão). O plano gratuito documenta 100 chamadas por dia por chave; ajuste `JOOBLE_MAX_PAGINAS_POR_TERMO` em `config.py` com cuidado.
- Portais regionais: RioVagas, Rio Emprega, Rio Empregos e VagasRio. No VagasRio, se a busca nativa do WordPress vier vazia, o programa tenta uma vez o endpoint público padrão `/wp-json/wp/v2/posts`; se estiver desativado ou bloqueado, registra o status e continua com as demais fontes.

Indeed e LinkedIn ficam **desativados por padrão**. O terminal mostra um link separado para cada cargo pesquisado, evitando uma busca ampla que misture termos. Essas consultas manuais não entram automaticamente no ranking ou na planilha. Só habilite coleta automatizada se tiver autorização expressa aplicável; não há tentativa de contornar CAPTCHA, login ou controles anti-bot.

Ative ou desative cada fonte em `SITES_ATIVOS`, no `config.py`. A busca é feita por cada termo informado e os resultados do mesmo portal são deduplicados antes da contagem. A deduplicação também compara título, empregador e cidade; sufixos jurídicos comuns (Ltda., ME, EPP, S/A) são normalizados. Vagas sem empresa ou sem cidade não são fundidas apenas por terem títulos parecidos.

## 4. Verificador de fontes e adaptação de estrutura

Cada coletor registra o que aconteceu: resultado vazio, bloqueio/CAPTCHA, erro HTTP, falha de rede, configuração ausente ou possível mudança estrutural.

Para páginas HTML, o scraper tenta mais de uma estratégia em vez de depender apenas de um seletor CSS antigo:

1. seletores específicos do portal;
2. dados estruturados `JobPosting` em JSON-LD;
3. microdata Schema.org;
4. extração alternativa por cartões/links semânticos.

Os resultados das estratégias são mesclados e deduplicados. Se os seletores conhecidos falharem, o diagnóstico pode guardar em `diagnosticos/html/` um esqueleto da página contendo tags e atributos estruturais permitidos — sem texto de anúncio, links, cookies ou dados pessoais. Para APIs JSON, o diagnóstico guarda apenas nomes de campos e tipos, nunca valores dos anúncios. Respostas de XML são lidas com parser XML, sem avisos falsos do BeautifulSoup.

**Limite importante:** o programa consegue se recuperar automaticamente quando a página ainda expõe padrões estruturados reconhecíveis. Quando um portal inventa uma estrutura totalmente nova, o verificador detecta e registra a mudança para correção; ele não reescreve sozinho o código Python nem garante que todo redesign será entendido. CAPTCHA, autenticação e bloqueios não são contornados.

## 5. Leitura do currículo e aderência profissional

A análise do currículo procura separar fatos comprovados de competências transferíveis. O perfil estruturado pode conter:

- famílias profissionais em que há experiência ou formação;
- cargos sustentados pelo histórico profissional;
- experiências, atividades, períodos e formação;
- habilidades e senioridade;
- habilitações como CNH, sem presumir que possuir CNH significa querer trabalhar como motorista.

O ranking recebe esse contexto e diferencia experiência direta de habilidade transferível. Filtros determinísticos continuam eliminando incompatibilidades objetivas antes da pontuação da IA — por exemplo, CNH exigida, localização confirmada e data/prazo vencido.

A intenção da busca também é conferida no título e na descrição. CPD é tratado como Central de Processamento de Dados; a sigla PCD, de pessoa com deficiência, não é considerada correspondência de CPD. Dados de cidade/empresa não bastam para classificar uma vaga como correspondente ao cargo.

A análise por IA não deve ser tratada como garantia de contratação ou de exatidão absoluta. Confira a descrição original e os requisitos antes de se candidatar. O parser valida os trechos de evidência devolvidos pela IA contra o texto efetivamente extraído do PDF; palavras isoladas espalhadas em partes diferentes do currículo não bastam para comprovar uma experiência profissional.

Durante a coleta, o terminal também mostra um resumo de completude dos cartões de cada fonte (campos sem título, empresa, local, data, link ou descrição). Esse indicador ajuda a comparar a qualidade dos dados recebidos sem descartar automaticamente anúncios que podem ser enriquecidos depois pela página completa.

## 6. Pasta de resultados, planilha Excel e painel HTML

O programa remove duplicatas, verifica datas e requisitos, classifica as vagas e cria, por padrão, a pasta `Resultados_AchaVAGAI` na raiz do projeto. Cada execução salva nela os quatro arquivos da pesquisa: `.xlsx`, `.html`, `.bat` e `.ps1`. Isso mantém os resultados separados do código-fonte e evita espalhar arquivos na pasta principal.

Use `--saida "C:\\caminho\\para\\Resultados"` para escolher outra pasta. O parâmetro controla a pasta de todos os quatro artefatos, não apenas da planilha. Mesmo quando a busca não encontra vagas elegíveis, o programa gera uma planilha/painel vazios e a Central de Resultados para mostrar claramente que a consulta terminou sem oportunidades.

A planilha organiza os resultados em abas:

- `Vagas`: visão principal com publicações cuja data pôde ser interpretada.
- `Cargos pesquisados`: correspondência direta com os termos/intenções da busca.
- `Compatíveis`: outros cargos que combinam com famílias profissionais comprovadas no currículo.
- `Alternativas`: oportunidades que podem ser consideradas, mas não têm correspondência direta ou familiar forte.
- `Data não confirmada`: anúncios sem data de publicação interpretável; não são misturados às publicações datadas.
- `Todas as vagas`: **todo o universo que passou pelos filtros obrigatórios**, inclusive vagas fora do limite de análise individual do Gemini e vagas abaixo da nota mínima. A coluna `Base da pontuação` diferencia notas de IA/cache de similaridade local TF-IDF; notas locais não são comparáveis às notas de IA.
- `Como abrir links`: instruções para corrigir a associação HTTP/HTTPS do Windows.
- `Mensagens de Candidatura`: criada quando `--com-mensagens` é utilizado.

Os links da coluna `Link` continuam sendo hyperlinks externos HTTPS normais no XLSX. A planilha não consegue definir qual aplicativo o Windows usa para abrir HTTP/HTTPS. Se clicar no link abrir o Explorador/Documentos, configure Google Chrome como aplicativo padrão para os protocolos HTTP e HTTPS em Configurações do Windows > Aplicativos > Aplicativos padrão.

Ao lado de cada planilha é criado `abrir_links_chrome_<nome-da-planilha>.bat` e um arquivo `.ps1` correspondente. Ao terminar uma busca interativa, o próprio AchaVagAI mostra a pasta onde os resultados foram salvos e oferece `B` + Enter para abrir a Central imediatamente. Também é possível dar dois cliques no `.bat` depois. A central colorida oferece:

1. **Abrir uma vaga pelo número** — mostra a lista numerada e abre somente a vaga escolhida no Chrome.
2. **Abrir a planilha Excel (.xlsx)** — abre o arquivo no Excel ou no aplicativo padrão do Windows.
3. **Abrir o painel visual no navegador (.html)** — abre o painel da mesma pesquisa em uma nova janela do Chrome.
4. **Abrir a pasta desta pesquisa** — mostra a pasta com Excel, HTML e atalhos.
0. **Sair**.

O `.bat` inicia o menu e o `.ps1` contém a lógica de abertura. Mantenha os dois arquivos juntos, na mesma pasta da planilha e do HTML. O atalho chama diretamente o `chrome.exe` para vagas e painel, sem depender da associação HTTP/HTTPS do Windows. Para a planilha, usa o aplicativo padrão associado a `.xlsx` (normalmente Excel). Se o Chrome não for encontrado automaticamente, o menu permite informar o caminho completo do `chrome.exe`. Cada escolha abre somente o destino selecionado; nenhuma vaga é aberta automaticamente.

O histórico local permite marcar vagas novas e reaproveitar avaliações anteriores. Apague `.achavagai_historico.json` ou use `--sem-cache` para refazer avaliações.

Opções úteis:

| Opção | Função |
|---|---|
| `--sim` | Não pergunta os filtros; aceita sugestões quando não forem informadas. |
| `--cargo`, `--cidade`, `--bairro`, `--dias` | Define os filtros de busca. |
| `--nota-minima N` | Define a nota mínima (0 a 100). |
| `--top N` | Quantidade mostrada no terminal. |
| `--com-mensagens` | Gera mensagens para candidatura. |
| `--saida PASTA` | Define a pasta de saída. |
| `--sem-ia` | Usa o ranking local. |
| `--sem-cache` | Ignora avaliações anteriores. |
| `--sem-analise-profunda` | Não abre as páginas das vagas para completar a descrição. |

## 7. Privacidade e credenciais

- Não compartilhe `.env`, PDF do currículo, histórico ou cache.
- O texto encaminhado à IA passa por anonimização configurável. A limpeza automática reduz exposição, mas não é garantia de remover todos os dados identificáveis; revise o conteúdo antes de usar provedores externos.
- Os arquivos de diagnóstico são estruturais. Ainda assim, trate a pasta `diagnosticos/` como material técnico do projeto e revise antes de compartilhar.
- A chave Jooble também é segredo. Não a coloque em código-fonte nem em repositório.

## 8. Testes

Execute localmente:

```powershell
python -m pytest -q
```

A suíte atual contém **573 testes automatizados**, executados sem acessar os sites nem consumir chaves de IA. Os testes simulam respostas HTML/JSON, erros HTTP, respostas Gemini e geração do Excel. Eles validam a lógica, mas não substituem uma verificação ao vivo dos portais nem garantem disponibilidade externa.

## 9. Estrutura

- `main.py`: fluxo da aplicação e fontes.
- `resume_parser.py`: leitura/estruturação do currículo.
- `matcher.py`: ranking por IA e alternativa local.
- `ia.py`: clientes Gemini/Claude, retries e seleção de modelo.
- `intencao_busca.py`: correspondência entre termos pesquisados e vagas, inclusive títulos com espaços ausentes.
- `classificacao.py`: separa pesquisas diretas, vagas compatíveis e alternativas.
- `exportar.py`: planilha por categorias/datas e atalho de abertura direta no Chrome.
- `habilitacao.py`, `filtros.py`: filtros objetivos.
- `scrapers/`: coletores, parser adaptativo e diagnósticos.
- `tests/`: testes automatizados.

Consulte `CHANGELOG.md` para o histórico das alterações.

### Inicialização e leitura de PDF
O leitor `pdfplumber` é carregado sob demanda, somente quando o currículo é aberto. Assim, a tela inicial e `python main.py --help` não precisam carregar antecipadamente `pdfminer` e `cryptography`. Ao executar normalmente, o terminal mostra o tempo de carregamento dos módulos e avisa quando começa a preparar o leitor de PDF.

## Painel visual HTML

Ao terminar uma pesquisa, o AchaVagAI gera automaticamente um arquivo `vagas_encontradas_<data-hora>.html` na pasta `Resultados_AchaVAGAI` (ou na pasta indicada por `--saida`), junto da planilha Excel e dos atalhos BAT/PS1. Abra-o com dois cliques no navegador. O painel é autocontido e funciona localmente, sem servidor, hospedagem, CDN ou conexão externa para carregar a interface.

O painel HTML tem identidade visual premium, responsiva e autocontida, com pesquisa por texto, filtro por fonte, categorias, ordenação, cartões com pontuação/origem da nota, descrição e links para o anúncio. **Seu conjunto de vagas espelha exatamente a primeira aba `Vagas` do Excel**: apenas publicações com data interpretável. Anúncios sem data não aparecem no HTML e permanecem exclusivamente na aba `Data não confirmada` do workbook. Excel e HTML compartilham o mesmo seletor de registros para evitar divergência. Notas de similaridade local ficam identificadas separadamente das avaliações IA/cache. O HTML não inclui currículo, nome do candidato, chaves API ou histórico pessoal.

### Correção do menu de links no Chrome
O atalho `.bat` chama o `.ps1` correspondente. O menu agora lê um objeto JSON por linha e valida título/URL como valores escalares. Ao escolher um número, somente o link daquele registro é enviado ao Chrome. Se você tiver atalhos antigos que exibem `System.Object[]`, gere uma nova planilha para criar novos arquivos `.bat` e `.ps1` corrigidos; não é necessário editar o atalho antigo manualmente.


## Plataforma pessoal de carreira (SQLite + consultor + geografia)

Consulte `MUDANCAS_2026-11-28_PLATAFORMA.md` para abrir o dashboard interativo pela Central de Resultados, manter o acompanhamento em SQLite, filtrar por modalidade/salário/distância, clicar nos municípios do mapa, consultar o histórico de pesquisas e usar o consultor de requisitos. O servidor usa apenas `127.0.0.1`; o consultor IA só envia dados profissionais minimizados e descrição da vaga quando acionado.
