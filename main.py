# ============================================
# VERSAO FINAL - BODE ANDARILHO (RENDER) - CORRIGIDA
# ============================================
print("🚀 INICIANDO BOT - VERSAO FINAL 2026-02-26")

import os
import asyncio
import logging
import signal
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ConversationHandler, ChatMemberHandler,
    ContextTypes
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
from src.eventos_secretario import editar_evento_secretario_handler  # NOVO

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

print(f"🔧 TOKEN carregado: {'SIM' if TOKEN else 'NÃO'}")
print(f"🔧 RENDER_URL: {RENDER_URL}")
print(f"🔧 PORT: {PORT}")

# --- Handlers existentes ---
async def mensagem_grupo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type in ["group", "supergroup"]:
        await update.message.reply_text(
            "Olá! Para interagir comigo, por favor use os botões nas mensagens de evento "
            "ou envie /start no meu chat privado. No grupo, apenas publico eventos e lembretes. 🐐"
        )
        return

async def bot_adicionado_grupo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.my_chat_member.new_chat_member.status == "member":
        await update.effective_chat.send_message(
            "Olá, irmãos! Sou o Bode Andarilho, o bot de agenda de visitas.\n\n"
            "Para interagir comigo, usem os botões nas mensagens de evento ou enviem /start no meu chat privado. "
            "No grupo, apenas publicarei eventos e lembretes. Confirmações e outras ações devem ser feitas em privado. 🐐"
        )

# Handler de erro global
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(f"❌ Exceção não tratada: {context.error}", exc_info=context.error)

# --- Função principal ---
async def main():
    print("⚙️ Criando aplicação Telegram...")
    telegram_app = Application.builder().token(TOKEN).updater(None).build()
    print("✅ Aplicação criada com updater=None")

    # 🔥 INICIALIZAÇÃO OBRIGATÓRIA
    await telegram_app.initialize()
    print("✅ Application.initialize() executado")
    
    await telegram_app.start()
    print("✅ Application.start() executado")

    telegram_app.add_error_handler(error_handler)

    # --- Registro dos handlers ---
    telegram_app.add_handler(CommandHandler("start", start))
    telegram_app.add_handler(cadastro_handler)
    telegram_app.add_handler(cadastro_evento_handler)
    telegram_app.add_handler(confirmacao_presenca_handler)
    telegram_app.add_handler(promover_handler)
    telegram_app.add_handler(rebaixar_handler)
    telegram_app.add_handler(editar_perfil_handler)
    telegram_app.add_handler(editar_evento_secretario_handler)  # NOVO

    # Handlers de callback
    telegram_app.add_handler(CallbackQueryHandler(mostrar_eventos, pattern="^ver_eventos$"))
    telegram_app.add_handler(CallbackQueryHandler(mostrar_eventos_por_data, pattern="^data\\|"))
    telegram_app.add_handler(CallbackQueryHandler(mostrar_eventos_por_grau, pattern="^grau\\|"))
    telegram_app.add_handler(CallbackQueryHandler(mostrar_detalhes_evento, pattern="^evento\\|"))
    telegram_app.add_handler(CallbackQueryHandler(ver_confirmados, pattern="^ver_confirmados\\|"))
    telegram_app.add_handler(CallbackQueryHandler(cancelar_presenca, pattern="^cancelar\\|"))
    telegram_app.add_handler(CallbackQueryHandler(cancelar_presenca, pattern="^confirma_cancelar\\|"))
    telegram_app.add_handler(CallbackQueryHandler(fechar_mensagem, pattern="^fechar_mensagem$"))
    telegram_app.add_handler(CallbackQueryHandler(minhas_confirmacoes, pattern="^minhas_confirmacoes$"))
    telegram_app.add_handler(CallbackQueryHandler(botao_handler))
    telegram_app.add_handler(ChatMemberHandler(bot_adicionado_grupo, ChatMemberHandler.MY_CHAT_MEMBER))
    telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, mensagem_grupo_handler))

    # --- Configuração do Webhook ---
    if not RENDER_URL:
        logger.error("RENDER_EXTERNAL_URL não definida!")
        return

    WEBHOOK_PATH = "/webhook_bode_2026"
    webhook_url = f"{RENDER_URL}{WEBHOOK_PATH}"
    print(f"🔗 URL do webhook: {webhook_url}")

    # Limpeza e configuração
    await telegram_app.bot.delete_webhook(drop_pending_updates=True)
    await asyncio.sleep(1)
    await telegram_app.bot.set_webhook(
        url=webhook_url,
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
        max_connections=1
    )

    webhook_info = await telegram_app.bot.get_webhook_info()
    logger.info(f"✅ Webhook configurado: {webhook_info.url}")
    logger.info(f"📊 Pending updates: {webhook_info.pending_update_count}")

    # --- Servidor Starlette ---
    async def webhook(request: Request) -> Response:
        try:
            data = await request.json()
            update = Update.de_json(data, telegram_app.bot)
            await telegram_app.process_update(update)
            return Response(status_code=200)
        except Exception as e:
            logger.error(f"❌ Erro no webhook: {e}", exc_info=True)
            return Response(status_code=500)

    async def health(request: Request) -> PlainTextResponse:
        return PlainTextResponse("OK")

    async def root(request: Request) -> PlainTextResponse:
        return PlainTextResponse("Bode Andarilho Bot - Online")

    starlette_app = Starlette(routes=[
        Route("/", root, methods=["GET"]),
        Route("/health", health, methods=["GET"]),
        Route(WEBHOOK_PATH, webhook, methods=["POST"]),
    ])

    # Servidor
    import uvicorn

    config = uvicorn.Config(
        starlette_app,
        host="0.0.0.0",
        port=PORT,
        log_level="info",
        timeout_keep_alive=60
    )
    server = uvicorn.Server(config)

    # Tratamento de sinais
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(shutdown(server, telegram_app)))

    print(f"✅ Servidor ouvindo em 0.0.0.0:{PORT}")
    await server.serve()

async def shutdown(server, telegram_app):
    """Desligamento gracioso."""
    print("🛑 Desligando servidor...")
    server.should_exit = True
    
    # 🔥 Limpeza adequada
    await telegram_app.stop()
    await telegram_app.shutdown()
    await telegram_app.bot.delete_webhook(drop_pending_updates=True)
    
    print("👋 Bot finalizado com sucesso.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("👋 Bot finalizado manualmente.")
    except Exception as e:
        print(f"💥 Erro fatal: {e}")
        raise