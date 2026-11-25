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

A análise por IA não deve ser tratada como garantia de contratação ou de exatidão absoluta. Confira a descrição original e os requisitos antes de se candidatar.

## 6. Resultados

O programa remove duplicatas, verifica datas e requisitos, classifica as vagas e cria `vagas_encontradas_AAAAMMDD_HHMM.xlsx`. A planilha inclui links de candidatura clicáveis e uma aba com mensagens de candidatura quando `--com-mensagens` é utilizado.

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

A suíte atual contém **510 testes automatizados**, executados sem acessar os sites nem consumir chaves de IA. Os testes simulam respostas HTML/JSON, erros HTTP, respostas Gemini e geração do Excel. Eles validam a lógica, mas não substituem uma verificação ao vivo dos portais nem garantem disponibilidade externa.

## 9. Estrutura

- `main.py`: fluxo da aplicação e fontes.
- `resume_parser.py`: leitura/estruturação do currículo.
- `matcher.py`: ranking por IA e alternativa local.
- `ia.py`: clientes Gemini/Claude, retries e seleção de modelo.
- `intencao_busca.py`: correspondência entre termos pesquisados e vagas.
- `habilitacao.py`, `filtros.py`: filtros objetivos.
- `scrapers/`: coletores, parser adaptativo e diagnósticos.
- `tests/`: testes automatizados.

Consulte `CHANGELOG.md` para o histórico das alterações.
