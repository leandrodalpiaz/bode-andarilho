# src/messages.py
# ============================================
# CONSTANTES DE MENSAGENS DO BOT
# ============================================

# Boas-vindas e cadastro
BOAS_VINDAS = (
    "Salve, irmão! 🐐\n\n"
    "Bem-vindo ao *Bode Andarilho*, o bot de confirmação de presenças para eventos maçônicos.\n\n"
    "Antes de começar, preciso de alguns dados seus. Não se preocupe, é rápido!"
)

BOAS_VINDAS_RETORNO = (
    "Salve, irmão {nome}! 🐐\n\n"
    "Que bom ter você de volta. O que deseja fazer?"
)

MENU_PRINCIPAL = "Escolha uma opção abaixo:"

# Cadastro
CADASTRO_CONCLUIDO = "✅ *Cadastro realizado com sucesso!*\n\nUse /start para acessar o menu principal."
CADASTRO_CANCELADO = "Cadastro cancelado. Você pode iniciar novamente com /start."

# Eventos
EVENTO_CADASTRADO = "✅ Evento cadastrado e publicado no grupo."
EVENTO_CANCELADO = "✅ Evento cancelado com sucesso.\nTodas as confirmações foram removidas."
EVENTO_NAO_ENCONTRADO = "Evento não encontrado ou não está mais ativo."
SEM_EVENTOS = "Não existem sessões disponíveis para este filtro no momento."

# Confirmações
PRESENCA_CONFIRMADA = "✅ Presença confirmada, irmão {nome}!"
PRESENCA_CANCELADA = "❌ Presença cancelada.\n\nSe mudar de ideia, basta confirmar novamente."
JA_CONFIRMOU = "Você já confirmou presença para este evento."
NAO_CONFIRMOU = "Não foi possível cancelar. Você não estava confirmado para este evento."

# Áreas restritas
ACESSO_NEGADO = "⛔ Você não tem permissão para acessar esta área."
APENAS_ADMIN = "Apenas administradores podem realizar esta operação."

# Erros
ERRO_GENERICO = "❌ Ocorreu um erro. Tente novamente mais tarde."
ERRO_DADOS_NAO_ENCONTRADOS = "Erro: dados não encontrados. Tente novamente."

# Lembretes (usado em lembretes.py)
LEMBRETE_TITULO = "🐐 *Lembrete de evento — Bode Andarilho*"
LEMBRETE_CORPO = (
    "Olá, irmão {nome}! Você confirmou presença no seguinte evento:\n\n"
    "📅 Data: {data}\n"
    "🏛️ Loja: {loja}\n"
    "🕐 Horário: {horario}\n"
    "📍 Local: {local}\n"
    "🔷 Grau mínimo: {grau}\n"
    "👔 Traje: {traje}\n"
    "🍽️ Ágape: {agape}\n\n"
    "Até amanhã! 🤝"
)