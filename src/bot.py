from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from src.messages import BOAS_VINDAS, BOAS_VINDAS_RETORNO, MENU_PRINCIPAL

def menu_principal_teclado():
    teclado = [
        [InlineKeyboardButton("📅 Ver eventos", callback_data="ver_eventos")],
        [InlineKeyboardButton("✅ Minhas confirmações", callback_data="minhas_confirmacoes")],
        [InlineKeyboardButton("👤 Meus Dados", callback_data="meus_dados")],
    ]
    return InlineKeyboardMarkup(teclado)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Por enquanto todos os membros são tratados como primeiro acesso
    # O reconhecimento de membros cadastrados será adicionado em breve
    await update.message.reply_text(
        BOAS_VINDAS,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Vamos lá!", callback_data="iniciar_cadastro")]
        ])
    )

async def botao_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "iniciar_cadastro":
        await query.edit_message_text(
            "Em breve o cadastro estará disponível aqui. 🐐",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Voltar", callback_data="menu")]
            ])
        )

    elif query.data == "menu":
        await query.edit_message_text(
            MENU_PRINCIPAL,
            reply_markup=menu_principal_teclado()
        )
