# AchaVagAI — plataforma local de carreira

## Recursos desta versão

- Dashboard de vagas com indicadores por fonte/categoria e mapa esquemático clicável por município.
- Filtros de texto, fonte, cidade, distância aproximada, modalidade explicitamente identificada, salário informado, etapa de candidatura e favoritos.
- Comparação lado a lado de até três vagas.
- Favoritos, etapas da candidatura, notas privadas e histórico de alterações em SQLite.
- Histórico das pesquisas realizadas na mesma pasta de resultados.
- Consultor local/IA sob demanda para avaliar requisitos, evidências do currículo, lacunas e riscos.
- Cache do consultor invalidado quando a descrição, requisitos, título, empresa, local ou URL da vaga muda.
- Distâncias calculadas em linha reta entre centros municipais conhecidos; não são rotas nem estimativas de tempo.

## Como abrir com todos os recursos

1. Execute `python main.py` e conclua a busca.
2. Na Central de Resultados (`.bat`), escolha a opção **Plataforma interativa de carreira** (opção 3 no menu atual).
3. O servidor abre o painel no navegador e fica ativo na janela do terminal. Encerre com `Ctrl+C` nessa janela.
4. Use a pasta `Resultados_AchaVAGAI` para preservar o arquivo `carreira.sqlite3` entre pesquisas. Não apague esse banco se quiser manter candidaturas, notas, favoritos, eventos e histórico das pesquisas.

Abrir o `.html` diretamente continua disponível para leitura, filtros e armazenamento local do navegador, mas as funções que dependem do servidor — sincronização SQLite, histórico persistente entre sessões e consultor IA sob demanda — exigem abrir pela Central.

## Privacidade e segurança

- O servidor escuta exclusivamente em `127.0.0.1`; não expõe a aplicação à rede local/internet.
- As chaves de API permanecem no processo Python e nunca são inseridas no HTML/JavaScript.
- O consultor só é acionado quando o usuário clica no botão da vaga. Ele recebe dados profissionais minimizados e dados do anúncio; não recebe nome, telefone, e-mail nem o PDF bruto.
- As evidências apresentadas como citações devem corresponder literalmente a trechos estruturados do currículo. Habilidades transferíveis não são convertidas automaticamente em experiência profissional específica.
- Os dados de acompanhamento ficam localmente no SQLite. Faça backup da pasta de resultados para preservar o histórico.

## Observações

- Modalidade só é marcada como Remoto, Híbrido ou Presencial quando há indicação explícita no campo estruturado ou em expressões específicas do anúncio. Caso contrário aparece como “Não informada”.
- O mapa é esquemático; a distância é entre centros municipais e não representa rota real, trânsito ou tempo de viagem.
- A qualidade do conselho depende da completude do currículo estruturado, da descrição da vaga e da disponibilidade/cota do provedor de IA. A orientação local continua disponível quando a IA não responde.
