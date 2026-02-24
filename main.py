# main.py
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ConversationHandler, ChatMemberHandler
)

# Importações dos módulos existentes
from src.bot import start, botao_handler
from src.cadastro import cadastro_handler
from src.eventos import (
    mostrar_eventos, mostrar_detalhes_evento, cancelar_presenca,
    confirmacao_presenca_handler, ver_confirmados, fechar_mensagem,
    minhas_confirmacoes, mostrar_eventos_por_data, mostrar_eventos_por_grau
)
from src.cadastro_evento import cadastro_evento_handler
from src.admin_acoes import promover_handler, rebaixar_handler

import os

TOKEN = os.getenv("TELEGRAM_TOKEN")
app = ApplicationBuilder().token(TOKEN).build()

# --- Handlers para interações no grupo ---
async def mensagem_grupo_handler(update: Update, context):
    """Responde a mensagens de texto enviadas em grupos."""
    if update.effective_chat.type in ["group", "supergroup"]:
        await update.message.reply_text(
            "Olá! Para interagir comigo, por favor use os botões nas mensagens de evento "
            "ou envie /start no meu chat privado. No grupo, apenas publico eventos e lembretes. 🐐"
        )
        return
    # Se for privado, a mensagem será ignorada aqui (outros handlers cuidam)

async def bot_adicionado_grupo(update: Update, context):
    """Mensagem de boas-vindas quando o bot é adicionado a um grupo."""
    if update.my_chat_member.new_chat_member.status == "member":
        await update.effective_chat.send_message(
            "Olá, irmãos! Sou o Bode Andarilho, o bot de agenda de visitas.\n\n"
            "Para interagir comigo, usem os botões nas mensagens de evento ou enviem /start no meu chat privado. "
            "No grupo, apenas publicarei eventos e lembretes. Confirmações e outras ações devem ser feitas em privado. 🐐"
        )

# --- Registro dos handlers ---
# Handlers de comandos
app.add_handler(CommandHandler("start", start))

# Handlers de conversação (devem vir antes dos handlers de callback simples)
app.add_handler(cadastro_handler)
app.add_handler(cadastro_evento_handler)
app.add_handler(confirmacao_presenca_handler)
app.add_handler(promover_handler)
app.add_handler(rebaixar_handler)

# Handlers de callback específicos (devem vir antes do genérico)
app.add_handler(CallbackQueryHandler(mostrar_eventos, pattern="^ver_eventos$"))
app.add_handler(CallbackQueryHandler(mostrar_eventos_por_data, pattern="^data_"))
app.add_handler(CallbackQueryHandler(mostrar_eventos_por_grau, pattern="^grau_"))
app.add_handler(CallbackQueryHandler(mostrar_detalhes_evento, pattern="^evento_"))
app.add_handler(CallbackQueryHandler(ver_confirmados, pattern="^ver_confirmados_"))
app.add_handler(CallbackQueryHandler(fechar_mensagem, pattern="^fechar_mensagem$"))
app.add_handler(CallbackQueryHandler(minhas_confirmacoes, pattern="^minhas_confirmacoes$"))
app.add_handler(CallbackQueryHandler(cancelar_presenca, pattern="^cancelar_"))

# Handler genérico para outros callbacks (deve vir por último)
app.add_handler(CallbackQueryHandler(botao_handler))

# Handler para quando o bot é adicionado a um grupo
app.add_handler(ChatMemberHandler(bot_adicionado_grupo, ChatMemberHandler.MY_CHAT_MEMBER))

# Handler para mensagens de texto em grupo (deve vir após todos os outros handlers de mensagem)
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, mensagem_grupo_handler))

print("Bot rodando...")
app.run_polling(allowed_updates=Update.ALL_TYPES)