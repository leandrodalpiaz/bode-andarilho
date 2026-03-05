# src/bot.py
from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from src.sheets import buscar_membro
from src.cadastro import cadastro_start
from src.perfil import mostrar_perfil
from src.permissoes import get_nivel

logger = logging.getLogger(__name__)


def menu_principal_teclado(nivel: str) -> InlineKeyboardMarkup:
    """Menu principal baseado no nível do usuário - APENAS botões permitidos."""
    botoes = [
        [InlineKeyboardButton("📅 Ver eventos", callback_data="ver_eventos")],
        [InlineKeyboardButton("✅ Minhas confirmações", callback_data="minhas_confirmacoes")],
        [InlineKeyboardButton("👤 Meu cadastro", callback_data="meu_cadastro")],
    ]

    if nivel in ("2", "3"):
        botoes.append([InlineKeyboardButton("📋 Área do Secretário", callback_data="area_secretario")])

    if nivel == "3":
        botoes.append([InlineKeyboardButton("⚙️ Área do Administrador", callback_data="area_admin")])

    return InlineKeyboardMarkup(botoes)


async def _safe_edit(query, text: str, **kwargs):
    """Evita log de erro quando o Telegram diz que a mensagem não mudou."""
    try:
        await query.edit_message_text(text, **kwargs)
    except Exception as e:
        if "Message is not modified" not in str(e):
            raise


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler para comando /start ou palavra 'bode' (quando chamado do grupo)."""
    logger.info(
        "start chamado - chat_type=%s user_id=%s",
        getattr(update.effective_chat, "type", None),
        getattr(update.effective_user, "id", None),
    )

    # Se estiver em grupo, chama cadastro_start que cuidará do redirecionamento
    if update.effective_chat and update.effective_chat.type in ["group", "supergroup"]:
        await cadastro_start(update, context)
        return

    # Se já está em privado, prossegue normalmente
    telegram_id = update.effective_user.id
    membro = buscar_membro(telegram_id)

    if membro:
        nivel = get_nivel(telegram_id)

        texto = (
            f"Bem-vindo de volta, irmão {membro.get('Nome', '')}!\n\n"
            "O que deseja fazer?"
        )

        # /start normalmente vem como mensagem; mas protege caso venha diferente
        if update.message:
            await update.message.reply_text(
                texto,
                reply_markup=menu_principal_teclado(nivel),
            )
        else:
            await context.bot.send_message(
                chat_id=telegram_id,
                text=texto,
                reply_markup=menu_principal_teclado(nivel),
            )
    else:
        await cadastro_start(update, context)


async def botao_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler genérico para botões (deve ser o último)."""
    query = update.callback_query
    if not query:
        return

    data = query.data or ""
    
    # Feedbacks específicos baseados no callback
    if data == "ver_eventos":
        await query.answer("📅 Carregando eventos...")
    elif data.startswith("data|"):
        await query.answer("📅 Filtrando eventos...")
    elif data.startswith("grau|"):
        await query.answer("🔺 Filtrando por grau...")
    elif data.startswith("evento|"):
        await query.answer("📋 Carregando detalhes do evento...")
    elif data.startswith("ver_confirmados|"):
        await query.answer("👥 Buscando lista de confirmados...")
    elif data.startswith("cancelar|") or data.startswith("confirma_cancelar|"):
        await query.answer("❌ Processando cancelamento...")
    elif data == "fechar_mensagem":
        await query.answer("🔒 Fechando mensagem...")
    elif data == "minhas_confirmacoes":
        await query.answer("✅ Buscando suas confirmações...")
    elif data.startswith("detalhes_confirmado|"):
        await query.answer("📋 Carregando detalhes...")
    elif data.startswith("detalhes_historico|"):
        await query.answer("📜 Carregando histórico...")
    elif data == "meu_cadastro":
        await query.answer("👤 Carregando seu perfil...")
    elif data == "area_secretario":
        await query.answer("📋 Acessando área do secretário...")
    elif data == "area_admin":
        await query.answer("⚙️ Acessando área do administrador...")
    elif data == "menu_principal":
        await query.answer("🏠 Voltando ao menu principal...")
    elif data == "cadastrar_evento":
        await query.answer("🏛 Iniciando cadastro de evento...")
    elif data == "ver_confirmados_secretario":
        await query.answer("👥 Buscando confirmados...")
    elif data == "encerrar_evento":
        await query.answer("❌ Processando...")
    elif data == "meus_eventos":
        await query.answer("📋 Buscando seus eventos...")
    elif data.startswith("gerenciar_evento|"):
        await query.answer("⚙️ Carregando opções...")
    elif data.startswith("confirmar_cancelamento|"):
        await query.answer("❌ Processando...")
    elif data.startswith("cancelar_evento|"):
        await query.answer("❌ Cancelando evento...")
    elif data == "admin_ver_membros":
        await query.answer("👥 Buscando membros...")
    elif data == "menu_lojas":
        await query.answer("🏛️ Carregando lojas...")
    elif data == "loja_listar":
        await query.answer("📋 Buscando suas lojas...")
    elif data == "menu_notificacoes":
        await query.answer("🔔 Carregando configurações...")
    elif data == "notificacoes_ativar":
        await query.answer("✅ Ativando notificações...")
    elif data == "notificacoes_desativar":
        await query.answer("🔕 Desativando notificações...")
    else:
        await query.answer("⏳ Processando...")

    # ============================================================
    # Guardrails: callbacks que DEVEM ser tratados por outros handlers
    # (ConversationHandlers / handlers específicos registrados antes)
    # ============================================================

    # Admin (flows de ConversationHandler em outros módulos)
    if data in {"admin_promover", "admin_rebaixar", "editar_perfil", "admin_editar_membro"}:
        return

    # Confirmação de presença (ConversationHandler do eventos.py)
    if data.startswith("confirmar|"):
        return

    # Cadastro (ConversationHandler do cadastro.py)
    if data in {"iniciar_cadastro", "editar_cadastro", "continuar_cadastro"}:
        return

    # Eventos secretário (ConversationHandler do eventos_secretario.py)
    if data == "editar_evento_secretario":
        return

    telegram_id = update.effective_user.id
    nivel = get_nivel(telegram_id)

    # Verificação de permissão para áreas restritas
    if data == "area_secretario" and nivel not in ["2", "3"]:
        await _safe_edit(query, "⛔ Você não tem permissão para acessar a Área do Secretário.")
        return
    if data == "area_admin" and nivel != "3":
        await _safe_edit(query, "⛔ Você não tem permissão para acessar a Área do Administrador.")
        return

    # Handlers de navegação de eventos (com pipe |)
    if data == "ver_eventos":
        from src.eventos import mostrar_eventos
        await mostrar_eventos(update, context)
    elif data.startswith("data|"):
        from src.eventos import mostrar_eventos_por_data
        await mostrar_eventos_por_data(update, context)
    elif data.startswith("grau|"):
        from src.eventos import mostrar_eventos_por_grau
        await mostrar_eventos_por_grau(update, context)
    elif data.startswith("evento|"):
        from src.eventos import mostrar_detalhes_evento
        await mostrar_detalhes_evento(update, context)
    elif data.startswith("ver_confirmados|"):
        from src.eventos import ver_confirmados
        await ver_confirmados(update, context)
    elif data.startswith("cancelar|") or data.startswith("confirma_cancelar|"):
        from src.eventos import cancelar_presenca
        await cancelar_presenca(update, context)
    elif data == "fechar_mensagem":
        from src.eventos import fechar_mensagem
        await fechar_mensagem(update, context)
    elif data == "minhas_confirmacoes":
        from src.eventos import minhas_confirmacoes
        await minhas_confirmacoes(update, context)
    elif data.startswith("detalhes_confirmado|"):
        from src.eventos import detalhes_confirmado
        await detalhes_confirmado(update, context)
    elif data.startswith("detalhes_historico|"):
        from src.eventos import detalhes_historico
        await detalhes_historico(update, context)
    elif data == "meu_cadastro":
        await mostrar_perfil(update, context)

    elif data == "area_secretario":
        await mostrar_area_secretario(update, context)
    elif data == "area_admin":
        await mostrar_area_admin(update, context)

    elif data == "menu_principal":
        await _safe_edit(
            query,
            "O que deseja fazer?",
            reply_markup=menu_principal_teclado(nivel),
        )

    # Secretário/Admin - imports tardios
    elif data == "cadastrar_evento":
        from src.cadastro_evento import novo_evento_start
        await novo_evento_start(update, context)
    elif data == "ver_confirmados_secretario":
        from src.admin_acoes import ver_confirmados_secretario
        await ver_confirmados_secretario(update, context)
    elif data == "encerrar_evento":
        from src.admin_acoes import encerrar_evento
        await encerrar_evento(update, context)
    elif data == "meus_eventos":
        from src.eventos_secretario import meus_eventos
        await meus_eventos(update, context)
    elif data.startswith("gerenciar_evento|"):
        from src.eventos_secretario import menu_gerenciar_evento
        await menu_gerenciar_evento(update, context)
    elif data.startswith("confirmar_cancelamento|"):
        from src.eventos_secretario import confirmar_cancelamento
        await confirmar_cancelamento(update, context)
    elif data.startswith("cancelar_evento|"):
        from src.eventos_secretario import executar_cancelamento
        await executar_cancelamento(update, context)
    elif data == "admin_ver_membros":
        from src.admin_acoes import ver_todos_membros
        await ver_todos_membros(update, context)
    elif data == "menu_lojas":
        from src.lojas import menu_lojas
        await menu_lojas(update, context)
    elif data == "loja_listar":
        from src.lojas import listar_lojas_handler
        await listar_lojas_handler(update, context)
    elif data == "menu_notificacoes":
        from src.admin_acoes import menu_notificacoes
        await menu_notificacoes(update, context)
    elif data == "notificacoes_ativar":
        from src.admin_acoes import notificacoes_ativar
        await notificacoes_ativar(update, context)
    elif data == "notificacoes_desativar":
        from src.admin_acoes import notificacoes_desativar
        await notificacoes_desativar(update, context)

    else:
        await _safe_edit(query, "Função em desenvolvimento ou comando não reconhecido.")


async def mostrar_area_secretario(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menu da área do secretário. Se estiver em grupo, redireciona para privado."""
    query = update.callback_query
    if not query:
        return
    # Feedback já foi dado no botao_handler, não precisa repetir

    if update.effective_chat.type in ["group", "supergroup"]:
        await _safe_edit(
            query,
            "🔔 A Área do Secretário será aberta no meu chat privado. "
            "Verifique suas mensagens.",
        )
        await context.bot.send_message(
            chat_id=update.effective_user.id,
            text="📋 *Área do Secretário*\n\nO que deseja fazer?",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📌 Cadastrar evento", callback_data="cadastrar_evento")],
                [InlineKeyboardButton("📋 Meus eventos", callback_data="meus_eventos")],
                [InlineKeyboardButton("👥 Ver confirmados por evento", callback_data="ver_confirmados_secretario")],
                [InlineKeyboardButton("🏛️ Minhas lojas", callback_data="menu_lojas")],
                [InlineKeyboardButton("🔔 Configurar notificações", callback_data="menu_notificacoes")],
                [InlineKeyboardButton("⬅️ Voltar ao menu", callback_data="menu_principal")],
            ]),
        )
        return

    telegram_id = update.effective_user.id
    nivel = get_nivel(telegram_id)

    if nivel not in ["2", "3"]:
        await _safe_edit(query, "⛔ Você não tem permissão para acessar esta área.")
        return

    teclado = InlineKeyboardMarkup([
        [InlineKeyboardButton("📌 Cadastrar evento", callback_data="cadastrar_evento")],
        [InlineKeyboardButton("📋 Meus eventos", callback_data="meus_eventos")],
        [InlineKeyboardButton("👥 Ver confirmados por evento", callback_data="ver_confirmados_secretario")],
        [InlineKeyboardButton("🏛️ Minhas lojas", callback_data="menu_lojas")],
        [InlineKeyboardButton("🔔 Configurar notificações", callback_data="menu_notificacoes")],
        [InlineKeyboardButton("⬅️ Voltar", callback_data="menu_principal")],
    ])

    await _safe_edit(
        query,
        "📋 *Área do Secretário*\n\nO que deseja fazer?",
        parse_mode="Markdown",
        reply_markup=teclado,
    )


async def mostrar_area_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menu da área do administrador. Se estiver em grupo, redireciona para privado."""
    query = update.callback_query
    if not query:
        return
    # Feedback já foi dado no botao_handler, não precisa repetir

    if update.effective_chat.type in ["group", "supergroup"]:
        await _safe_edit(
            query,
            "🔔 A Área do Administrador será aberta no meu chat privado. "
            "Verifique suas mensagens.",
        )
        await context.bot.send_message(
            chat_id=update.effective_user.id,
            text="⚙️ *Área do Administrador*\n\nO que deseja fazer?",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📌 Cadastrar evento", callback_data="cadastrar_evento")],
                [InlineKeyboardButton("📋 Gerenciar eventos", callback_data="meus_eventos")],
                [InlineKeyboardButton("👥 Ver todos os membros", callback_data="admin_ver_membros")],
                [InlineKeyboardButton("✏️ Editar membro", callback_data="admin_editar_membro")],
                [InlineKeyboardButton("🟢 Promover secretário", callback_data="admin_promover")],
                [InlineKeyboardButton("🔻 Rebaixar secretário", callback_data="admin_rebaixar")],
                [InlineKeyboardButton("🏛️ Minhas lojas", callback_data="menu_lojas")],
                [InlineKeyboardButton("🔔 Configurar notificações", callback_data="menu_notificacoes")],
                [InlineKeyboardButton("⬅️ Voltar ao menu", callback_data="menu_principal")],
            ]),
        )
        return

    telegram_id = update.effective_user.id
    nivel = get_nivel(telegram_id)

    if nivel != "3":
        await _safe_edit(query, "⛔ Você não tem permissão para acessar esta área.")
        return

    teclado = InlineKeyboardMarkup([
        [InlineKeyboardButton("📌 Cadastrar evento", callback_data="cadastrar_evento")],
        [InlineKeyboardButton("📋 Gerenciar eventos", callback_data="meus_eventos")],
        [InlineKeyboardButton("👥 Ver todos os membros", callback_data="admin_ver_membros")],
        [InlineKeyboardButton("✏️ Editar membro", callback_data="admin_editar_membro")],
        [InlineKeyboardButton("🟢 Promover secretário", callback_data="admin_promover")],
        [InlineKeyboardButton("🔻 Rebaixar secretário", callback_data="admin_rebaixar")],
        [InlineKeyboardButton("🏛️ Minhas lojas", callback_data="menu_lojas")],
        [InlineKeyboardButton("🔔 Configurar notificações", callback_data="menu_notificacoes")],
        [InlineKeyboardButton("⬅️ Voltar", callback_data="menu_principal")],
    ])

    await _safe_edit(
        query,
        "⚙️ *Área do Administrador*\n\nO que deseja fazer?",
        parse_mode="Markdown",
        reply_markup=teclado,
    )