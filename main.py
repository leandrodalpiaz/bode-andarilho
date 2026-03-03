# main.py
# ============================================
# VERSAO FINAL - BODE ANDARILHO (RENDER) - REESCRITA
# ============================================
from __future__ import annotations

import os
import asyncio
import logging
import signal
from typing import Optional

from starlette.applications import Starlette
from starlette.routing import Route
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response

from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    MessageHandler,
    CommandHandler,
    filters,
)

from src.cadastro import cadastro_handler
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
)
from src.cadastro_evento import cadastro_evento_handler
from src.admin_acoes import (
    promover_handler,
    rebaixar_handler,
    editar_membro_handler,
)
from src.editar_perfil import editar_perfil_handler
from src.eventos_secretario import (
    editar_evento_secretario_handler,
    meus_eventos,
    menu_gerenciar_evento,
    confirmar_cancelamento,
    executar_cancelamento,
)

print("INICIANDO BOT - VERSAO FINAL 2026-03-02 (MAIN REESCRITO)")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("TELEGRAM_TOKEN")
RENDER_URL = os.getenv("RENDER_EXTERNAL_URL")
PORT = int(os.getenv("PORT", "10000"))

WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", "/telegram/webhook")


def _require_env(name: str, value: Optional[str]) -> str:
    if not value:
        raise RuntimeError(f"Variável de ambiente {name} não definida.")
    return value


def _join_url(base: str, path: str) -> str:
    base = base.rstrip("/")
    path = path if path.startswith("/") else f"/{path}"
    return f"{base}{path}"


async def shutdown(server, telegram_app: Application):
    """
    Encerramento gracioso:
    - para o server
    - para o telegram app (PTB)
    """
    try:
        logger.info("Shutdown iniciado...")
        try:
            server.should_exit = True
        except Exception:
            pass

        try:
            await telegram_app.bot.delete_webhook(drop_pending_updates=False)
        except Exception:
            pass

        try:
            await telegram_app.stop()
        except Exception:
            pass

        try:
            await telegram_app.shutdown()
        except Exception:
            pass

        logger.info("Shutdown concluído.")
    except Exception as e:
        logger.error("Erro no shutdown: %s", e, exc_info=True)


async def mensagem_grupo_handler(update: Update, context):
    """
    Handler simples para mensagens em grupo/supergrupo:
    - evita poluir o grupo
    - mantém o bot “quieto” a não ser que você decida o contrário
    """
    try:
        if not update.message:
            return

        chat = update.effective_chat
        if not chat:
            return

        # Só reage em grupo/supergrupo (não em privado)
        if chat.type not in ("group", "supergroup"):
            return

        text = (update.message.text or "").strip().lower()

        # Se quiser alguma ação no grupo, coloque aqui.
        # Por padrão, fica silencioso.
        if text in ("/start", "/cadastro"):
            await update.message.reply_text("📩 Use o bot no privado para cadastro e menus.")
    except Exception as e:
        logger.warning("Erro em mensagem_grupo_handler: %s", e, exc_info=True)


def register_handlers(app: Application) -> None:
    """
    Ordem é importante:
    1) ConversationHandlers (cadastro/confirmacao/evento/admin/secretario)
    2) CallbackQueryHandlers específicos (com pattern)
    3) CallbackQueryHandler genérico do menu (por último)
    4) MessageHandlers genéricos por fim
    """

    # 1) Fluxos conversacionais (prioridade alta)
    app.add_handler(cadastro_handler)
    app.add_handler(confirmacao_presenca_handler)
    app.add_handler(cadastro_evento_handler)

    app.add_handler(promover_handler)
    app.add_handler(rebaixar_handler)
    app.add_handler(editar_membro_handler)

    app.add_handler(editar_perfil_handler)

    app.add_handler(editar_evento_secretario_handler)

    # Se estes forem handlers (ConversationHandler/CallbackQueryHandler) no seu módulo, registramos:
    # (se forem funções simples, não atrapalha: app.add_handler espera Handler; então aqui assumimos que são Handlers)
    for h in (meus_eventos, menu_gerenciar_evento, confirmar_cancelamento, executar_cancelamento):
        try:
            app.add_handler(h)
        except Exception:
            # Se algum desses for apenas função (não Handler), ignore sem quebrar o boot.
            pass

    # 2) Callbacks específicos de eventos
    app.add_handler(CallbackQueryHandler(mostrar_eventos, pattern=r"^(ver_eventos|mostrar_eventos|eventos)$"))
    app.add_handler(CallbackQueryHandler(mostrar_eventos_por_data, pattern=r"^data\|"))
    app.add_handler(CallbackQueryHandler(mostrar_eventos_por_grau, pattern=r"^grau\|"))
    app.add_handler(CallbackQueryHandler(mostrar_detalhes_evento, pattern=r"^evento\|"))

    app.add_handler(CallbackQueryHandler(minhas_confirmacoes, pattern=r"^minhas_confirmacoes$"))
    app.add_handler(CallbackQueryHandler(detalhes_confirmado, pattern=r"^detalhes_confirmado\|"))

    app.add_handler(CallbackQueryHandler(ver_confirmados, pattern=r"^ver_confirmados\|"))
    app.add_handler(CallbackQueryHandler(cancelar_presenca, pattern=r"^cancelar\|"))
    app.add_handler(CallbackQueryHandler(fechar_mensagem, pattern=r"^fechar_mensagem$"))

    # 3) Menu principal / botões genéricos (catch-all) — sempre por último
    app.add_handler(CallbackQueryHandler(botao_handler))

    # 4) Mensagens (grupo e fallback)
    app.add_handler(MessageHandler(filters.ChatType.GROUPS & filters.TEXT & ~filters.COMMAND, mensagem_grupo_handler))
    app.add_handler(MessageHandler(filters.ChatType.GROUPS & filters.COMMAND, mensagem_grupo_handler))

    # Comando simples de saúde no Telegram (opcional)
    async def ping(update: Update, context):
        if update.message:
            await update.message.reply_text("OK")

    app.add_handler(CommandHandler("ping", ping))


async def main():
    token = _require_env("TELEGRAM_TOKEN", TOKEN)
    render_url = _require_env("RENDER_EXTERNAL_URL", RENDER_URL)

    webhook_url = _join_url(render_url, WEBHOOK_PATH)

    logger.info("TOKEN carregado: %s", "SIM" if token else "NAO")
    logger.info("RENDER_URL: %s", render_url)
    logger.info("PORT: %s", PORT)
    logger.info("WEBHOOK_PATH: %s", WEBHOOK_PATH)
    logger.info("WEBHOOK_URL: %s", webhook_url)

    telegram_app = Application.builder().token(token).build()
    register_handlers(telegram_app)

    # Inicializa o app PTB
    await telegram_app.initialize()
    await telegram_app.start()

    # Webhook (drop pendentes no deploy ajuda a evitar “replay” de clique antigo)
    await telegram_app.bot.delete_webhook(drop_pending_updates=True)
    await asyncio.sleep(0.5)
    await telegram_app.bot.set_webhook(
        url=webhook_url,
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
        max_connections=1,
    )

    info = await telegram_app.bot.get_webhook_info()
    logger.info("Webhook configurado: %s", info.url)
    logger.info("Pending updates: %s", info.pending_update_count)

    async def webhook(request: Request) -> Response:
        try:
            data = await request.json()
            update = Update.de_json(data, telegram_app.bot)
            await telegram_app.process_update(update)
            return Response(status_code=200)
        except Exception as e:
            logger.error("Erro no webhook: %s", e, exc_info=True)
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
        try:
            loop.add_signal_handler(sig, lambda s=sig: asyncio.create_task(shutdown(server, telegram_app)))
        except NotImplementedError:
            # Alguns ambientes não suportam add_signal_handler
            pass

    print(f"Servidor ouvindo em 0.0.0.0:{PORT}")
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())