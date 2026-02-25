# main.py
import os
import asyncio
import logging
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ConversationHandler, ChatMemberHandler
)

# Importações dos seus módulos
from src.bot import start, botao_handler
from src.cadastro import cadastro_handler
from src.eventos import (
    mostrar_eventos, mostrar_detalhes_evento, cancelar_presenca,
    confirmacao_presenca_handler, ver_confirmados, fechar_mensagem,
    minhas_confirmacoes, mostrar_eventos_por_data, mostrar_eventos_por_grau
)
from src.cadastro_evento import cadastro_evento_handler
from src.admin_acoes import promover_handler, rebaixar_handler
from src.editar_perfil import editar_perfil_handler

# Configuração de logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Variáveis de ambiente
TOKEN = os.getenv("TELEGRAM_TOKEN")
RENDER_URL = os.getenv("RENDER_EXTERNAL_URL")
PORT = int(os.getenv("PORT", 10000))

# --- Handlers existentes ---
async def mensagem_grupo_handler(update: Update, context):
    if update.effective_chat.type in ["group", "supergroup"]:
        await update.message.reply_text(
            "Olá! Para interagir comigo, por favor use os botões nas mensagens de evento "
            "ou envie /start no meu chat privado. No grupo, apenas publico eventos e lembretes. 🐐"
        )
        return

async def bot_adicionado_grupo(update: Update, context):
    if update.my_chat_member.new_chat_member.status == "member":
        await update.effective_chat.send_message(
            "Olá, irmãos! Sou o Bode Andarilho, o bot de agenda de visitas.\n\n"
            "Para interagir comigo, usem os botões nas mensagens de evento ou enviem /start no meu chat privado. "
            "No grupo, apenas publicarei eventos e lembretes. Confirmações e outras ações devem ser feitas em privado. 🐐"
        )

# --- Função principal ---
async def main():
    # Cria a aplicação do Telegram SEM polling
    telegram_app = Application.builder().token(TOKEN).updater(None).build()

    # --- Registro dos handlers ---
    telegram_app.add_handler(CommandHandler("start", start))
    telegram_app.add_handler(cadastro_handler)
    telegram_app.add_handler(cadastro_evento_handler)
    telegram_app.add_handler(confirmacao_presenca_handler)
    telegram_app.add_handler(promover_handler)
    telegram_app.add_handler(rebaixar_handler)
    telegram_app.add_handler(editar_perfil_handler)

    # Handlers de callback com pipe
    telegram_app.add_handler(CallbackQueryHandler(mostrar_eventos, pattern="^ver_eventos$"))
    telegram_app.add_handler(CallbackQueryHandler(mostrar_eventos_por_data, pattern="^data\\|"))
    telegram_app.add_handler(CallbackQueryHandler(mostrar_eventos_por_grau, pattern="^grau\\|"))
    telegram_app.add_handler(CallbackQueryHandler(mostrar_detalhes_evento, pattern="^evento\\|"))
    telegram_app.add_handler(CallbackQueryHandler(ver_confirmados, pattern="^ver_confirmados\\|"))
    telegram_app.add_handler(CallbackQueryHandler(cancelar_presenca, pattern="^cancelar\\|"))
    telegram_app.add_handler(CallbackQueryHandler(cancelar_presenca, pattern="^confirma_cancelar\\|"))
    telegram_app.add_handler(CallbackQueryHandler(fechar_mensagem, pattern="^fechar_mensagem$"))
    telegram_app.add_handler(CallbackQueryHandler(minhas_confirmacoes, pattern="^minhas_confirmacoes$"))

    # Handler genérico
    telegram_app.add_handler(CallbackQueryHandler(botao_handler))

    # Handlers de grupo
    telegram_app.add_handler(ChatMemberHandler(bot_adicionado_grupo, ChatMemberHandler.MY_CHAT_MEMBER))
    telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, mensagem_grupo_handler))

    # --- Configuração do Webhook (VERSÃO ROBUSTA) ---
    if not RENDER_URL:
        logger.error("RENDER_EXTERNAL_URL não definida! O webhook não funcionará.")
        return

    webhook_url = f"{RENDER_URL}/webhook"

    # 🔥 LIMPEZA FORÇADA
    logger.info("🧹 Removendo webhook antigo e limpando fila de atualizações...")
    await telegram_app.bot.delete_webhook(drop_pending_updates=True)
    await asyncio.sleep(2)

    # Configura o novo webhook
    logger.info(f"🔗 Configurando novo webhook para: {webhook_url}")
    await telegram_app.bot.set_webhook(
        url=webhook_url,
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True
    )

    # Verifica se o webhook foi configurado
    webhook_info = await telegram_app.bot.get_webhook_info()
    logger.info(f"✅ Webhook configurado: {webhook_info.url}")

    # --- Servidor Starlette ---
    async def webhook(request: Request) -> Response:
        try:
            data = await request.json()
            update = Update.de_json(data, telegram_app.bot)
            await telegram_app.process_update(update)
            return Response(status_code=200)
        except Exception as e:
            logger.error(f"❌ Erro no webhook: {e}")
            return Response(status_code=500)

    async def health(request: Request) -> PlainTextResponse:
        return PlainTextResponse(f"OK - Bot ativo - Webhook: {webhook_url}")

    starlette_app = Starlette(routes=[
        Route("/webhook", webhook, methods=["POST"]),
        Route("/health", health, methods=["GET"]),
    ])

    # Inicia o servidor
    import uvicorn
    config = uvicorn.Config(
        starlette_app,
        host="0.0.0.0",
        port=PORT,
        log_level="info"
    )
    server = uvicorn.Server(config)

    try:
        logger.info(f"🚀 Servidor iniciado na porta {PORT}")
        await server.serve()
    except KeyboardInterrupt:
        logger.info("🛑 Servidor interrompido manualmente")
    except Exception as e:
        logger.error(f"💥 Erro fatal no servidor: {e}")
        raise
    finally:
        logger.info("🧹 Limpando webhook antes de desligar...")
        await telegram_app.bot.delete_webhook()

if __name__ == "__main__":
    asyncio.run(main())