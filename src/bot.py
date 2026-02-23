# src/bot.py
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes
from src.sheets import buscar_membro # Importa a função para buscar membro
from src.cadastro import cadastro_start # Importa a função para iniciar o cadastro
from src.eventos import mostrar_eventos, mostrar_detalhes_evento, confirmar_presenca, cancelar_presenca
from src.perfil import mostrar_perfil
from src.permissoes import get_nivel
# Importa novo_evento_start localmente no botao_handler para evitar circularidade
# from src.cadastro_evento import novo_evento_start # Não importar aqui diretamente

def menu_principal_teclado(nivel: str):
    botoes = [
        [InlineKeyboardButton("📅 Ver eventos", callback_data="ver_eventos")],
        [InlineKeyboardButton("👤 Meu cadastro", callback_data="meu_cadastro")],
    ]

    if nivel in ["secretario", "admin"]:
        botoes.append([InlineKeyboardButton("📋 Área do Secretário", callback_data="area_secretario")])

    if nivel == "admin":
        botoes.append([InlineKeyboardButton("⚙️ Área do Administrador", callback_data="area_admin")])

    return InlineKeyboardMarkup(botoes)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    membro = buscar_membro(telegram_id)

    if membro:
        # Usuário já cadastrado, mostra o menu principal
        nivel = get_nivel(telegram_id)
        await update.message.reply_text(
            f"Bem-vindo de volta, irmão {membro.get('Nome', '')}!\n\n"
            "O que deseja fazer?",
            reply_markup=menu_principal_teclado(nivel)
        )
    else:
        # Usuário não cadastrado, inicia o fluxo de cadastro
        await cadastro_start(update, context)

async def botao_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    telegram_id = update.effective_user.id
    nivel = get_nivel(telegram_id)
    data = query.data

    if data == "ver_eventos":
        await mostrar_eventos(update, context)
    elif data.startswith("evento_"):
        await mostrar_detalhes_evento(update, context)
    elif data.startswith("confirmar_"):
        await confirmar_presenca(update, context)
    elif data.startswith("cancelar_"):
        await cancelar_presenca(update, context)
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
        # Importa localmente para evitar circularidade
        from src.cadastro_evento import novo_evento_start
        await novo_evento_start(update, context)
    # Adicione outros handlers para botões específicos da área do secretário/admin aqui
    # Ex: elif data == "cadastrar_membro_sec":
    #        await iniciar_cadastro_membro_secretario(update, context)
    else:
        await query.edit_message_text("Função em desenvolvimento ou comando não reconhecido.")


async def mostrar_area_secretario(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    telegram_id = update.effective_user.id
    nivel = get_nivel(telegram_id)

    if nivel not in ["secretario", "admin"]:
        await query.edit_message_text("Você não tem permissão para acessar esta área.")
        return

    teclado = InlineKeyboardMarkup([
        [InlineKeyboardButton("📅 Cadastrar evento", callback_data="cadastrar_evento")],
        [InlineKeyboardButton("👤 Cadastrar membro", callback_data="cadastrar_membro_sec")], # Exemplo
        [InlineKeyboardButton("📋 Ver confirmados por evento", callback_data="ver_confirmados")], # Exemplo
        [InlineKeyboardButton("🔴 Encerrar evento", callback_data="encerrar_evento")], # Exemplo
        [InlineKeyboardButton("⬅️ Voltar", callback_data="menu_principal")],
    ])

    await query.edit_message_text("📋 *Área do Secretário*\n\nO que deseja fazer?", parse_mode="Markdown", reply_markup=teclado)

async def mostrar_area_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    telegram_id = update.effective_user.id

    if get_nivel(telegram_id) != "admin":
        await query.edit_message_text("Você não tem permissão para acessar esta área.")
        return

    teclado = InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 Ver todos os membros", callback_data="admin_ver_membros")], # Exemplo
        [InlineKeyboardButton("✏️ Editar membro", callback_data="admin_editar_membro")], # Exemplo
        [InlineKeyboardButton("🗑️ Excluir membro", callback_data="admin_excluir_membro")], # Exemplo
        [InlineKeyboardButton("✏️ Editar evento", callback_data="admin_editar_evento")], # Exemplo
        [InlineKeyboardButton("🗑️ Excluir evento", callback_data="admin_excluir_evento")], # Exemplo
        [InlineKeyboardButton("⭐ Promover secretário", callback_data="admin_promover")], # Exemplo
        [InlineKeyboardButton("🔽 Rebaixar secretário", callback_data="admin_rebaixar")], # Exemplo
        [InlineKeyboardButton("⬅️ Voltar", callback_data="menu_principal")],
    ])

    await query.edit_message_text("⚙️ *Área do Administrador*\n\nO que deseja fazer?", parse_mode="Markdown", reply_markup=teclado)
