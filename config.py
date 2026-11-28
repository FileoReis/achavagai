"""
Configurações gerais do AchaVagAI.
Ajuste as listas abaixo conforme sua região / área de atuação.

Importante: não renomeie nem apague as variáveis existentes. Os módulos da pasta
scrapers/ também leem este arquivo.
"""

# User-Agent "de navegador" para reduzir bloqueios simples de scraping.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}

# Tempo de espera (segundos) entre requisições ao mesmo site, para não sobrecarregar
# o servidor e reduzir o risco de bloqueio por excesso de requisições.
REQUEST_DELAY_SECONDS = 2.0

# Tempo de espera ao buscar a descrição completa de cada vaga individualmente
# (etapa de "análise profunda").
DESCRICAO_DELAY_SECONDS = 1.0

# Quantas vagas (as melhores colocadas na pré-análise) recebem busca da descrição
# completa antes do ranking final. Números maiores = análise mais profunda, porém
# mais lenta (cada vaga extra = 1 requisição HTTP a mais).
QUANTIDADE_ANALISE_PROFUNDA = 25

# Se True, mostra mensagens técnicas de falha de requisição (para depuração).
# Deixe False para uma saída mais limpa no dia a dia.
MODO_DETALHADO = False

# Todos os artefatos de uma pesquisa concluída (XLSX, HTML, BAT e PS1) ficam
# agrupados nesta pasta dentro do projeto. Pode ser substituída com --saida.
PASTA_RESULTADOS = "Resultados_AchaVAGAI"

# Cidades/municípios comumente usados nas vagas da região do Rio de Janeiro.
# Usado como apoio para o parser do currículo tentar identificar a cidade do candidato.
CIDADES_RJ = [
    "Rio de Janeiro", "São Gonçalo", "Duque de Caxias", "Nova Iguaçu",
    "Campos dos Goytacazes", "Belford Roxo", "Niterói", "São João de Meriti",
    "Petrópolis", "Volta Redonda", "Macaé", "Magé", "Itaboraí", "Cabo Frio",
    "Nilópolis", "Mesquita", "Queimados", "Itaguaí", "Angra dos Reis",
]

# Bairros comuns (principalmente zona sul/centro/zona norte do Rio) para apoio
# ao parser. Adicione os bairros relevantes para você.
# "Centro" fica por último porque a palavra aparece em muitos textos que não são
# bairro (ex.: "centro de distribuição"), e o primeiro item encontrado é o escolhido.
BAIRROS_RJ = [
    "Copacabana", "Ipanema", "Leblon", "Botafogo", "Flamengo",
    "Tijuca", "Barra da Tijuca", "Jacarepaguá", "Bangu", "Campo Grande",
    "Gávea", "Recreio", "Méier", "Madureira", "Santa Cruz", "Sepetiba",
    "Belford Roxo", "Centro",
]

# Palavras-chave de habilidades/áreas usadas para tentar identificar o perfil
# profissional a partir do texto do currículo. Edite/expanda livremente.
SKILL_KEYWORDS = [
    # TI / Dados
    "python", "java", "javascript", "typescript", "sql", "power bi", "excel avançado",
    "react", "node.js", "django", "flask", "machine learning", "inteligência artificial",
    "devops", "aws", "azure", "docker", "kubernetes", "scrum", "agile",
    # Administrativo / Comercial
    "vendas", "atendimento ao cliente", "administrativo", "financeiro", "logística",
    "estoque", "marketing", "recursos humanos", "recrutamento", "comercial",
    "negociação", "gestão de equipes", "liderança", "pacote office",
    # Operacional
    "motorista", "auxiliar de produção", "operador de caixa", "eletricista",
    "manutenção", "segurança do trabalho", "enfermagem", "cozinha", "garçom",
]

# Cargos/funções comuns, usados para SUGERIR o "cargo desejado" a partir do texto
# do currículo (ex.: cargos mencionados no objetivo ou no histórico profissional).
# Coloque frases mais específicas primeiro (ex.: "auxiliar de estoque" antes de
# apenas "estoque") para que a sugestão fique mais precisa.
CARGOS_COMUNS = [
    "auxiliar de estoque", "auxiliar de logística", "auxiliar de manutenção",
    "auxiliar administrativo", "assistente administrativo", "assistente comercial",
    "auxiliar de produção", "auxiliar de serviços gerais", "operador de caixa",
    "operador de empilhadeira", "técnico de manutenção", "técnico de ti",
    "técnico de suporte", "analista de suporte", "analista administrativo",
    "analista de logística", "analista de dados", "desenvolvedor", "programador",
    "vendedor", "representante comercial", "consultor de vendas", "motorista",
    "entregador", "eletricista", "recepcionista", "atendente", "garçom",
    "cozinheiro", "auxiliar de cozinha", "enfermeiro", "técnico de enfermagem",
    "porteiro", "vigilante", "segurança", "jovem aprendiz", "estagiário",
    "gerente de loja", "supervisor", "coordenador", "engenheiro",
]


# Sites que o script tentará consultar. Ative/desative conforme desejar.
# Jooble REST API: o plano gratuito documenta até 100 requisições/dia por chave.
# Cada página consome uma requisição. Com 3 termos e 3 páginas, uma execução
# normal usa no máximo 9 chamadas (menos quando totalCount indicar fim).
JOOBLE_RESULTADOS_POR_PAGINA = 30  # tamanho padrão escolhido para cada página
JOOBLE_MAX_PAGINAS_POR_TERMO = 3  # 3 páginas x 30 = até 90 resultados por termo

# VagasRio: se a pesquisa nativa WordPress vier vazia/sem cartões, tenta a API
# pública padrão do WordPress (/wp-json/wp/v2/posts). Se o site a desativar, o
# diagnóstico registra o status e a coleta segue sem tentar contornar bloqueios.
VAGASRIO_USAR_REST_FALLBACK = True

SITES_ATIVOS = {
    # LinkedIn e Indeed ficam desativados por padrão: ambos proíbem coleta
    # automatizada sem autorização expressa. Os links manuais são exibidos no
    # terminal. Só ative se tiver autorização escrita do portal.
    "linkedin": False,
    "indeed": False,
    "vagas_com": True,
    "infojobs": True,
    "empregare": True,
    "empregando_brasil": True,
    "gupy": True,  # API JSON pública do portal; experimental e monitorada
    "jooble": True,  # requer JOOBLE_API_KEY no .env
    "riovagas": True,
    "rioemprega": True,
    "rioempregos": True,
    "vagasrio": True,
}

# Nota mínima (0-100) para uma vaga aparecer nos resultados finais (terminal e
# Excel). Vagas abaixo desse valor são descartadas para reduzir ruído. Pode ser
# sobrescrito na linha de comando com --nota-minima.
NOTA_MINIMA_PADRAO = 25

# UF (estado) alvo deste script. Serve para descartar automaticamente vagas de
# outros estados quando o site/scraper informa a cidade com UF (ex.: "São Paulo
# / SP" é descartado se UF_ALVO = "RJ"). Vagas sem UF identificável e vagas remotas
# não são descartadas por esse filtro (não dá para confirmar que são de outro estado).
UF_ALVO = "RJ"


# ---------------------------------------------------------------------------
# IA (Gemini / Claude)
# ---------------------------------------------------------------------------

# Modelo padrão que oferece o melhor equilíbrio entre capacidade e acesso no
# nível gratuito. Para usar o modelo de raciocínio topo de linha (pago), defina
# GEMINI_MODEL=gemini-4-argon,gemini-3.8-flash no .env. O código tenta o modelo
# mais forte e cai para Flash se o projeto não tiver acesso. Não ativa cobrança
# paga sem a escolha explícita do usuário.
GEMINI_MODELOS = [
    "gemini-3.8-flash",
    "gemini-3.5-flash-lite",
]

# Modelo do Claude (usado só quando não há GEMINI_API_KEY). Pode ser trocado
# com CLAUDE_MODEL no .env.
CLAUDE_MODELO = "claude-sonnet-5-5"

# Nível de raciocínio: high melhora a leitura do currículo e a avaliação de
# requisitos conflitantes. Aumenta consumo/latência; modelos que não aceitarem
# este parâmetro são tentados novamente sem ele.
GEMINI_NIVEL_PENSAMENTO = "high"

# No Gemini, os tokens de raciocínio contam DENTRO do limite de saída. Esta folga
# é somada ao limite pedido em cada chamada para a resposta não ser cortada no
# meio (era a causa de erros "Unterminated string" e de mensagens vazias).
GEMINI_FOLGA_TOKENS = 4096

# Quantas vezes repetir uma chamada que falhou por motivo passageiro (limite de
# requisições, instabilidade do servidor, rede) antes de tentar outro modelo.
IA_TENTATIVAS_POR_MODELO = 3

# Maior espera (segundos) aceita ao receber "tente novamente em X segundos".
# Se o servidor pedir mais que isso, o script passa para o próximo modelo.
IA_ESPERA_MAXIMA_SEGUNDOS = 45

# O programa lembra qual modelo funcionou para a sua chave e começa direto por ele,
# em vez de testar o primeiro da lista, falhar e trocar a cada chamada. A lembrança
# fica neste arquivo (na pasta do projeto) e vale este número de dias; depois disso o
# programa volta a testar os modelos melhores da lista, para aproveitar se algum
# deles passar a funcionar na sua chave. Use 0 para nunca lembrar.
IA_LEMBRAR_MODELO_DIAS = 7
MODELO_PREFERIDO_ARQUIVO = ".achavagai_modelo.json"

# Quantas vagas (as melhores da pré-análise por texto) vão para a IA avaliar, e
# quantas vagas por chamada. Lotes menores = respostas mais confiáveis e, se um
# lote falhar, os outros continuam valendo.
IA_TOP_ANALISE = 30
IA_TAMANHO_LOTE = 10

# Pausa (segundos) entre uma chamada de IA e a seguinte, para respeitar o limite
# de requisições por minuto do plano gratuito.
PAUSA_ENTRE_CHAMADAS_IA = 1.0

# Tamanho máximo (caracteres) da descrição de cada vaga enviada para a IA.
DESCRICAO_MAX_CARACTERES_IA = 900

# Remove CPF, RG, telefone, e-mail, CEP, data de nascimento e número da casa do
# texto do currículo ANTES de enviar para a IA (o nome, a cidade e o bairro
# continuam, porque ajudam na análise). Desative só se tiver um bom motivo.
ANONIMIZAR_CURRICULO = True

# Na "análise profunda", só busca a descrição completa de vagas cuja descrição
# atual tenha menos caracteres que isto (as demais já estão boas).
DESCRICAO_MINIMA_CARACTERES = 400

# Sites cujas páginas de vaga NÃO são baixadas na análise profunda. O LinkedIn
# proíbe coleta automatizada e bloqueia com facilidade, então fica de fora. Ele
# continua sendo pesquisado na busca normal. Tire da lista por sua conta e risco.
HOSTS_SEM_ANALISE_PROFUNDA = ("linkedin.com",)

# Busca os sites ao mesmo tempo (um site por vez dentro de cada um, respeitando a
# pausa REQUEST_DELAY_SECONDS). Se algum scraper se comportar mal assim, ponha False.
BUSCA_PARALELA = True

# Descarta vagas cuja data de comparecimento, entrevista, inscrição ou prazo, escrita
# no título ou no começo da descrição (ex.: "Comparecer no dia 24/08"), já passou.
# Vários portais regionais deixam esse tipo de vaga no ar por meses.
FILTRAR_VAGAS_ENCERRADAS = True

# Descarta, antes da IA, vagas que exigem uma categoria de CNH que o seu currículo não
# informa (ex.: motorista de ônibus exige D, motorista de caminhão exige C). Só age se o
# currículo cita a sua categoria; sem isso, a IA e você decidem.
FILTRAR_POR_HABILITACAO = True

# Histórico local (vagas já vistas + notas da IA em cache). Fica na pasta do
# projeto. Notas em cache valem por este número de dias.
HISTORICO_ARQUIVO = ".achavagai_historico.json"
CACHE_VALIDADE_DIAS = 14
