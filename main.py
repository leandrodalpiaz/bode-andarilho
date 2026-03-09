# main.py
# ============================================
# BODE ANDARILHO - PONTO DE ENTRADA PRINCIPAL
# ============================================
# 
# Este arquivo configura o webhook, registra todos os handlers
# e inicia o servidor. É o coração do bot.
# 
# A ORDEM DOS HANDLERS É FUNDAMENTAL:
# 1. ConversationHandlers
# 2. CommandHandler (/start)
# 3. Callbacks específicos
# 4. Handler da palavra "bode"
# 5. Handler genérico de botões (último)
# 
# ============================================

from __future__ import annotations

import os
import asyncio
import logging
import signal
from datetime import datetime
from typing import Optional

from starlette.applications import Starlette
from starlette.routing import Route
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response

from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ChatMemberHandler,
    MessageHandler,
    CommandHandler,
    filters,
)

# ============================================
# IMPORTAÇÕES DOS MÓDULOS
# ============================================

# Cadastro de membros
from src.cadastro import cadastro_handler, cadastro_start

# Menus e navegação principal
from src.bot import botao_handler, menu_principal_teclado, start

# Eventos (visualização, confirmação, etc.)
from src.eventos import (
    mostrar_eventos,
    mostrar_detalhes_evento,
    cancelar_presenca,
    ver_confirmados,
    fechar_mensagem,
    minhas_confirmacoes,
    minhas_confirmacoes_futuro,
    minhas_confirmacoes_historico,
    mostrar_eventos_por_data,
    mostrar_eventos_por_grau,
    detalhes_confirmado,
    detalhes_historico,
    confirmacao_presenca_handler,
    mostrar_calendario,
    calendario_atual,
)

# Cadastro de eventos (com integração com lojas)
from src.cadastro_evento import cadastro_evento_handler

# Ações administrativas
from src.admin_acoes import (
    promover_handler,
    rebaixar_handler,
    editar_membro_handler,
    ver_todos_membros,
    menu_notificacoes,
    notificacoes_ativar,
    notificacoes_desativar,
    exibir_menu_admin,
)

# Edição do próprio perfil
from src.editar_perfil import editar_perfil_handler

# Área do secretário
from src.eventos_secretario import (
    editar_evento_secretario_handler,
    meus_eventos,
    menu_gerenciar_evento,
    confirmar_cancelamento,
    executar_cancelamento,
    resumo_confirmados,
    copiar_lista_confirmados,
    ver_confirmados_secretario,
    visualizar_confirmados,
    listar_eventos_cancelados,
    confirmar_refazer_evento,
    executar_refazer_evento,
    exibir_menu_secretario,
)

# Gerenciamento de lojas (com exclusão)
from src.lojas import (
    cadastro_loja_handler,
    menu_lojas,
    listar_lojas_handler,
    excluir_loja_menu,
    confirmar_exclusao_loja,
    executar_exclusao_loja,
)

# Utilitários
from src.sheets import buscar_membro
from src.permissoes import get_nivel

# ============================================
# CONFIGURAÇÃO INICIAL
# ============================================

print("INICIANDO BOT - BODE ANDARILHO")

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
    """Garante que uma variável de ambiente obrigatória existe."""
    if not value:
        raise RuntimeError(f"Variável de ambiente {name} não definida.")
    return value


def _join_url(base: str, path: str) -> str:
    """Concatena base URL com path de forma segura."""
    base = base.rstrip("/")
    path = path if path.startswith("/") else f"/{path}"
    return f"{base}{path}"


# ============================================
# HANDLERS DE GRUPO
# ============================================

async def bode_grupo_handler(update: Update, context):
    """
    Captura a palavra 'bode' em grupos e redireciona para o privado.
    - Se cadastrado: envia/edita menu no privado
    - Se não cadastrado: inicia cadastro no privado
    """
    if update.effective_chat.type not in ("group", "supergroup"):
        return

    user_id = update.effective_user.id
    membro = buscar_membro(user_id)

    if membro:
        from src.bot import criar_estrutura_inicial
        await criar_estrutura_inicial(context, user_id, membro)
    else:
        # Enviar mensagem no privado para iniciar cadastro
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    "🐐 *Bode Andarilho*\n\n"
                    "Bem-vindo! Você ainda não está cadastrado.\n"
                    "Vamos começar seu cadastro?\n\n"
                    "Envie /start para prosseguir."
                ),
                parse_mode="Markdown"
            )
        except Exception as e:
            print(f"Erro ao enviar mensagem no privado para {user_id}: {e}")
            # Fallback: responde no grupo
            if update.message:
                await update.message.reply_text(
                    "📩 Não consegui enviar mensagem no privado. Verifique se você iniciou uma conversa comigo primeiro."
                )


async def mensagem_grupo_handler(update: Update, context):
    """Handler para mensagens genéricas em grupos."""
    try:
        if not update.message:
            return

        chat = update.effective_chat
        if not chat or chat.type not in ("group", "supergroup"):
            return

        text = (update.message.text or "").strip().lower()

        if text in ("/start", "/cadastro"):
            await update.message.reply_text(
                "📩 Use o bot no privado para cadastro e menus."
            )
    except Exception as e:
        logger.warning("Erro em mensagem_grupo_handler: %s", e, exc_info=True)


async def novo_membro_grupo_handler(update: Update, context):
    """
    Handler para quando um novo membro entra no grupo.
    Envia mensagem de boas-vindas no grupo orientando a usar 'bode'.
    """
    try:
        if not update.chat_member:
            return

        chat_member = update.chat_member
        if chat_member.new_chat_member.status not in ("member", "administrator", "creator"):
            return  # Não é entrada

        user = chat_member.new_chat_member.user
        if user.is_bot:
            return  # Ignorar bots

        chat = update.effective_chat
        if chat.type not in ("group", "supergroup"):
            return

        # Enviar mensagem de boas-vindas no grupo
        nome = user.first_name or "irmão"
        await context.bot.send_message(
            chat_id=chat.id,
            text=(
                f"Salve, {nome}! 🐐\n\n"
                "Bem-vindo ao grupo do Bode Andarilho.\n"
                "Para acessar o menu e confirmar presenças, digite *bode* no grupo."
            ),
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.warning("Erro em novo_membro_grupo_handler: %s", e, exc_info=True)


# ============================================
# REGISTRO DE HANDLERS
# ============================================

def register_handlers(app: Application) -> None:
    """Registra todos os handlers na ordem correta."""

    # ===== 1. CONVERSATION HANDLERS =====
    app.add_handler(cadastro_handler)
    app.add_handler(confirmacao_presenca_handler)
    app.add_handler(cadastro_evento_handler)
    app.add_handler(promover_handler)
    app.add_handler(rebaixar_handler)
    app.add_handler(editar_membro_handler)
    app.add_handler(editar_perfil_handler)
    app.add_handler(editar_evento_secretario_handler)
    app.add_handler(cadastro_loja_handler)

    # ===== 2. COMMAND HANDLERS =====
    app.add_handler(CommandHandler("start", start))
    
    async def ping(update: Update, context):
        if update.message:
            await update.message.reply_text("OK")
    app.add_handler(CommandHandler("ping", ping))

    # ===== 3. CALLBACKS ESPECÍFICOS DE EVENTOS =====
    app.add_handler(CallbackQueryHandler(
        mostrar_eventos, pattern=r"^(ver_eventos|mostrar_eventos|eventos|voltar_eventos)$"
    ))
    app.add_handler(CallbackQueryHandler(
        mostrar_eventos_por_data, pattern=r"^data\|"
    ))
    app.add_handler(CallbackQueryHandler(
        mostrar_eventos_por_grau, pattern=r"^grau\|"
    ))
    app.add_handler(CallbackQueryHandler(
        mostrar_detalhes_evento, pattern=r"^evento\|"
    ))
    app.add_handler(CallbackQueryHandler(
        mostrar_calendario, pattern=r"^calendario\|"
    ))
    app.add_handler(CallbackQueryHandler(
        calendario_atual, pattern=r"^calendario_atual$"
    ))

    # ===== 4. CALLBACKS DE CONFIRMAÇÕES =====
    app.add_handler(CallbackQueryHandler(
        minhas_confirmacoes, pattern=r"^minhas_confirmacoes$"
    ))
    app.add_handler(CallbackQueryHandler(
        minhas_confirmacoes_futuro, pattern=r"^minhas_confirmacoes_futuro$"
    ))
    app.add_handler(CallbackQueryHandler(
        minhas_confirmacoes_historico, pattern=r"^minhas_confirmacoes_historico$"
    ))
    app.add_handler(CallbackQueryHandler(
        detalhes_confirmado, pattern=r"^detalhes_confirmado\|"
    ))
    app.add_handler(CallbackQueryHandler(
        detalhes_historico, pattern=r"^detalhes_historico\|"
    ))

    # ===== 5. CALLBACKS DE AÇÕES EM EVENTOS =====
    app.add_handler(CallbackQueryHandler(
        ver_confirmados, pattern=r"^ver_confirmados\|"
    ))
    app.add_handler(CallbackQueryHandler(
        cancelar_presenca, pattern=r"^confirma_cancelar\|"
    ))
    app.add_handler(CallbackQueryHandler(
        cancelar_presenca, pattern=r"^cancelar\|"
    ))
    # Handler para fechar a lista de confirmados
    app.add_handler(CallbackQueryHandler(
        fechar_mensagem, pattern=r"^fechar_mensagem$"
    ))

    # ===== 6. CALLBACKS DA ÁREA DO SECRETÁRIO =====
    app.add_handler(CallbackQueryHandler(
        meus_eventos, pattern=r"^meus_eventos$"
    ))
    app.add_handler(CallbackQueryHandler(
        ver_confirmados_secretario, pattern=r"^ver_confirmados_secretario$"
    ))
    app.add_handler(CallbackQueryHandler(
        visualizar_confirmados, pattern=r"^visualizar_confirmados\|"
    ))
    app.add_handler(CallbackQueryHandler(
        menu_gerenciar_evento, pattern=r"^gerenciar_evento\|"
    ))
    app.add_handler(CallbackQueryHandler(
        confirmar_cancelamento, pattern=r"^confirmar_cancelamento\|"
    ))
    app.add_handler(CallbackQueryHandler(
        executar_cancelamento, pattern=r"^cancelar_evento\|"
    ))
    app.add_handler(CallbackQueryHandler(
        resumo_confirmados, pattern=r"^resumo_evento\|"
    ))
    app.add_handler(CallbackQueryHandler(
        copiar_lista_confirmados, pattern=r"^copiar_lista\|"
    ))
    app.add_handler(CallbackQueryHandler(
        listar_eventos_cancelados, pattern=r"^listar_eventos_cancelados$"
    ))
    app.add_handler(CallbackQueryHandler(
        confirmar_refazer_evento, pattern=r"^confirmar_refazer\|"
    ))
    app.add_handler(CallbackQueryHandler(
        executar_refazer_evento, pattern=r"^executar_refazer\|"
    ))

    # ===== 7. CALLBACKS ADMINISTRATIVOS =====
    app.add_handler(CallbackQueryHandler(
        ver_todos_membros, pattern=r"^admin_ver_membros$"
    ))
    app.add_handler(CallbackQueryHandler(
        menu_notificacoes, pattern=r"^menu_notificacoes$"
    ))
    app.add_handler(CallbackQueryHandler(
        notificacoes_ativar, pattern=r"^notificacoes_ativar$"
    ))
    app.add_handler(CallbackQueryHandler(
        notificacoes_desativar, pattern=r"^notificacoes_desativar$"
    ))

    # ===== 8. CALLBACKS DE LOJAS =====
    app.add_handler(CallbackQueryHandler(menu_lojas, pattern=r"^menu_lojas$"))
    app.add_handler(CallbackQueryHandler(listar_lojas_handler, pattern=r"^loja_listar$"))
    # Handlers para exclusão de lojas (adicionados)
    app.add_handler(CallbackQueryHandler(excluir_loja_menu, pattern=r"^loja_excluir_menu$"))
    app.add_handler(CallbackQueryHandler(confirmar_exclusao_loja, pattern=r"^excluir_loja_\d+$"))
    app.add_handler(CallbackQueryHandler(executar_exclusao_loja, pattern=r"^excluir_loja_confirmar$"))

    # ===== 8. HANDLER PARA NOVOS MEMBROS NO GRUPO =====
    app.add_handler(ChatMemberHandler(novo_membro_grupo_handler))

    # ===== 9. HANDLER DA PALAVRA "BODE" =====
    app.add_handler(
        MessageHandler(
            filters.Regex(r"^(?i:bode)[.!?]*$") & filters.ChatType.GROUPS,
            bode_grupo_handler
        )
    )

    # ===== 10. HANDLER GENÉRICO DE BOTÕES (CATCH-ALL) =====
    app.add_handler(CallbackQueryHandler(botao_handler))

    # ===== 11. HANDLERS DE MENSAGENS EM GRUPO =====
    app.add_handler(MessageHandler(
        filters.ChatType.GROUPS & filters.TEXT & ~filters.COMMAND,
        mensagem_grupo_handler
    ))
    app.add_handler(MessageHandler(
        filters.ChatType.GROUPS & filters.COMMAND,
        mensagem_grupo_handler
    ))


# ============================================
# CONFIGURAÇÃO DO WEBHOOK E SERVIDOR
# ============================================

async def shutdown(server, telegram_app: Application):
    """Encerramento gracioso do servidor e do bot."""
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
            await telegram_app.shutdown()
        except Exception:
            pass

        logger.info("Shutdown concluído.")
    except Exception as e:
        logger.error("Erro no shutdown: %s", e, exc_info=True)


async def main():
    """Função principal que inicia o bot e o servidor webhook."""
    
    token = _require_env("TELEGRAM_TOKEN", TOKEN)
    render_url = _require_env("RENDER_EXTERNAL_URL", RENDER_URL)

    webhook_url = _join_url(render_url, WEBHOOK_PATH)

    logger.info("TOKEN carregado: %s", "SIM" if token else "NAO")
    logger.info("RENDER_URL: %s", render_url)
    logger.info("PORT: %s", PORT)
    logger.info("WEBHOOK_URL: %s", webhook_url)

    telegram_app = Application.builder().token(token).build()
    register_handlers(telegram_app)

    await telegram_app.initialize()
    await telegram_app.start()

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
        """Endpoint que recebe as atualizações do Telegram."""
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

    from src.scheduler import iniciar_scheduler
    await iniciar_scheduler(telegram_app)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(
                sig, 
                lambda s=sig: asyncio.create_task(shutdown(server, telegram_app))
            )
        except NotImplementedError:
            pass

    print(f"Servidor ouvindo em 0.0.0.0:{PORT}")
    await server.serve()


# ============================================
# PONTO DE ENTRADA
# ============================================
if __name__ == "__main__":
    asyncio.run(main())
