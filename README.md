# AchaVagAI — Busca automática de vagas a partir do currículo

Script em Python que lê seu currículo em PDF, sugere filtros de busca (cidade,
bairro, cargo desejado — com IA quando disponível), procura vagas no LinkedIn,
Indeed, Vagas.com, InfoJobs e em portais regionais do Rio de Janeiro (RioVagas,
Rio Emprega, Rio Empregos, VagasRio), ranqueia os resultados por compatibilidade
com seu currículo (com justificativa da IA), gera mensagens de candidatura
personalizadas para as melhores vagas, e salva tudo em uma planilha Excel pronta
para uso.

## 1. Instalação

```bash
cd achavagai
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## 2. Configurar sua chave de IA (uma vez só)

1. Copie o arquivo `.env.example` para `.env` (mesma pasta do `main.py`).
2. Preencha com sua chave — recomendo o **Gemini**, que é gratuito:
   - Acesse **https://aistudio.google.com/apikey**, faça login com sua conta
     Google e clique em "Create API key" (não pede cartão de crédito).
   - Cole a chave no `.env`:
     ```
     GEMINI_API_KEY=cole-sua-chave-aqui
     ```
3. Pronto — o script lê o `.env` sozinho a partir de agora. Não precisa mais
   digitar `$env:GEMINI_API_KEY=...` toda vez que abrir o terminal.

Se preferir usar o Claude (Anthropic) em vez do Gemini, preencha
`ANTHROPIC_API_KEY` no lugar (uso pago). Sem nenhuma das duas chaves, o script
funciona normalmente, só que com uma análise mais simples (veja a seção 4).

**Nunca compartilhe o conteúdo do seu `.env`** (nem aqui, nem em print, nem em
repositórios de código) — trate a chave como uma senha.

## 3. Uso básico

```bash
python main.py caminho/para/seu_curriculo.pdf
```

O script vai:
1. Ler o PDF. Se houver IA configurada, ela lê o currículo inteiro e extrai um
   perfil estruturado (cidade, bairro, cargo sugerido, senioridade, principais
   habilidades e um resumo do perfil) — mais preciso do que buscar palavras-chave
   soltas. Sem IA, usa a extração local por palavras-chave como alternativa.
2. Perguntar se você quer confirmar ou ajustar os filtros (Enter aceita o valor
   sugerido). Você pode informar **vários cargos separados por vírgula** (ex.:
   `Técnico em Informática, Vendedor`) — o script busca cada um separadamente e
   combina os resultados.
3. Buscar vagas em todos os sites configurados.
4. Ranquear as vagas por aderência ao currículo, e **descartar automaticamente**
   as vagas com nota muito baixa (veja `--nota-minima` abaixo).
5. Gerar uma mensagem de candidatura pronta para as melhores vagas (se houver IA).
6. Mostrar tudo em tabelas coloridas no terminal e salvar em uma planilha Excel
   (`vagas_encontradas_AAAAMMDD_HHMM.xlsx`) com duas abas: **Vagas** (com nota,
   motivo da IA e link clicável) e **Mensagens de Candidatura**.

### Opções de linha de comando

```
--sem-ia                    Desativa toda a análise de IA (mesmo com chave configurada)
--com-mensagens              Gera mensagens de candidatura personalizadas (desativado por padrão)
--top N                     Quantas vagas mostrar no resumo (padrão: 15)
--top-mensagens N           Para quantas vagas gerar mensagem de candidatura (padrão: 5)
--nota-minima N             Nota mínima 0-100 para uma vaga aparecer nos resultados (padrão: 30)
```

Exemplo: `python main.py curriculo.pdf --nota-minima 50 --top 10`

## 4. Como funciona a análise com IA

O script detecta automaticamente qual IA usar, nesta ordem: **Gemini** (se
`GEMINI_API_KEY` estiver definida) → **Claude** (se `ANTHROPIC_API_KEY` estiver
definida) → **TF-IDF local** (sem IA nenhuma, sempre funciona, mas sem
justificativa e menos preciso quanto a sinônimos/contexto).

Quando há IA disponível, ela é usada em três pontos:
- **Extração do currículo**: perfil estruturado (cidade, cargo, senioridade etc.)
- **Ranking das vagas**: nota 0–100 + justificativa curta por vaga, considerando
  área, senioridade e localização — não só palavras em comum.
- **Mensagens de candidatura**: um texto curto e pronto para copiar e enviar,
  personalizado para cada uma das melhores vagas.

## 5. Estrutura do projeto

```
achavagai/
├── main.py                     # orquestra todo o fluxo
├── resume_parser.py            # lê o PDF e extrai o perfil do candidato (IA + local)
├── matcher.py                  # ranqueia vagas (IA + TF-IDF local)
├── mensagem.py                 # gera mensagens de candidatura personalizadas
├── ia.py                       # camada única de acesso a Gemini/Claude
├── config.py                   # cidades, bairros, palavras-chave, nota mínima etc.
├── .env.example                # modelo para suas chaves de API
└── scrapers/
    ├── base.py                 # classe Vaga + utilidades HTTP
    ├── utils.py                 # geração de slugs de URL
    ├── linkedin.py              # busca pública de vagas no LinkedIn
    ├── indeed.py                 # busca no Indeed Brasil
    ├── vagas_com.py               # busca no Vagas.com.br
    ├── infojobs.py                 # busca no InfoJobs Brasil
    └── generic_wordpress.py        # busca em portais WordPress (RioVagas etc.)
```

## 6. Sites cobertos, e por que Catho/Gupy não estão na lista

Cobertos: **LinkedIn**, **Indeed**, **Vagas.com**, **InfoJobs**, e os portais
regionais **RioVagas**, **Rio Emprega**, **Rio Empregos**, **VagasRio**.

**Catho** e **Gupy** ficaram de fora por limitações técnicas reais, não por
falta de tentativa:
- O **Catho** carrega os resultados de busca via JavaScript (a página inicial
  vem praticamente vazia, só preenchida depois pelo navegador) — scraping
  simples com `requests` não consegue ler o conteúdo. Seria necessário um
  navegador automatizado (Selenium/Playwright), o que traz mais complexidade,
  lentidão e maior chance de bloqueio.
- A **Gupy** não tem um portal de busca único — cada empresa tem sua própria
  página de vagas (`empresa.gupy.io`), e a API pública oficial exige
  autenticação por empresa. Não há como buscar "todas as vagas da Gupy" de uma
  vez sem uma lista prévia de quais empresas consultar.

Se quiser, posso te ajudar a adicionar manualmente páginas de carreira
específicas de empresas que usam Gupy (ex.: `empresa.gupy.io/vagas`), já que
essas costumam ser mais simples de ler.

## 7. Como adicionar novos sites de vagas

- **Sites baseados em WordPress** (blogs de vagas, comuns em portais regionais):
  adicione uma entrada no dicionário `SITES_WORDPRESS` em
  `scrapers/generic_wordpress.py` com o nome e a URL base do site.
- **Sites com estrutura própria e renderizados no servidor** (não dependem de
  JavaScript): crie um novo arquivo em `scrapers/`, seguindo o padrão de
  `vagas_com.py` ou `infojobs.py`.
- **Sites que dependem de JavaScript** (a maioria dos grandes portais modernos):
  não são cobertos por este script sem ferramentas adicionais (Selenium/
  Playwright), que trazem bem mais complexidade e lentidão.

## 8. Avisos importantes (leia antes de usar)

- **Termos de uso dos sites**: scraping automatizado pode violar os Termos de
  Uso de alguns sites — especialmente o **LinkedIn**, que proíbe explicitamente
  coleta automatizada. O scraper aqui usa um endpoint público (sem login), mas
  isso pode parar de funcionar sem aviso ou levar a bloqueio temporário do seu
  IP se usado com muita frequência. Use com moderação.
- **Fragilidade dos scrapers**: sites mudam o HTML com frequência. Se um site
  parar de retornar resultados, o motivo mais provável é que a estrutura da
  página mudou — os seletores em `scrapers/*.py` precisam ser atualizados.
- **Robots.txt e limites de requisição**: o script já inclui uma pequena pausa
  (`REQUEST_DELAY_SECONDS` em `config.py`) entre requisições. Evite rodar o
  script em loop contínuo/muito frequente.
- **Dados pessoais e IA**: nada é enviado a terceiros a menos que você tenha
  configurado uma chave de IA — nesse caso, o texto do currículo e as vagas
  pré-selecionadas são enviados ao provedor escolhido (Google ou Anthropic)
  para gerar as notas, justificativas e mensagens de candidatura.

## 9. Limitações conhecidas

- Os portais regionais (RioVagas, Rio Emprega etc.) funcionam como blogs e não
  têm filtro estruturado de cidade — a "vaga" é o post do blog. A busca nativa
  desses sites (parâmetro "?s=" do WordPress) nem sempre filtra de verdade —
  confirmamos que o **VagasRio especificamente ignora o termo pesquisado** e
  sempre devolve os posts mais recentes do site inteiro (testamos comparando
  uma busca real com uma busca por um termo que não existe — os dois
  retornaram o mesmo conteúdo). Por isso o script aplica um **filtro local de
  segurança**: só mantém vagas cujo título/descrição realmente contenham a
  palavra buscada, descartando o resto — mas isso significa que, se o site não
  tiver nenhuma vaga relevante entre os posts mais recentes, você vai ver
  poucos ou nenhum resultado desse portal para termos de nicho.
- O Indeed pode exigir captcha em navegação intensa; quando isso acontece, o
  script simplesmente não retorna resultados desse site naquela execução.
- Sem IA configurada, a extração de perfil e o ranking de vagas usam regras
  simples (palavras-chave/TF-IDF) — bem mais rápido, porém menos preciso que a
  análise com IA, e sem verificação de requisitos concretos (habilitação, curso
  técnico específico, elegibilidade PCD etc.) — que só a IA consegue avaliar
  lendo o currículo.
- O filtro de dias descarta vagas cuja data de publicação seja identificável e
  esteja fora do prazo; vagas sem data reconhecível (comum no Indeed, InfoJobs e
  Vagas.com) são mantidas, já que não é possível confirmar a idade delas.
