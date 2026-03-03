# ============================================
# VERSAO FINAL - BODE ANDARILHO (RENDER) - CORRIGIDA
# ============================================
print("🚀 INICIANDO BOT - VERSAO FINAL 2026-03-02")

import os
import asyncio
import logging
import signal
import re
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response

from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ChatMemberHandler,
    ContextTypes,
)

from src.cadastro import cadastro_handler, cadastro_start
from src.bot import botao_handler
from src.eventos import (
    mostrar_eventos,
    mostrar_detalhes_evento,
    cancelar_presenca,
    ver_confirmados,
    fechar_mensagem,
    minhas_confirmacoes,
    mostrar_eventos_por_data,
    mostrar_eventos_por_grau,
    detalhes_confirmado,
    confirmacao_presenca_handler,
    iniciar_confirmacao_presenca,
)
from src.cadastro_evento import cadastro_evento_handler
from src.admin_acoes import (
    promover_handler,
    rebaixar_handler,
    # ver_todos_membros REMOVIDO - função não existe
    editar_membro,
)
from src.editar_perfil import editar_perfil_handler
from src.eventos_secretario import (
    editar_evento_secretario_handler,
    meus_eventos,
    menu_gerenciar_evento,
    confirmar_cancelamento,
    executar_cancelamento,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("TELEGRAM_TOKEN")
RENDER_URL = os.getenv("RENDER_EXTERNAL_URL")
PORT = int(os.getenv("PORT", 10000))

print(f"🔧 TOKEN carregado: {'SIM' if TOKEN else 'NÃO'}")
print(f"🔧 RENDER_URL: {RENDER_URL}")
print(f"🔧 PORT: {PORT}")


async def mensagem_grupo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Responde a mensagens em grupo (exceto 'bode')."""
    if update.effective_chat.type in ("group", "supergroup"):
        await update.message.reply_text(
            "Olá! Para interagir comigo, por favor use os botões nas mensagens de evento "
            "ou envie /start no meu chat privado. No grupo, apenas publico eventos e lembretes. 🐐"
        )


async def bot_adicionado_grupo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Boas-vindas quando o bot é adicionado a um grupo."""
    if update.my_chat_member and update.my_chat_member.new_chat_member.status == "member":
        await update.effective_chat.send_message(
            "Olá, irmãos! Sou o Bode Andarilho, o bot de agenda de visitas.\n\n"
            "Para interagir comigo, usem os botões nas mensagens de evento ou enviem /start no meu chat privado. "
            "No grupo, apenas publicarei eventos e lembretes. 🐐"
        )


def is_bode_message(message_text: str) -> bool:
    if not message_text:
        return False
    cleaned = re.sub(r"[.!?]+", "", message_text.strip()).lower()
    return cleaned == "bode"


async def bode_grupo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Quando o usuário envia 'bode' em grupo."""
    if update.effective_chat.type not in ("group", "supergroup"):
        return
    logger.info(
        "bode_grupo_handler: user=%s text=%r",
        update.effective_user.id,
        update.message.text if update.message else None,
    )
    await cadastro_start(update, context)


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("❌ Exceção não tratada: %s", context.error, exc_info=context.error)


async def main():
    print("⚙️ Criando aplicação Telegram...")

    telegram_app = Application.builder().token(TOKEN).updater(None).build()
    await telegram_app.initialize()
    await telegram_app.start()

    telegram_app.add_error_handler(error_handler)

    # ✅ ConversationHandlers primeiro (NUNCA mexer na ordem)
    telegram_app.add_handler(cadastro_handler)
    telegram_app.add_handler(cadastro_evento_handler)
    telegram_app.add_handler(confirmacao_presenca_handler)
    telegram_app.add_handler(promover_handler)
    telegram_app.add_handler(rebaixar_handler)
    telegram_app.add_handler(editar_perfil_handler)
    telegram_app.add_handler(editar_evento_secretario_handler)

    # ✅ "bode" no grupo (ponte)
    class BodeGrupoFilter(filters.MessageFilter):
        def filter(self, message):
            if message.chat.type not in ("group", "supergroup"):
                return False
            return is_bode_message(message.text)

    telegram_app.add_handler(MessageHandler(filters.TEXT & BodeGrupoFilter(), bode_grupo_handler))

    # ✅ Callbacks específicos (ordem importante - específicos primeiro)
    telegram_app.add_handler(CallbackQueryHandler(mostrar_eventos, pattern="^ver_eventos$"))
    telegram_app.add_handler(CallbackQueryHandler(mostrar_eventos_por_data, pattern=r"^data\|"))
    telegram_app.add_handler(CallbackQueryHandler(mostrar_eventos_por_grau, pattern=r"^grau\|"))
    telegram_app.add_handler(CallbackQueryHandler(mostrar_detalhes_evento, pattern=r"^evento\|"))
    telegram_app.add_handler(CallbackQueryHandler(ver_confirmados, pattern=r"^ver_confirmados\|"))
    telegram_app.add_handler(CallbackQueryHandler(iniciar_confirmacao_presenca, pattern=r"^confirmar\|"))
    telegram_app.add_handler(CallbackQueryHandler(cancelar_presenca, pattern=r"^cancelar\|"))
    telegram_app.add_handler(CallbackQueryHandler(cancelar_presenca, pattern=r"^confirma_cancelar\|"))
    telegram_app.add_handler(CallbackQueryHandler(fechar_mensagem, pattern="^fechar_mensagem$"))
    telegram_app.add_handler(CallbackQueryHandler(minhas_confirmacoes, pattern="^minhas_confirmacoes$"))
    telegram_app.add_handler(CallbackQueryHandler(detalhes_confirmado, pattern=r"^detalhes_confirmado\|"))
    
    # 🔥 NOVOS HANDLERS PARA ADMIN/SECRETÁRIO
    telegram_app.add_handler(CallbackQueryHandler(meus_eventos, pattern=r"^meus_eventos$"))
    telegram_app.add_handler(CallbackQueryHandler(editar_membro, pattern=r"^admin_editar_membro$"))
    telegram_app.add_handler(CallbackQueryHandler(menu_gerenciar_evento, pattern=r"^gerenciar_evento\|"))
    telegram_app.add_handler(CallbackQueryHandler(confirmar_cancelamento, pattern=r"^confirmar_cancelamento\|"))
    telegram_app.add_handler(CallbackQueryHandler(executar_cancelamento, pattern=r"^cancelar_evento\|"))

    # ✅ Botões “de menu” (genérico - deve vir por último)
    telegram_app.add_handler(
        CallbackQueryHandler(botao_handler, pattern=r"^(menu_principal|meu_cadastro|area_secretario|area_admin)$")
    )

    # Grupo
    telegram_app.add_handler(ChatMemberHandler(bot_adicionado_grupo, ChatMemberHandler.MY_CHAT_MEMBER))
    telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, mensagem_grupo_handler))

    # Webhook
    if not RENDER_URL:
        logger.error("RENDER_EXTERNAL_URL não definida!")
        return

    WEBHOOK_PATH = "/webhook_bode_2026"
    webhook_url = f"{RENDER_URL}{WEBHOOK_PATH}"
    print(f"🔗 URL do webhook: {webhook_url}")

    await telegram_app.bot.delete_webhook(drop_pending_updates=True)
    await asyncio.sleep(1)
    await telegram_app.bot.set_webhook(
        url=webhook_url,
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
        max_connections=1,
    )

    webhook_info = await telegram_app.bot.get_webhook_info()
    logger.info("✅ Webhook configurado: %s", webhook_info.url)
    logger.info("📊 Pending updates: %s", webhook_info.pending_update_count)

    async def webhook(request: Request) -> Response:
        try:
            data = await request.json()
            update = Update.de_json(data, telegram_app.bot)
            await telegram_app.process_update(update)
            return Response(status_code=200)
        except Exception as e:
            logger.error("❌ Erro no webhook: %s", e, exc_info=True)
            return Response(status_code=500)

    async def health(request: Request) -> PlainTextResponse:
        return PlainTextResponse("OK")

    async def root(request: Request) -> PlainTextResponse:
        return PlainTextResponse("Bode Andarilho Bot - Online")

    starlette_app = Starlette(
        routes=[
            Route("/", root, methods=["GET"]),
            Route("/health", health, methods=["GET"]),
            Route(WEBHOOK_PATH, webhook, methods=["POST"]),
        ]
    )

    import uvicorn

    config = uvicorn.Config(
        starlette_app,
        host="0.0.0.0",
        port=PORT,
        log_level="info",
        timeout_keep_alive=60,
    )
    server = uvicorn.Server(config)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(shutdown(server, telegram_app)))

    print(f"✅ Servidor ouvindo em 0.0.0.0:{PORT}")
    await server.serve()


async def shutdown(server, telegram_app):
    print("🛑 Desligando servidor...")
    server.should_exit = True
    await asyncio.sleep(2)
    try:
        await telegram_app.stop()
        await telegram_app.shutdown()
    except Exception as e:
        logger.error("Erro ao parar aplicação: %s", e)
    print("👋 Bot finalizado com sucesso.")


if __name__ == "__main__":
    asyncio.run(main())