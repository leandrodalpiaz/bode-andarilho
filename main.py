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

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.error import InvalidToken

from src.miniapp import (
    get_cadastro_membro,
    get_cadastro_evento,
    get_cadastro_loja,
    api_cadastro_membro,
    api_cadastro_evento,
    api_cadastro_loja,
    api_listar_lojas,
    WEBAPP_URL_MEMBRO,
)
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
from src.bot import (
    botao_handler,
    menu_principal_teclado,
    start,
    _enviar_ou_editar_mensagem,
    TIPO_RESULTADO,
)

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
    membros_pagina_anterior,
    membros_pagina_proxima,
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

# Ajuda contextual e gamificação
from src.ajuda.menus import ajuda_handlers
from src.ajuda.conquistas import mostrar_marcos_secretario, mostrar_conquistas_membro

# Utilitários
from src.sheets_supabase import buscar_membro, membro_esta_ativo, atualizar_status_membro
from src.permissoes import get_nivel
from src.messages import (
    GRUPO_ONBOARDING_SEM_CADASTRO,
    GRUPO_FALLBACK_ABRIR_PRIVADO,
    GRUPO_COMANDO_PRIVADO,
    GRUPO_COMANDO_NAO_RECONHECIDO,
    GRUPO_BOAS_VINDAS_RETORNO_TMPL,
    GRUPO_ONBOARDING_NOVO_MEMBRO_TMPL,
    GRUPO_FALLBACK_NOVO_MEMBRO_TMPL,
)

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
DROP_PENDING_UPDATES_ON_BOOT = os.getenv("DROP_PENDING_UPDATES_ON_BOOT", "false")
WEBHOOK_MAX_CONNECTIONS = int(os.getenv("WEBHOOK_MAX_CONNECTIONS", "20"))
# ID do grupo principal (obrigatório para verificação de presença no grupo)
GRUPO_PRINCIPAL_ID_STR = os.getenv("GRUPO_PRINCIPAL_ID", "")
GRUPO_TELEGRAM_ID: Optional[int] = int(GRUPO_PRINCIPAL_ID_STR) if GRUPO_PRINCIPAL_ID_STR.lstrip("-").isdigit() else None


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


def _clean_env_text(value: Optional[str]) -> Optional[str]:
    """Normaliza valores de env removendo espaços/aspas acidentais."""
    if value is None:
        return None
    cleaned = value.strip()
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in {"'", '"'}:
        cleaned = cleaned[1:-1].strip()
    return cleaned


def _link_privado_bot(bot_username: Optional[str], start_param: str = "start") -> str:
    """Monta link seguro para abrir o chat privado do bot com deep link opcional."""
    username = (bot_username or "BodeAndarilhoBot").lstrip("@")
    if start_param:
        return f"https://t.me/{username}?start={start_param}"
    return f"https://t.me/{username}"


def _env_bool(value: Optional[str], default: bool = False) -> bool:
    """Converte string de ambiente para bool com fallback seguro."""
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


async def _auto_delete_mensagens_grupo(context, chat_id: int, message_ids: list[int], delay: int = 15) -> None:
    """Apaga mensagens temporárias no grupo sem falhar o fluxo principal."""
    await asyncio.sleep(max(1, int(delay)))
    for msg_id in message_ids:
        if not msg_id:
            continue
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
        except Exception as e:
            logger.debug("Nao foi possivel autoapagar mensagem %s no chat %s: %s", msg_id, chat_id, e)


# ============================================
# HANDLERS DE GRUPO
# ============================================

async def bode_grupo_handler(update: Update, context):
    """
    Captura a palavra 'bode' em grupos e redireciona para o privado.
    - Se cadastrado e ativo: envia/edita menu no privado
    - Se novo/inativo: envia onboarding no privado com botão de iniciar cadastro
    - Só envia fallback no grupo quando o privado falhar
    """
    if update.effective_chat.type not in ("group", "supergroup"):
        return

    logger.info(
        "bode_grupo_handler acionado: chat_id=%s user_id=%s texto=%r",
        update.effective_chat.id if update.effective_chat else None,
        update.effective_user.id if update.effective_user else None,
        (update.message.text if update.message else None),
    )

    user_id = update.effective_user.id
    membro = buscar_membro(user_id)
    cadastro_ativo = bool(membro and membro_esta_ativo(membro))

    link_privado = _link_privado_bot(getattr(context.bot, "username", None), "cadastro")
    teclado_privado = InlineKeyboardMarkup(
        [[InlineKeyboardButton("📩 Abrir privado do bot", url=link_privado)]]
    )

    if cadastro_ativo:
        from src.bot import criar_estrutura_inicial
        sucesso = await criar_estrutura_inicial(context, user_id, membro)
        if sucesso:
            logger.info("Fluxo bode no grupo: menu aberto no privado para user_id=%s", user_id)
            return
    else:
        texto_onboarding = GRUPO_ONBOARDING_SEM_CADASTRO
        if WEBAPP_URL_MEMBRO:
            btn_cadastro = InlineKeyboardButton("🧾 Iniciar cadastro", web_app=WebAppInfo(url=WEBAPP_URL_MEMBRO))
        else:
            btn_cadastro = InlineKeyboardButton("🧾 Iniciar cadastro", callback_data="iniciar_cadastro")
        teclado_cadastro = InlineKeyboardMarkup([[btn_cadastro]])
        sucesso = await _enviar_ou_editar_mensagem(
            context,
            user_id,
            TIPO_RESULTADO,
            texto_onboarding,
            teclado_cadastro,
            limpar_conteudo=True,
        )
        if sucesso:
            logger.info("Fluxo bode no grupo: onboarding enviado no privado para user_id=%s", user_id)
            return

    logger.info("Fluxo bode no grupo: fallback no grupo para user_id=%s", user_id)
    if update.message:
        resposta = await update.message.reply_text(
            GRUPO_FALLBACK_ABRIR_PRIVADO,
            reply_markup=teclado_privado,
        )
        asyncio.create_task(
            _auto_delete_mensagens_grupo(
                context,
                update.effective_chat.id,
                [resposta.message_id],
                delay=15,
            )
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

        logger.info(
            "mensagem_grupo_handler: chat_id=%s user_id=%s texto=%r",
            chat.id,
            update.effective_user.id if update.effective_user else None,
            text,
        )

        if text in ("/start", "/cadastro"):
            await update.message.reply_text(
                GRUPO_COMANDO_PRIVADO
            )
            return

        # Fallback para comandos não suportados no grupo.
        if text.startswith("/"):
            link_privado = _link_privado_bot(getattr(context.bot, "username", None), "start")
            teclado_privado = InlineKeyboardMarkup(
                [[InlineKeyboardButton("📩 Abrir privado do bot", url=link_privado)]]
            )
            resposta = await update.message.reply_text(
                GRUPO_COMANDO_NAO_RECONHECIDO,
                reply_markup=teclado_privado,
            )

            # Limpa comando + aviso para manter o grupo organizado.
            asyncio.create_task(
                _auto_delete_mensagens_grupo(
                    context,
                    chat.id,
                    [update.message.message_id, resposta.message_id],
                    delay=15,
                )
            )
            return
    except Exception as e:
        logger.warning("Erro em mensagem_grupo_handler: %s", e, exc_info=True)


async def novo_membro_grupo_handler(update: Update, context):
    """
    Detecta entradas e saídas do grupo.

    Saída  → marca cadastro como inativo no Supabase.
    Entrada → tenta enviar convite de cadastro no privado do novo membro.
              Se o privado não estiver disponível, envia fallback mínimo
              no grupo (auto-apagado em 30 s) com deep link.
              Se já cadastrado e ativo, envia boas-vindas de retorno no privado.
    """
    try:
        if not update.chat_member:
            return

        chat_member = update.chat_member
        chat = update.effective_chat
        if not chat or chat.type not in ("group", "supergroup"):
            return

        novo_status = chat_member.new_chat_member.status
        antigo_status = chat_member.old_chat_member.status

        user = chat_member.new_chat_member.user
        if user.is_bot:
            return

        # ── SAÍDA DO GRUPO ──────────────────────────────────────────────────
        if novo_status in ("left", "kicked") and antigo_status in (
            "member", "administrator", "creator"
        ):
            atualizar_status_membro(user.id, "inativo")
            logger.info(
                "Membro %s saiu/foi removido do grupo %s — cadastro marcado como inativo.",
                user.id, chat.id,
            )
            return

        # ── ENTRADA NO GRUPO ────────────────────────────────────────────────
        if novo_status not in ("member", "administrator", "creator"):
            return

        # Promoção/rebaixamento interno (já estava no grupo): ignorar.
        if antigo_status in ("member", "administrator", "creator"):
            return

        nome = user.first_name or "Irmão"
        membro = buscar_membro(user.id)
        cadastro_ativo = bool(membro and membro_esta_ativo(membro))

        username_bot = (getattr(context.bot, "username", None) or "BodeAndarilhoBot").lstrip("@")
        link_privado = f"https://t.me/{username_bot}?start=cadastro"

        if cadastro_ativo:
            # Reativa o cadastro caso tenha sido marcado inativo numa saída anterior
            atualizar_status_membro(user.id, "Ativo")
            texto_retorno = GRUPO_BOAS_VINDAS_RETORNO_TMPL.format(nome=membro.get('Nome', nome))
            try:
                await context.bot.send_message(
                    chat_id=user.id,
                    text=texto_retorno,
                    parse_mode="Markdown",
                )
                logger.info("Boas-vindas de retorno no privado para user_id=%s.", user.id)
            except Exception:
                logger.debug("Privado indisponível para retorno user_id=%s — nenhuma ação.", user.id)
            return

        # Novo membro: tentar enviar convite de cadastro diretamente no privado
        texto_onboarding = GRUPO_ONBOARDING_NOVO_MEMBRO_TMPL.format(nome=nome)
        if WEBAPP_URL_MEMBRO:
            btn_onboarding = InlineKeyboardButton("🧾 Fazer meu cadastro", web_app=WebAppInfo(url=WEBAPP_URL_MEMBRO))
        else:
            btn_onboarding = InlineKeyboardButton("🧾 Fazer meu cadastro", callback_data="iniciar_cadastro")
        teclado_onboarding = InlineKeyboardMarkup([[btn_onboarding]])
        try:
            await context.bot.send_message(
                chat_id=user.id,
                text=texto_onboarding,
                parse_mode="Markdown",
                reply_markup=teclado_onboarding,
            )
            logger.info("Convite de cadastro enviado no privado para user_id=%s.", user.id)
            return
        except Exception as e_priv:
            logger.info(
                "Privado indisponível para user_id=%s (%s). Usando fallback no grupo.",
                user.id, e_priv,
            )

        # Fallback: mensagem mínima no grupo com deep link (auto-apagada em 30 s)
        teclado_deep = InlineKeyboardMarkup(
            [[InlineKeyboardButton("🧾 Fazer meu cadastro", url=link_privado)]]
        )
        msg = await context.bot.send_message(
            chat_id=chat.id,
            text=GRUPO_FALLBACK_NOVO_MEMBRO_TMPL.format(nome=nome),
            reply_markup=teclado_deep,
        )
        asyncio.create_task(
            _auto_delete_mensagens_grupo(context, chat.id, [msg.message_id], delay=30)
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

    # ===== 3. CALLBACKS DA CENTRAL DE AJUDA =====
    for handler in ajuda_handlers:
        app.add_handler(handler)

    # ===== 4. CALLBACKS DE GAMIFICAÇÃO =====
    app.add_handler(CallbackQueryHandler(
        mostrar_marcos_secretario, pattern=r"^mostrar_marcos_secretario$"
    ))
    app.add_handler(CallbackQueryHandler(
        mostrar_conquistas_membro, pattern=r"^mostrar_conquistas_membro$"
    ))

    # ===== 5. CALLBACKS ESPECÍFICOS DE EVENTOS =====
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

    # ===== 6. CALLBACKS DE CONFIRMAÇÕES =====
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

    # ===== 7. CALLBACKS DE AÇÕES EM EVENTOS =====
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

    # ===== 8. CALLBACKS DA ÁREA DO SECRETÁRIO =====
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

    # ===== 9. CALLBACKS ADMINISTRATIVOS =====
    app.add_handler(CallbackQueryHandler(
        ver_todos_membros, pattern=r"^admin_ver_membros$"
    ))
    app.add_handler(CallbackQueryHandler(
        membros_pagina_anterior, pattern=r"^membros_page_prev$"
    ))
    app.add_handler(CallbackQueryHandler(
        membros_pagina_proxima, pattern=r"^membros_page_next$"
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

    # ===== 10. CALLBACKS DE LOJAS =====
    app.add_handler(CallbackQueryHandler(menu_lojas, pattern=r"^menu_lojas$"))
    app.add_handler(CallbackQueryHandler(listar_lojas_handler, pattern=r"^loja_listar$"))
    # Handlers para exclusão de lojas (adicionados)
    app.add_handler(CallbackQueryHandler(excluir_loja_menu, pattern=r"^loja_excluir_menu$"))
    app.add_handler(CallbackQueryHandler(confirmar_exclusao_loja, pattern=r"^excluir_loja_\d+$"))
    app.add_handler(CallbackQueryHandler(executar_exclusao_loja, pattern=r"^excluir_loja_confirmar$"))

    # ===== 11. HANDLER PARA NOVOS MEMBROS NO GRUPO =====
    app.add_handler(ChatMemberHandler(novo_membro_grupo_handler))

    # ===== 12. HANDLER DA PALAVRA "BODE" =====
    # Aceita palavra simples, comando com barra e comando com menção ao bot.
    app.add_handler(
        MessageHandler(
            filters.ChatType.GROUPS
            & filters.TEXT
            & filters.Regex(r"^(?i:/?(bode|menu|painel)(?:@[a-z0-9_]+)?)[.!?]*$"),
            bode_grupo_handler,
        )
    )
    app.add_handler(
        CommandHandler(
            ["bode", "menu", "painel"],
            bode_grupo_handler,
            filters=filters.ChatType.GROUPS,
        )
    )

    # ===== 13. HANDLER GENÉRICO DE BOTÕES (CATCH-ALL) =====
    app.add_handler(CallbackQueryHandler(botao_handler))

    # ===== 14. HANDLERS DE MENSAGENS EM GRUPO =====
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

    token = _require_env("TELEGRAM_TOKEN", _clean_env_text(TOKEN))
    render_url = _require_env("RENDER_EXTERNAL_URL", _clean_env_text(RENDER_URL))
    webhook_path = _clean_env_text(WEBHOOK_PATH) or "/telegram/webhook"
    webhook_path = webhook_path if webhook_path.startswith("/") else f"/{webhook_path}"

    webhook_url = _join_url(render_url, webhook_path)
    drop_pending_updates = _env_bool(DROP_PENDING_UPDATES_ON_BOOT, default=False)

    logger.info("TOKEN carregado: %s", "SIM" if token else "NAO")
    logger.info("RENDER_URL: %s", render_url)
    logger.info("PORT: %s", PORT)
    logger.info("WEBHOOK_PATH normalizado: %r", webhook_path)
    logger.info("WEBHOOK_URL: %s", webhook_url)
    logger.info("DROP_PENDING_UPDATES_ON_BOOT: %s", drop_pending_updates)
    logger.info("WEBHOOK_MAX_CONNECTIONS: %s", WEBHOOK_MAX_CONNECTIONS)

    telegram_app = Application.builder().token(token).build()
    register_handlers(telegram_app)

    try:
        await telegram_app.initialize()
    except InvalidToken:
        logger.error(
            "TELEGRAM_TOKEN inválido ou revogado. Atualize a variável de ambiente no provider."
        )
        raise RuntimeError("Falha de autenticação no Telegram.") from None

    await telegram_app.start()

    await telegram_app.bot.set_webhook(
        url=webhook_url,
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=drop_pending_updates,
        max_connections=WEBHOOK_MAX_CONNECTIONS,
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
            Route(webhook_path, webhook, methods=["POST"]),
            Route("/webapp/cadastro_membro", get_cadastro_membro, methods=["GET"]),
            Route("/webapp/cadastro_evento", get_cadastro_evento, methods=["GET"]),
            Route("/webapp/cadastro_loja", get_cadastro_loja, methods=["GET"]),
            Route("/api/cadastro_membro", api_cadastro_membro, methods=["POST"]),
            Route("/api/cadastro_evento", api_cadastro_evento, methods=["POST"]),
            Route("/api/cadastro_loja", api_cadastro_loja, methods=["POST"]),
            Route("/api/lojas", api_listar_lojas, methods=["POST"]),
        ]
    )
    starlette_app.state.telegram_app = telegram_app
    starlette_app.state.bot_token = token

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
