from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes
from src.sheets import buscar_membro # Importa a função para buscar membro
from src.cadastro import cadastro_start # Importa a função para iniciar o cadastro
from src.eventos import mostrar_eventos, mostrar_detalhes_evento, confirmar_presenca, cancelar_presenca
from src.perfil import mostrar_perfil
from src.permissoes import get_nivel

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
        nivel = get_nivel(telegram_id) # Pega o nível do usuário
        await update.message.reply_text(
            f"Bem-vindo de volta, irmão {membro.get('Nome', '')}!\n\n"
            "O que deseja fazer?",
            reply_markup=menu_principal_teclado(nivel) # Usa o teclado dinâmico
        )
    else:
        # Usuário não cadastrado, inicia o fluxo de cadastro
        await cadastro_start(update, context) # Chama a função de início de cadastro

async def botao_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer() # Sempre responda ao callback_query

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
    # Adicione aqui os handlers para os botões da área do secretário e admin
    # Por exemplo, para o botão "Cadastrar evento" da área do secretário:
    elif data == "cadastrar_evento":
        # Assumindo que 'novo_evento_start' é o entry_point do ConversationHandler de cadastro de evento
        # e que ele está em src/cadastro_evento.py
        from src.cadastro_evento import novo_evento_start
        await novo_evento_start(update, context)
    # ... outros handlers para botões específicos ...
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
        [InlineKeyboardButton("👤 Cadastrar membro", callback_data="cadastrar_membro_sec")],
        [InlineKeyboardButton("📋 Ver confirmados por evento", callback_data="ver_confirmados")],
        [InlineKeyboardButton("🔴 Encerrar evento", callback_data="encerrar_evento")],
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
        [InlineKeyboardButton("👥 Ver todos os membros", callback_data="admin_ver_membros")],
        [InlineKeyboardButton("✏️ Editar membro", callback_data="admin_editar_membro")],
        [InlineKeyboardButton("🗑️ Excluir membro", callback_data="admin_excluir_membro")],
        [InlineKeyboardButton("✏️ Editar evento", callback_data="admin_editar_evento")],
        [InlineKeyboardButton("🗑️ Excluir evento", callback_data="admin_excluir_evento")],
        [InlineKeyboardButton("⭐ Promover secretário", callback_data="admin_promover")],
        [InlineKeyboardButton("🔽 Rebaixar secretário", callback_data="admin_rebaixar")],
        [InlineKeyboardButton("⬅️ Voltar", callback_data="menu_principal")],
    ])

    await query.edit_message_text("⚙️ *Área do Administrador*\n\nO que deseja fazer?", parse_mode="Markdown", reply_markup=teclado)
