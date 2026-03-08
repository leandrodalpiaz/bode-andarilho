# src/messages.py
# ============================================
# BODE ANDARILHO - CONSTANTES DE MENSAGENS
# ============================================
# 
# Este arquivo centraliza todas as mensagens textuais do bot
# para facilitar a manutenção e futuras traduções.
# 
# As mensagens são organizadas por categoria:
# - Boas-vindas e cadastro
# - Eventos e confirmações
# - Áreas restritas
# - Lembretes
# - Erros
# 
# ============================================

# ============================================
# BOAS-VINDAS E CADASTRO
# ============================================

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

CADASTRO_CONCLUIDO = "✅ *Cadastro realizado com sucesso!*\n\nUse /start para acessar o menu principal."
CADASTRO_CANCELADO = "Cadastro cancelado. Você pode iniciar novamente com /start."


# ============================================
# EVENTOS E CONFIRMAÇÕES
# ============================================

EVENTO_CADASTRADO = "✅ Evento cadastrado e publicado no grupo."
EVENTO_CANCELADO = "✅ Evento cancelado com sucesso.\nTodas as confirmações foram removidas."
EVENTO_NAO_ENCONTRADO = "Evento não encontrado ou não está mais ativo."
SEM_EVENTOS = "Não existem sessões disponíveis para este filtro no momento."

PRESENCA_CONFIRMADA = "✅ Presença confirmada, irmão {nome}!"
PRESENCA_CANCELADA = "❌ Presença cancelada.\n\nSe mudar de ideia, basta confirmar novamente."
JA_CONFIRMOU = "Você já confirmou presença para este evento."
NAO_CONFIRMOU = "Não foi possível cancelar. Você não estava confirmado para este evento."


# ============================================
# ÁREAS RESTRITAS
# ============================================

ACESSO_NEGADO = "⛔ Você não tem permissão para acessar esta área."
APENAS_ADMIN = "Apenas administradores podem realizar esta operação."
APENAS_SECRETARIO = "Apenas secretários e administradores podem acessar esta função."


# ============================================
# LEMBRETES
# ============================================

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

LEMBRETE_MEIO_DIA_TITULO = "🕛 *MEIO DIA EM PONTO!*"
LEMBRETE_MEIO_DIA_CORPO = (
    "Irmão {nome}, hoje tem sessão!\n\n"
    "🏛 Loja {loja}{numero}\n"
    "📍 {local}\n"
    "🕕 {horario}\n\n"
    "Até logo mais! 🤝"
)

LEMBRETE_SECRETARIO_TITULO = "📋 *ALERTA PARA SECRETÁRIO*"
LEMBRETE_SECRETARIO_CORPO = (
    "Olá, irmão {nome}! Você é o secretário responsável pelo seguinte evento:\n\n"
    "📅 Data: {data}\n"
    "🏛️ Loja: {loja}\n"
    "🕐 Horário: {horario}\n"
    "📍 Local: {local}\n"
    "🔷 Grau mínimo: {grau}\n"
    "👔 Traje: {traje}\n"
    "🍽️ Ágape: {agape}\n\n"
    "Confirmações até o momento: {num_confirmados}\n\n"
    "Prepare-se para a sessão! 🤝"
)

LEMBRETE_SECRETARIO_MEIO_DIA_TITULO = "🕛 *ALERTA SECRETÁRIO - MEIO DIA!*"
LEMBRETE_SECRETARIO_MEIO_DIA_CORPO = (
    "Irmão {nome}, hoje é o dia da sessão que você organiza!\n\n"
    "🏛 Loja {loja}{numero}\n"
    "📍 {local}\n"
    "🕕 {horario}\n\n"
    "Confirmações: {num_confirmados}\n\n"
    "Até logo mais! 🤝"
)


# ============================================
# NOTIFICAÇÕES
# ============================================

NOTIFICACAO_NOVA_CONFIRMACAO = (
    "📢 *NOVA CONFIRMAÇÃO*\n\n"
    "👤 *Irmão:* {nome}\n"
    "📅 *Evento:* {data} - {loja}\n"
    "🍽 *Ágape:* {agape}\n"
)


# ============================================
# ERROS
# ============================================

ERRO_GENERICO = "❌ Ocorreu um erro. Tente novamente mais tarde."
ERRO_DADOS_NAO_ENCONTRADOS = "Erro: dados não encontrados. Tente novamente."
ERRO_PERMISSAO = "⛔ Você não tem permissão para realizar esta operação."