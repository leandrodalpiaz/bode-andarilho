# -*- coding: utf-8 -*-
import logging
import random
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler
from src.bot import navegar_para

logger = logging.getLogger(__name__)

# Tabela estática/temporária de patrocínios rotativos
# No futuro, pode ser puxada via supabase supabase.table("patrocinios")
PATROCINADORES = [
    {"nome": "Sind Ofícios", "link": "https://sindoficios.com.br", "tipo": "institucional"},
]

def obter_texto_patrocinio() -> str:
    """
    Retorna uma string formatada em markdown com um patrocinador aleatório
    para ser injetada no final de resumos e relatórios longos.
    """
    if not PATROCINADORES:
        return ""
    p = random.choice(PATROCINADORES)
    return f"\n\n_Apoio Institucional: [{p['nome']}]({p['link']})_"


async def cmd_apoiar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler para o comando /apoiar e menu de crowdfunding."""
    query = update.callback_query
    if query:
        try:
            await query.answer()
        except Exception:
            pass

    texto = (
        "🤝 *Apoie o Bode Andarilho*\n\n"
        "O ecossistema Bode Andarilho é um projeto independente e sem fins lucrativos, "
        "criado para estreitar nossos laços fraternos e facilitar a gestão maçônica.\n\n"
        "Nossa premissa é fundamental: *Maçom ajuda Maçom*.\n"
        "Se este sistema é útil para sua rotina ou para sua Oficina, "
        "considere nos apoiar para cobrirmos os custos de nuvem, banco de dados e manutenção contínua.\n\n"
        "☕ *Como você pode ajudar?*\n"
        "• Faça um PIX voluntário de qualquer valor para o servidor.\n"
        "• Adquira nossos souvenirs (Pins e Medalhas) na nossa lojinha virtual (Em breve)."
    )

    teclado = InlineKeyboardMarkup([
        [InlineKeyboardButton("📲 Contribuir via PIX", callback_data="mostrar_pix")],
        [InlineKeyboardButton("🛍️ Lojinha do Bode (Em breve)", callback_data="mostrar_lojinha")],
        [InlineKeyboardButton("🔙 Voltar ao Menu Principal", callback_data="menu_principal")]
    ])

    await navegar_para(update, context, "Apoio Institucional", texto, teclado)


async def mostrar_pix(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    texto = (
        "📲 *Doação Direta via PIX*\n\n"
        "Agradecemos profundamente o seu apoio para manter o Bode no ar, Irmão!\n\n"
        "Chave PIX (E-mail):\n`bodeandarilho@gmail.com`\n\n"
        "_(Toque na chave acima para copiá-la e cole no seu aplicativo bancário)_"
    )
    
    teclado = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Voltar", callback_data="apoiar_menu")]
    ])
    
    await navegar_para(update, context, "Chave PIX", texto, teclado)


async def mostrar_lojinha(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("Lojinha em construção! Em breve Pins e Adesivos.", show_alert=True)


def registrar_handlers_apoio(application):
    application.add_handler(CommandHandler("apoiar", cmd_apoiar))
    application.add_handler(CallbackQueryHandler(cmd_apoiar, pattern="^apoiar_menu$"))
    application.add_handler(CallbackQueryHandler(mostrar_pix, pattern="^mostrar_pix$"))
    application.add_handler(CallbackQueryHandler(mostrar_lojinha, pattern="^mostrar_lojinha$"))
