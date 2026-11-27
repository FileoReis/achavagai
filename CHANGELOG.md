## 24/11/2026 — Melhorias de coleta e diagnóstico

- Jooble: paginação habilitada, até 3 páginas de 30 vagas por termo por padrão; interrompe ao atingir `totalCount`, uma página curta ou ausência de novos anúncios. Deduplica IDs entre páginas e não inclui a chave real nas mensagens de erro.
- Jooble: configuração documentada em `JOOBLE_MAX_PAGINAS_POR_TERMO` e `JOOBLE_RESULTADOS_POR_PAGINA`, respeitando o limite diário documentado pelo plano gratuito.
- Empregare: requisição passa a usar os cabeçalhos gerais do projeto e registra HTTP 403 como acesso negado, sem chamar incorretamente de timeout e sem tentar contornar o bloqueio.
- Empregando Brasil: strings que sejam apenas URLs/texto puro não são mais enviadas ao BeautifulSoup; HTML em CDATA continua sendo convertido em texto.
- Diagnóstico: separa HTTP 401, 403, 407, 429 e 451 de erros de rede.
- Indeed e LinkedIn: terminal exibe uma pesquisa manual separada para cada termo, em vez de combinar todos os cargos em uma única busca ampla.

# Mudanças desta atualização (novembro de 2026)

## Bugs corrigidos (encontrados lendo o código e testando)

**"Motorista de Ônibus Urbano, CNH categoria D" com nota 75 para currículo com CNH B (relatado por você, com imagens)**
- A imagem mostrou três falhas na mesma linha. Nenhuma regra do programa garantia a categoria da CNH (dependia só da IA), a nota e o motivo da IA caíram na vaga errada, e a vaga era de 9 de abril (o scraper não trouxe a data, que está na página).
- **CNH por código** (`habilitacao.py`): lê a categoria no currículo (A, B, AB...) e descarta, antes da IA, a vaga que exige outra. A exigência vem do texto ("CNH categoria D válida", "Hab B", "CNH C ou D") ou do cargo (ônibus pede D, caminhão C, carreta E, motoboy A). Respeita a hierarquia (quem tem D também dirige B e C), ignora "diferencial" e "ajudante de motorista", e só age se o currículo informa a CNH. Conferido com o currículo real: leu A e B, e eliminou as duas vagas de ônibus da imagem. Listas como "CNH A/B", "A, B" e "B ou E" são lidas por inteiro (um A ou E sozinho só vale dentro de lista ou depois de "categoria"; sem isso, quem tem só CNH A seria eliminado de uma vaga "A/B").
- **Nota na vaga certa:** a IA agora devolve o começo do título que avaliou. O código confere com a vaga daquele número, move a nota para a vaga certa quando ela veio trocada (inclusive índices começando em 1) e pede de novo as que não batem com nenhuma. O terminal avisa quando corrige.
- **Motivos sem invenção:** o prompt proíbe citar características que não estão no texto (a imagem mostrava "vaga temporária" numa vaga CLT).
- **Data lida da página:** na análise profunda, o programa lê a data de publicação (dados estruturados, metadados, tag de data do artigo) e descarta a vaga antiga **antes** de gastar a IA. Também confere de novo a CNH e o prazo com a descrição completa.
- **Empresa e cidade:** "Motorista de Ônibus Urbano – Queimados – RJ" saía com empresa "Queimados" e cidade "RJ". Agora vem sem empresa e com cidade "Queimados, RJ".

**Troca de modelo repetida (relatado por você)**
- Quando o `gemini-3.8-flash` falhava, o programa o tentava **de novo em toda chamada** (uma por lote de vagas), e a mensagem nem dizia o motivo. O código só "lembrava" falhas em alguns casos, e na prática nenhum: cada chamada recomeçava pelo primeiro modelo da lista.
- Agora: modelo sem cota, sem acesso ou inexistente fica de lado até o fim da execução, e o aviso sai **uma vez**, com o motivo e o modelo que passa a ser usado. Limite por minuto e servidor instável geram só uma pausa de 60 segundos.
- O modelo que funcionou vira o primeiro da fila e fica gravado em `.achavagai_modelo.json`, então as próximas execuções vão **direto nele**. A lembrança vale 7 dias (`IA_LEMBRAR_MODELO_DIAS`). Uma falha passageira do melhor modelo não vira lembrança em arquivo.

**Vagas já encerradas (relatado por você)**
- Vagas como "Auxiliar de CPD, Princesa Supermercados, Comparecer no dia 24/08" apareciam em novembro. Dois motivos: esses portais não informam a data de publicação (então o filtro de idade não as via) e a IA **nunca recebeu a data de hoje**, então não tinha como saber que 24/08 já passou.
- Agora há um filtro por regras: lê datas ligadas a comparecer, entrevista, inscrição, prazo, "encerra" e "válido até" no título e no começo da descrição, e descarta a vaga se a data já passou. Trata datas sem ano (24/08 visto em novembro é de agosto; 05/01 é do ano que vem), intervalos ("de 05/11 a 20/11" vale pela data final) e ignora datas de início ("desde 01/09").
- A IA passou a receber "Data de hoje" e uma regra explícita: data de comparecimento ou prazo no passado vale nota 0. O texto do prompt mudou, então as notas antigas do cache deixam de valer (elas davam nota alta a essas vagas).
- Efeito colateral corrigido: o local da vaga era lido do **último** trecho do título, então "Cargo – Empresa – Penha Circular RJ – Comparecer no dia 24/08" ficava sem cidade. Agora procura de trás para frente o trecho que parece um local.

**Datas e região**
- `05/11/2026` era lido como 11 de maio (formato americano), e `dayfirst=True` do dateutil inverte dia e mês até em datas ISO. Textos como "há 3 dias" não eram entendidos, então a vaga nunca era descartada por idade. Agora entende dia/mês/ano, ISO, "há N dias/semanas/meses", "ontem" e "3 de novembro".
- O filtro de estado só via "Cidade / SP". Agora entende "Cidade, SP", "Cidade (SP)" e "Cidade - SP", ignora siglas que não são estado (como "TI") e **não descarta vagas remotas**.
- Repetidas: o mesmo anúncio com `?trackingId=...` diferente não era reconhecido, e a mesma vaga em dois sites também passava. Agora compara o link sem parâmetros de rastreio e também título, empresa e cidade.

**IA**
- Uma resposta fora do formato derrubava o script: nota escrita como "85%", índice ausente, objeto no lugar de lista. Tudo isso é tratado agora.
- JSON cortado no meio ("Unterminated string") perdia todas as notas. Agora aproveita os itens que chegaram completos e pede de novo só os que faltaram.
- No Gemini 3.x os tokens de raciocínio contam no limite de saída, então as mensagens de candidatura (limite 400) podiam vir vazias ou cortadas. Agora há folga de tokens e nível de raciocínio baixo.
- O Gemini 3.8 Flash não aceita o nível de raciocínio "minimal" que o código usava. O nível agora é escolhido por modelo, com repetição automática sem o parâmetro se for recusado.
- Erros 429 e 5xx não tinham nova tentativa. Agora espera o tempo pedido pelo servidor e tenta de novo, depois passa para o próximo modelo da lista.
- A IA não sabia a cidade da busca (só via o campo "Local" da vaga). Agora recebe cidade, bairro e UF.
- Empresa e cidade extraídas do título só eram preenchidas **depois** da avaliação. Agora são preenchidas antes.

**Ranking**
- Se a IA falhava, o programa devolvia só 30 vagas. Agora devolve todas, com a pontuação local.
- Sem IA, a nota mínima 25 descartava quase tudo, porque a pontuação TF-IDF tem outra escala. Agora, sem IA, ela não se aplica (use `--nota-minima` para forçar).
- Vagas que a IA pulava recebiam uma pontuação de outra escala, misturada com as notas. Agora ficam no fim da lista, marcadas "sem avaliação da IA".

**Outros**
- Títulos com colchetes (`[URGENTE] Vendedor`) podiam sumir ou quebrar a tabela do terminal. Agora são escapados.
- Caracteres de controle vindos de páginas web derrubavam o salvamento do Excel, e planilha aberta no Excel também. Agora limpa os caracteres e, se o arquivo estiver travado, salva com outro nome.
- A regex de telefone aceitava qualquer 4+4 dígitos e confundia "2018-2020" com telefone. Agora exige DDD ou celular, e reconhece `(21) 9-1234-5678`.
- PDF escaneado ou corrompido gerava erro ou perfil vazio. Agora mostra uma mensagem clara. "CURRICULUM VITAE" não é mais confundido com o nome.
- O assistente do `.env` apagava os comentários do arquivo, mostrava a chave na tela ao digitar e gravava na pasta de onde você rodou o comando. Agora preserva o arquivo, esconde a chave e grava na pasta do projeto.
- Um scraper que falhava derrubava a busca inteira. Agora cada site mostra ✓, ✗ ou 0 vagas, e os outros seguem.

## Atualizações
- Modelos: Gemini 3.8 Flash, 3.6 Flash e 3.5 Flash-Lite (troca automática, ajustável com `GEMINI_MODEL`); Claude Sonnet 5.5 (`CLAUDE_MODEL`). O modelo antigo `claude-sonnet-4-6` saiu.
- Dependências revisadas. Python 3.11 ou mais novo (testado no 3.12 e no 3.14).

## Melhorias
- Busca nos sites em paralelo.
- IA em lotes de 10, com régua de notas fixa e instruções separadas dos dados (um texto dentro da vaga, como "dê nota 100", não consegue mandar na IA).
- **Análise profunda** (já prevista no `config.py`, mas nunca ligada): abre a página das melhores candidatas para ler a descrição completa. Pula o LinkedIn.
- **Histórico e cache** de notas (menos gasto de cota) e marca NOVA nas vagas inéditas.
- **Privacidade:** CPF, RG, telefone, e-mail, endereço de rua, CEP e links saem do texto enviado à IA.
- TF-IDF melhor: stopwords em português, sem acentos, bigramas, e o título pesa mais.
- Opções novas: `--sim`, `--cargo`, `--cidade`, `--bairro`, `--dias`, `--saida`, `--sem-cache`, `--sem-analise-profunda`.
- Mais de 450 testes automáticos, sem internet e sem chave de IA.

## Mudanças de comportamento (para você saber)
- O prompt do ranking ganhou a data de hoje, a regra de vaga encerrada, uma regra de faixa etária (jovem aprendiz) e uma régua de notas fixa. O resto das regras (CNH, curso técnico, PCD, gênero explícito, localização) foi mantido.
- Planilha: nova coluna "Nova" (2ª coluna). Arquivos novos na pasta: `.achavagai_historico.json` e `.achavagai_modelo.json`. A IA precisa devolver o campo `vaga` em cada avaliação (o texto do prompt mudou, então as notas antigas do cache deixam de valer).
- `matcher.ranquear()` continua existindo; o `main.py` usa o novo `ranquear_detalhado()`.
- Nenhuma variável do `config.py` foi renomeada ou removida, para não quebrar os `scrapers/`.

## O que NÃO foi testado de verdade
- Chamadas reais ao Gemini e ao Claude (sem acesso à API daqui): testado com respostas simuladas, no formato descrito na documentação.
- Os sites de vagas e a análise profunda: testado com páginas de exemplo.
- A pasta `scrapers/` não veio no zip, então não foi lida nem atualizada.


## 24/11/2026 — Auditoria das fontes, Gemini e perfil profissional

- **Gemini:** passou a reconhecer `GEMINI_API_KEY`, `_2` e `_3` como credenciais redundantes; só troca de chave quando uma credencial é recusada, nunca para contornar HTTP 429. A ordem padrão usa Gemini 3.8 Flash (`high`) e fallback Gemini 3.5 Flash-Lite. O antigo Gemini 3.6 Flash foi removido da lista padrão. Gemini 4 Argon fica opt-in via `GEMINI_MODEL`, pois pode gerar cobrança.
- **Verificador adaptativo:** scrapers HTML combinam seletores do portal, JSON-LD `JobPosting`, microdata Schema.org e extração semântica de cartões/links. Diagnósticos diferenciam vazio, bloqueio, erro HTTP/rede e mudança estrutural provável. Snapshots HTML preservam apenas atributos estruturais; snapshots JSON preservam somente nomes de campos/tipos.
- **Gupy:** nova integração experimental com endpoint público JSON usado pelo portal. Não é a API corporativa documentada e pode mudar sem aviso.
- **Intenção profissional:** filtro de intenção antes do ranking, separação entre áreas/cargos comprovados e habilidades transferíveis, e tratamento específico de CPD sem confundir com PCD.
- **Fontes e conformidade:** Indeed e LinkedIn ficam desligados por padrão e aparecem como buscas manuais; Jooble requer chave própria. Empregare e Empregando Brasil permanecem integrados.
- **Testes:** 479 testes automatizados passaram; nenhum site real ou chave de IA foi acessado pela suíte.


## 25/11/2026 — Diagnóstico Empregare e fallback VagasRio

- Empregare: respostas JSON agora são validadas por schema antes da extração. A estrutura documentada `model.dados` continua sendo o caminho principal; wrappers comuns (`data`, `items`, `results`, `vagas`, `jobs`) só são aceitos quando os itens possuem campos de título reconhecidos.
- Empregare: quando o schema muda, o diagnóstico grava `diagnosticos/json/` com nomes de campos e tipos, sem valores dos anúncios, e deixa de produzir snapshots HTML vazios. Quando o servidor responde HTML, preserva apenas o esqueleto DOM para manutenção do parser.
- VagasRio: reconhece marcadores WordPress `search-no-results`/`.no-results` como busca sem resultados, não como mudança de layout. A URL de busca passa a ser codificada com `urlencode` e usa o domínio canônico `www.vagasrio.com.br`.
- VagasRio: quando a busca HTML não retorna anúncios relevantes, tenta uma consulta à API REST pública padrão do WordPress (`/wp-json/wp/v2/posts`) uma vez. Se a API estiver desativada/bloqueada, o erro é registrado sem tentar contornar controles.
- Diagnóstico: registra URL solicitada e URL final após redirecionamento, removendo query e fragmentos; evita contar duas vezes o mesmo HTTPError no coletor compartilhado.
- XML: a telemetria usa `ElementTree` para detectar bloqueios/resultados em feeds XML e não passa XML ao parser HTML do BeautifulSoup; o coletor Empregando Brasil informa Content-Type ao diagnóstico.
- Testes: 510 testes automatizados passaram, incluindo schema JSON da Empregare, snapshots sanitizados, páginas WordPress sem resultados, fallback REST do VagasRio e aviso XML.


## 27/11/2026 — Classificação baseada em evidências e correção dos links Excel

- Perfil do currículo: inclui indicadores locais para distinguir experiência profissional comprovada como motorista/entregador, objetivo explícito de condução e experiência específica em CPD. CNH e logística isoladas não são tratadas como prova de atuação profissional ao volante.
- Ranking IA: reforça instruções de evidência e revisa justificativas que afirmam experiência em condução ou CPD sem suporte no texto do currículo; quando necessário, corrige o motivo e limita a pontuação.
- Intenção de busca: reconhece títulos concatenados como `Técnico deInformaticaN1` e `MotoristaCarga`, mantendo CPD separado de PCD.
- Classificação profissional: adiciona `Pesquisa direta`, `Compatível com currículo` e `Alternativa`, sem promover motorista a compatível apenas por CNH/logística.
- Planilha: cria abas separadas para cargos pesquisados, compatíveis, alternativas, datas não confirmadas e visão consolidada. A aba principal `Vagas` mantém publicações com data interpretável.
- Links: mantém hyperlinks HTTPS externos corretos no XLSX e gera um `.BAT` + `.PS1` auxiliar que abre o Chrome diretamente, contornando apenas a associação errada do Windows quando o próprio usuário escolhe um link. Não altera configurações do Windows e não executa links automaticamente.
- Segurança Excel: conserva neutralização de conteúdo externo que poderia ser interpretado como fórmula e valida URLs HTTP/HTTPS.
- Testes: 525 testes automatizados passaram, incluindo classificação, evidências, separação por data, hyperlinks e criação do atalho auxiliar. Testes não acessam sites reais nem executam o PowerShell em Windows.

## 2026-11-27 — Inicialização mais transparente e leitura de PDF sob demanda
- `pdfplumber` agora é importado somente quando o currículo PDF é efetivamente lido.
- `python main.py --help` e a importação de `resume_parser` não carregam `pdfminer`/`cryptography` desnecessariamente.
- O programa mostra uma mensagem de inicialização imediatamente e informa o tempo de carregamento dos módulos.
- A etapa de leitura do currículo informa explicitamente quando o leitor PDF está sendo carregado.
- Erro de dependência ausente do leitor PDF agora apresenta orientação de instalação específica.


## 27/11/2026 — Exportação do universo elegível e classificação consistente

- Corrigida a perda de vagas fora do limite `IA_TOP_ANALISE`: o matcher preserva agora todas as oportunidades que passaram pelos filtros obrigatórios, mesmo quando não foram avaliadas individualmente pelo Gemini.
- Vagas sem análise IA/cache recebem pontuação TF-IDF local, com a base e a situação explicitadas no Excel; essas notas não são comparáveis às notas da IA e não são submetidas ao corte mínimo da IA.
- `Todas as vagas` passa a conter o universo elegível completo; `Vagas` contém as datas interpretáveis e `Data não confirmada` reúne todas as vagas sem data reconhecida. As três categorias profissionais são aplicadas por classificação do título e das evidências do perfil, sem transformar uma menção incidental na descrição em pesquisa direta.
- A correspondência direta é baseada no título e em sinônimos profissionais; exemplos como `Técnico de TI Jr.` entram na área de Informática, enquanto uma vaga administrativa que apenas menciona CPD na descrição não vira automaticamente vaga de CPD.
- Cargos de motorista não são classificados como compatíveis apenas porque o currículo menciona logística ou possui CNH; é necessária experiência de condução comprovada ou objetivo profissional explícito.
- O resumo do terminal utiliza a mesma lista completa enviada ao Excel e informa separadamente quantas vagas têm pontuação IA/cache e quantas têm apenas pontuação local.
- Testes: 535 testes automatizados aprovados.


## 27/11/2026 — Painel visual HTML local

- Ao final de cada pesquisa, o programa gera `vagas_encontradas_<data-hora>.html` ao lado do Excel. Se a busca não encontrar oportunidades, também cria um painel vazio com essa informação.
- Painel premium responsivo, autocontido e offline: busca instantânea, filtros por categoria/fonte/data, ordenação por ordem original/data/título, cartões detalhados, links de candidatura e cópia de URL.
- O HTML utiliza a mesma lista completa de vagas exportada no Excel e explicita a origem das notas (IA/cache ou TF-IDF local). Não compara numericamente notas locais e notas da IA para reordenar vagas.
- O relatório não inclui currículo, nome do candidato, chaves API ou histórico pessoal; não utiliza CDN, analytics, fontes externas ou servidor.
- Testes: 541 testes automatizados aprovados; testes de navegador Chromium verificaram filtros, ausência de erros JavaScript e responsividade a 390 px sem rolagem horizontal.

### Correção do atalho de abertura no Chrome (2026-11-27)
- Corrigido o gerador `.ps1` que podia interpretar a lista JSON como um único objeto com propriedades em array, exibindo `System.Object[]` no menu.
- O payload agora usa JSON Lines: um registro independente por linha, com título e URL escalares.
- A seleção do menu captura um único registro e abre somente a URL escolhida.
- Registros com título/URL em formato de array ou URL fora de HTTP/HTTPS são ignorados com aviso.

## 2026-11-27 — Painel HTML premium

- Redesenho visual premium e responsivo do painel HTML.
- Painel espelha exatamente a aba principal `Vagas` do Excel; registros sem data ficam somente na aba `Data não confirmada`.
- Seletor de registros compartilhado entre exportador XLSX e gerador HTML.
- Validação em Chromium desktop/mobile e testes de equivalência entre planilha e painel.


## 27/11/2026 — Central de oportunidades no atalho BAT/PS1

- O `.bat` agora configura título, cor e página de código do terminal e apresenta uma abertura mais amigável.
- O `.ps1` apresenta um menu PowerShell colorido com opções para abrir o painel HTML no Chrome, abrir uma vaga individual ou abrir a pasta da pesquisa.
- A opção do painel abre o HTML correspondente à planilha em uma nova janela do Chrome, usando caminho local convertido para URI `file://` (não depende da associação de arquivos HTML do Windows).
- A opção de vaga continua abrindo apenas o registro selecionado, em nova aba; a leitura JSON Lines e a validação HTTP/HTTPS foram preservadas.
- A busca pelo Chrome é feita sob demanda, apenas quando uma das opções de abertura é selecionada.
- Testes adicionados para opções do menu, caminho do HTML, cores do BAT e seleção individual de URL.

## 2026-11-27 — Central de resultados com Excel, HTML e vagas individuais
- Menu PowerShell gerado pelo BAT agora oferece: vaga individual numerada, abrir planilha XLSX, abrir painel HTML no Chrome e abrir pasta.
- O XLSX e o HTML são referenciados por nomes relativos à pasta do atalho, com nomes codificados em Base64 para preservar acentos e espaços.
- A mensagem final do AchaVagAI apresenta instruções claras e permite digitar B para abrir o BAT imediatamente em uma nova janela no Windows.
- O atalho continua sendo criado mesmo quando a pesquisa não tem links externos válidos, permitindo abrir a planilha, o painel ou a pasta.

- Validação desta revisão: 548 testes automatizados aprovados. Não foi possível executar o BAT/PS1 em uma sessão Windows real deste ambiente; a geração dos arquivos e os seus conteúdos foram verificados por testes estáticos.
