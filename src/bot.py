# src/bot.py

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes
from src.sheets import buscar_membro
from src.cadastro import cadastro_start
from src.eventos import (
    mostrar_eventos, mostrar_detalhes_evento, cancelar_presenca,
    ver_confirmados, minhas_confirmacoes, mostrar_eventos_por_data,
    mostrar_eventos_por_grau, fechar_mensagem, detalhes_confirmado
)
from src.perfil import mostrar_perfil
from src.permissoes import get_nivel

def menu_principal_teclado(nivel: str):
    """Menu principal baseado no nível do usuário - APENAS botões permitidos."""
    botoes = [
        [InlineKeyboardButton("📅 Ver eventos", callback_data="ver_eventos")],
        [InlineKeyboardButton("✅ Minhas confirmações", callback_data="minhas_confirmacoes")],
        [InlineKeyboardButton("👤 Meu cadastro", callback_data="meu_cadastro")],
    ]

    if nivel == "2" or nivel == "3":
        botoes.append([InlineKeyboardButton("📋 Área do Secretário", callback_data="area_secretario")])

    if nivel == "3":
        botoes.append([InlineKeyboardButton("⚙️ Área do Administrador", callback_data="area_admin")])

    return InlineKeyboardMarkup(botoes)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler para comando /start ou palavra 'bode' (quando chamado do grupo)."""
    # Se estiver em grupo, chama cadastro_start que cuidará do redirecionamento
    if update.effective_chat.type in ["group", "supergroup"]:
        await cadastro_start(update, context)
        return

    # Se já está em privado, prossegue normalmente
    telegram_id = update.effective_user.id
    membro = buscar_membro(telegram_id)

    if membro:
        nivel = get_nivel(telegram_id)
        await update.message.reply_text(
            f"Bem-vindo de volta, irmão {membro.get('Nome', '')}!\n\n"
            "O que deseja fazer?",
            reply_markup=menu_principal_teclado(nivel)
        )
    else:
        await cadastro_start(update, context)

async def botao_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler genérico para botões (deve ser o último)."""
    query = update.callback_query
    await query.answer()

    telegram_id = update.effective_user.id
    nivel = get_nivel(telegram_id)
    data = query.data

    # Verificação de permissão para áreas restritas
    if data == "area_secretario" and nivel not in ["2", "3"]:
        await query.edit_message_text("⛔ Você não tem permissão para acessar a Área do Secretário.")
        return
    if data == "area_admin" and nivel != "3":
        await query.edit_message_text("⛔ Você não tem permissão para acessar a Área do Administrador.")
        return

    # Handlers de navegação de eventos (com pipe |)
    if data == "ver_eventos":
        await mostrar_eventos(update, context)
    elif data.startswith("data|"):
        await mostrar_eventos_por_data(update, context)
    elif data.startswith("grau|"):
        await mostrar_eventos_por_grau(update, context)
    elif data.startswith("evento|"):
        await mostrar_detalhes_evento(update, context)
    elif data.startswith("ver_confirmados|"):
        await ver_confirmados(update, context)
    elif data.startswith("cancelar|") or data.startswith("confirma_cancelar|"):
        await cancelar_presenca(update, context)
    elif data == "fechar_mensagem":
        await fechar_mensagem(update, context)
    elif data == "minhas_confirmacoes":
        await minhas_confirmacoes(update, context)
    elif data.startswith("detalhes_confirmado|"):
        await detalhes_confirmado(update, context)
    elif data == "meu_cadastro":
        await mostrar_perfil(update, context)
    elif data == "area_secretario":
        await mostrar_area_secretario(update, context)
    elif data == "area_admin":
        await mostrar_area_admin(update, context)
    elif data == "menu_principal":
        await query.edit_message_text(
            "O que deseja fazer?",
            reply_markup=menu_principal_teclado(nivel)
        )
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
    elif data == "admin_editar_membro":
        from src.admin_acoes import editar_membro
        await editar_membro(update, context)
    elif data == "admin_promover":
        from src.admin_acoes import promover_handler
        await promover_handler(update, context)
    elif data == "admin_rebaixar":
        from src.admin_acoes import rebaixar_handler
        await rebaixar_handler(update, context)
    elif data == "editar_perfil":
        # Este callback será capturado pelo ConversationHandler em editar_perfil.py
        return
    else:
        await query.edit_message_text("Função em desenvolvimento ou comando não reconhecido.")

async def mostrar_area_secretario(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menu da área do secretário. Se estiver em grupo, redireciona para privado."""
    query = update.callback_query
    await query.answer()

    if update.effective_chat.type in ["group", "supergroup"]:
        await query.edit_message_text(
            "🔔 A Área do Secretário será aberta no meu chat privado. "
            "Verifique suas mensagens."
        )
        await context.bot.send_message(
            chat_id=update.effective_user.id,
            text="📋 *Área do Secretário*\n\nO que deseja fazer?",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📌 Cadastrar evento", callback_data="cadastrar_evento")],
                [InlineKeyboardButton("📋 Meus eventos", callback_data="meus_eventos")],
                [InlineKeyboardButton("📋 Ver confirmados por evento", callback_data="ver_confirmados_secretario")],
                [InlineKeyboardButton("⬅️ Voltar ao menu", callback_data="menu_principal")]
            ])
        )
        return

    telegram_id = update.effective_user.id
    nivel = get_nivel(telegram_id)

    if nivel not in ["2", "3"]:
        await query.edit_message_text("⛔ Você não tem permissão para acessar esta área.")
        return

    teclado = InlineKeyboardMarkup([
        [InlineKeyboardButton("📌 Cadastrar evento", callback_data="cadastrar_evento")],
        [InlineKeyboardButton("📋 Meus eventos", callback_data="meus_eventos")],
        [InlineKeyboardButton("📋 Ver confirmados por evento", callback_data="ver_confirmados_secretario")],
        [InlineKeyboardButton("⬅️ Voltar", callback_data="menu_principal")],
    ])

    await query.edit_message_text(
        "📋 *Área do Secretário*\n\n"
        "O que deseja fazer?",
        parse_mode="Markdown",
        reply_markup=teclado
    )

async def mostrar_area_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menu da área do administrador. Se estiver em grupo, redireciona para privado."""
    query = update.callback_query
    await query.answer()

    if update.effective_chat.type in ["group", "supergroup"]:
        await query.edit_message_text(
            "🔔 A Área do Administrador será aberta no meu chat privado. "
            "Verifique suas mensagens."
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
                [InlineKeyboardButton("⬅️ Voltar ao menu", callback_data="menu_principal")]
            ])
        )
        return

    telegram_id = update.effective_user.id
    nivel = get_nivel(telegram_id)

    if nivel != "3":
        await query.edit_message_text("⛔ Você não tem permissão para acessar esta área.")
        return

    teclado = InlineKeyboardMarkup([
        [InlineKeyboardButton("📌 Cadastrar evento", callback_data="cadastrar_evento")],
        [InlineKeyboardButton("📋 Gerenciar eventos", callback_data="meus_eventos")],
        [InlineKeyboardButton("👥 Ver todos os membros", callback_data="admin_ver_membros")],
        [InlineKeyboardButton("✏️ Editar membro", callback_data="admin_editar_membro")],
        [InlineKeyboardButton("🟢 Promover secretário", callback_data="admin_promover")],
        [InlineKeyboardButton("🔻 Rebaixar secretário", callback_data="admin_rebaixar")],
        [InlineKeyboardButton("⬅️ Voltar", callback_data="menu_principal")],
    ])

    await query.edit_message_text(
        "⚙️ *Área do Administrador*\n\n"
        "O que deseja fazer?",
        parse_mode="Markdown",
        reply_markup=teclado
    )