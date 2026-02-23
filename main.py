# main.py
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters

# Importações dos seus módulos
from src.bot import start, botao_handler # 'start' e 'botao_handler' estão em src/bot.py
from src.cadastro import cadastro_handler # 'cadastro_handler' é o ConversationHandler do cadastro de membros
from src.eventos import mostrar_eventos, mostrar_detalhes_evento, confirmar_presenca, cancelar_presenca # Funções de eventos
from src.cadastro_evento import cadastro_evento_handler # O ConversationHandler para cadastro de eventos

import os

TOKEN = os.getenv("TELEGRAM_TOKEN")
app = ApplicationBuilder().token(TOKEN).build()

# Handler para o comando /start (para usuários já cadastrados ou para iniciar o fluxo principal)
app.add_handler(CommandHandler("start", start))

# Handler de Cadastro de Membros (ConversationHandler)
app.add_handler(cadastro_handler)

# Handler de Cadastro de Eventos (ConversationHandler)
# Note que o entry_point de cadastro_evento_handler é um CallbackQueryHandler para "cadastrar_evento"
app.add_handler(cadastro_evento_handler)

# Handlers de Eventos (botões de callback)
# Estes são os handlers que o botao_handler de src/bot.py chama diretamente
app.add_handler(CallbackQueryHandler(mostrar_eventos, pattern="^ver_eventos$"))
app.add_handler(CallbackQueryHandler(mostrar_detalhes_evento, pattern="^evento_"))
app.add_handler(CallbackQueryHandler(confirmar_presenca, pattern="^confirmar_"))
app.add_handler(CallbackQueryHandler(cancelar_presenca, pattern="^cancelar_"))

# Handler genérico para botões que não se encaixam nos padrões acima (chamado pelo botao_handler)
# Este deve ser o último CallbackQueryHandler para garantir que os mais específicos sejam processados primeiro
app.add_handler(CallbackQueryHandler(botao_handler))


print("Bot rodando...")
app.run_polling(allowed_updates=Update.ALL_TYPES)
