"""
Configurações gerais do AchaVagAI.
Ajuste as listas abaixo conforme sua região / área de atuação.
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
BAIRROS_RJ = [
    "Centro", "Copacabana", "Ipanema", "Leblon", "Botafogo", "Flamengo",
    "Tijuca", "Barra da Tijuca", "Jacarepaguá", "Bangu", "Campo Grande",
    "Gávea", "Recreio", "Méier", "Madureira", "Santa Cruz", "Sepetiba",
    "Belford Roxo",
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
SITES_ATIVOS = {
    "linkedin": True,
    "indeed": True,
    "vagas_com": True,
    "infojobs": True,
    "riovagas": True,
    "rioemprega": True,
    "rioempregos": True,
    "vagasrio": True,
}

# Nota mínima (0-100) para uma vaga aparecer nos resultados finais (terminal e
# Excel). Vagas abaixo desse valor são descartadas para reduzir ruído. Pode ser
# sobrescrito na linha de comando com --nota-minima.
NOTA_MINIMA_PADRAO = 25
