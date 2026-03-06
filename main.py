# main.py
# ============================================
# BODE ANDARILHO - PONTO DE ENTRADA PRINCIPAL
# ============================================
# Este arquivo configura o webhook, registra todos os handlers
# e inicia o servidor. É o coração do bot.
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

# ============================================
# IMPORTAÇÕES DOS MÓDULOS DO BOT
# ============================================

# Cadastro de membros
from src.cadastro import cadastro_handler, cadastro_start

# Menus e navegação principal
from src.bot import botao_handler, menu_principal_teclado

# Funcionalidades de eventos (visualização, confirmação, etc.)
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

# Ações administrativas (promover, rebaixar, editar membros, notificações)
from src.admin_acoes import (
    promover_handler,
    rebaixar_handler,
    editar_membro_handler,
    ver_todos_membros,
    menu_notificacoes,
    notificacoes_ativar,
    notificacoes_desativar,
)

# Edição do próprio perfil
from src.editar_perfil import editar_perfil_handler

# Funcionalidades específicas para secretários
from src.eventos_secretario import (
    editar_evento_secretario_handler,
    meus_eventos,
    menu_gerenciar_evento,
    confirmar_cancelamento,
    executar_cancelamento,
    resumo_confirmados,
    copiar_lista_confirmados,
)

# Gerenciamento de lojas (pré-cadastro)
from src.lojas import (
    cadastro_loja_handler,
    menu_lojas,
    listar_lojas_handler,
)

# Utilitários
from src.sheets import buscar_membro
from src.permissoes import get_nivel

# ============================================
# CONFIGURAÇÃO INICIAL
# ============================================

print("INICIANDO BOT - BODE ANDARILHO")

# Configuração de logging para monitoramento
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Variáveis de ambiente (configuradas no Render)
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
# FUNÇÃO AUXILIAR PARA ENVIAR MENU PRINCIPAL
# ============================================

async def enviar_menu_principal(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int, membro: dict):
    """
    Envia o menu principal para o usuário no privado.
    Se já existir um menu anterior, tenta editar; caso contrário, envia novo.
    """
    from src.bot import enviar_ou_editar_menu, menu_principal_teclado
    
    nivel = get_nivel(user_id)
    texto = f"🐐 *Bode Andarilho*\n\nBem-vindo de volta, irmão {membro.get('Nome', '')}!\n\nO que deseja fazer?"
    
    await enviar_ou_editar_menu(
        context,
        user_id,
        texto,
        menu_principal_teclado(nivel)
    )


# ============================================
# HANDLERS DE GRUPO E COMANDOS ESPECIAIS
# ============================================

async def bode_grupo_handler(update: Update, context):
    """
    Captura a palavra 'bode' em grupos e redireciona para o privado.
    - Se usuário cadastrado: envia/edita menu principal no privado
    - Se não cadastrado: orienta a fazer cadastro
    """
    if update.effective_chat.type not in ("group", "supergroup"):
        return

    user_id = update.effective_user.id
    membro = buscar_membro(user_id)

    if membro:
        # Usuário já cadastrado: envia menu principal (editando se possível)
        await enviar_menu_principal(update, context, user_id, membro)
    else:
        # Usuário não cadastrado: orienta a fazer cadastro no privado
        await cadastro_start(update, context)


async def mensagem_grupo_handler(update: Update, context):
    """
    Handler para mensagens genéricas em grupos.
    Mantém o bot silencioso para evitar poluição.
    """
    try:
        if not update.message:
            return

        chat = update.effective_chat
        if not chat or chat.type not in ("group", "supergroup"):
            return

        text = (update.message.text or "").strip().lower()

        # Apenas responde a comandos específicos
        if text in ("/start", "/cadastro"):
            await update.message.reply_text(
                "📩 Use o bot no privado para cadastro e menus."
            )
    except Exception as e:
        logger.warning("Erro em mensagem_grupo_handler: %s", e, exc_info=True)


# ============================================
# HANDLER PRINCIPAL DO COMANDO /start
# ============================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handler para comando /start.
    - Em grupo: orienta a usar o privado
    - Em privado: se cadastrado, mostra menu; se não, inicia cadastro
    """
    logger.info(
        "start chamado - chat_type=%s user_id=%s",
        getattr(update.effective_chat, "type", None),
        getattr(update.effective_user, "id", None),
    )

    # Se estiver em grupo, orienta a ir para o privado
    if update.effective_chat and update.effective_chat.type in ["group", "supergroup"]:
        await update.message.reply_text(
            "🔒 Para interagir comigo, fale no privado.\n\n"
            "Clique aqui: @BodeAndarilhoBot e envie /start"
        )
        return

    # Se já está em privado, prossegue normalmente
    telegram_id = update.effective_user.id
    membro = buscar_membro(telegram_id)

    if membro:
        await enviar_menu_principal(update, context, telegram_id, membro)
    else:
        await cadastro_start(update, context)


# ============================================
# REGISTRO DE TODOS OS HANDLERS
# ============================================
# A ORDEM É FUNDAMENTAL PARA O FUNCIONAMENTO CORRETO:
# 1. ConversationHandlers (prioridade máxima)
# 2. CommandHandler (/start)
# 3. Callbacks específicos (com padrões regex)
# 4. Handlers de mensagens em grupo
# 5. Callback genérico (catch-all, último)
# ============================================

def register_handlers(app: Application) -> None:
    """Registra todos os handlers na ordem correta."""

    # ===== 1. CONVERSATION HANDLERS =====
    # Fluxos que exigem múltiplas interações
    app.add_handler(cadastro_handler)              # Cadastro de membros
    app.add_handler(confirmacao_presenca_handler)  # Confirmação de presença
    app.add_handler(cadastro_evento_handler)       # Cadastro de eventos
    app.add_handler(promover_handler)              # Promoção de membros
    app.add_handler(rebaixar_handler)              # Rebaixamento de membros
    app.add_handler(editar_membro_handler)         # Edição de membros (admin)
    app.add_handler(editar_perfil_handler)         # Edição do próprio perfil
    app.add_handler(editar_evento_secretario_handler)  # Edição de eventos (secretário)
    app.add_handler(cadastro_loja_handler)         # Cadastro de lojas

    # ===== 2. COMMAND HANDLERS =====
    # Comandos simples como /start
    app.add_handler(CommandHandler("start", start))
    
    # Comando de saúde (opcional)
    async def ping(update: Update, context):
        if update.message:
            await update.message.reply_text("OK")
    app.add_handler(CommandHandler("ping", ping))

    # ===== 3. CALLBACKS ESPECÍFICOS DE EVENTOS =====
    # Navegação principal de eventos
    app.add_handler(CallbackQueryHandler(
        mostrar_eventos, pattern=r"^(ver_eventos|mostrar_eventos|eventos)$"
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
    
    # Calendário visual
    app.add_handler(CallbackQueryHandler(
        mostrar_calendario, pattern=r"^calendario\|"
    ))
    app.add_handler(CallbackQueryHandler(
        calendario_atual, pattern=r"^calendario_atual$"
    ))

    # ===== 4. CALLBACKS DE CONFIRMAÇÕES DO USUÁRIO =====
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
        cancelar_presenca, pattern=r"^cancelar\|"
    ))
    app.add_handler(CallbackQueryHandler(
        fechar_mensagem, pattern=r"^fechar_mensagem$"
    ))

    # ===== 6. CALLBACKS DA ÁREA DO SECRETÁRIO =====
    app.add_handler(CallbackQueryHandler(
        meus_eventos, pattern=r"^meus_eventos$"
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

    # ===== 7. CALLBACKS DA ÁREA ADMINISTRATIVA =====
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

    # ===== 8. CALLBACKS DE GERENCIAMENTO DE LOJAS =====
    app.add_handler(CallbackQueryHandler(
        menu_lojas, pattern=r"^menu_lojas$"
    ))
    app.add_handler(CallbackQueryHandler(
        listar_lojas_handler, pattern=r"^loja_listar$"
    ))

    # ===== 9. HANDLER PARA PALAVRA "BODE" EM GRUPOS =====
    app.add_handler(
        MessageHandler(
            filters.Regex(r"^(?i:bode)[.!?]*$") & filters.ChatType.GROUPS,
            bode_grupo_handler
        )
    )

    # ===== 10. HANDLER GENÉRICO DE BOTÕES (CATCH-ALL) =====
    # Este handler deve ser o ÚLTIMO, pois captura qualquer callback não tratado
    app.add_handler(CallbackQueryHandler(botao_handler))

    # ===== 11. HANDLERS DE MENSAGENS EM GRUPO =====
    # Captura mensagens de texto e comandos em grupos
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
    """
    Encerramento gracioso do servidor e do bot.
    Garante que o webhook seja removido antes de desligar.
    """
    try:
        logger.info("Shutdown iniciado...")
        
        # Para o servidor
        try:
            server.should_exit = True
        except Exception:
            pass

        # Remove webhook
        try:
            await telegram_app.bot.delete_webhook(drop_pending_updates=False)
        except Exception:
            pass

        # Para o bot
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
    
    # Valida variáveis de ambiente obrigatórias
    token = _require_env("TELEGRAM_TOKEN", TOKEN)
    render_url = _require_env("RENDER_EXTERNAL_URL", RENDER_URL)

    webhook_url = _join_url(render_url, WEBHOOK_PATH)

    logger.info("TOKEN carregado: %s", "SIM" if token else "NAO")
    logger.info("RENDER_URL: %s", render_url)
    logger.info("PORT: %s", PORT)
    logger.info("WEBHOOK_URL: %s", webhook_url)

    # Cria a aplicação do Telegram
    telegram_app = Application.builder().token(token).build()
    register_handlers(telegram_app)

    # Inicializa o app
    await telegram_app.initialize()
    await telegram_app.start()

    # Configura webhook (remove pendentes para evitar processamento duplicado)
    await telegram_app.bot.delete_webhook(drop_pending_updates=True)
    await asyncio.sleep(0.5)
    await telegram_app.bot.set_webhook(
        url=webhook_url,
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
        max_connections=1,
    )

    # Verifica configuração do webhook
    info = await telegram_app.bot.get_webhook_info()
    logger.info("Webhook configurado: %s", info.url)
    logger.info("Pending updates: %s", info.pending_update_count)

    # ===== CONFIGURAÇÃO DO SERVIDOR WEBHOOK =====
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
        """Endpoint de saúde para o Render."""
        return PlainTextResponse("OK")

    async def root(request: Request) -> PlainTextResponse:
        """Página inicial (apenas informativa)."""
        return PlainTextResponse("Bode Andarilho Bot - Online")

    # Cria aplicação Starlette com as rotas
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

    # ===== INICIA SCHEDULER DE LEMBRETES =====
    from src.scheduler import iniciar_scheduler
    await iniciar_scheduler(telegram_app)

    # ===== CONFIGURA SHUTDOWN GRACIOSO =====
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(
                sig, 
                lambda s=sig: asyncio.create_task(shutdown(server, telegram_app))
            )
        except NotImplementedError:
            # Alguns ambientes (Windows) não suportam signal handlers
            pass

    print(f"Servidor ouvindo em 0.0.0.0:{PORT}")
    await server.serve()


# ============================================
# PONTO DE ENTRADA DO SCRIPT
# ============================================
if __name__ == "__main__":
    asyncio.run(main())