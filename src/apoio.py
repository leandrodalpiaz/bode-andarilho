# -*- coding: utf-8 -*-
import logging
import random
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler
from src.bot import navegar_para
from src.publicidade import obter_publicidade_diploma

logger = logging.getLogger(__name__)

# Tabela estática/temporária de patrocínios rotativos
# No futuro, pode ser puxada via supabase supabase.table("patrocinios")
PATROCINADORES = [
    {"nome": "Sind Ofícios", "link": "https://sindoficios.com.br", "tipo": "institucional"},
    {"nome": "📢 Sua Marca Aqui! Apoie o Bode", "link": "https://t.me/BodeAndarilhoBot?start=apoiar", "tipo": "campanha"},
    {"nome": "🤝 Divulgue seu negócio para a Irmandade!", "link": "https://t.me/BodeAndarilhoBot?start=apoiar", "tipo": "campanha"},
    {"nome": "🐐 Fortaleça nosso Templo Digital! Seja Apoiador", "link": "https://t.me/BodeAndarilhoBot?start=apoiar", "tipo": "campanha"},
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

async def mostrar_publicidade_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Tela administrativa simples para visualizar a publicidade configurada."""
    query = update.callback_query
    if query:
        try:
            await query.answer()
        except Exception:
            pass

    from src.permissoes import get_nivel

    user_id = update.effective_user.id
    if get_nivel(user_id) != "3":
        await navegar_para(
            update,
            context,
            "Publicidade/Apoiadores",
            "⛔ Esta área é exclusiva para administradores.",
            InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Voltar", callback_data="menu_principal")]]),
        )
        return

    publicidade = obter_publicidade_diploma()
    status_imagem = "Configurada" if publicidade.get("imagem") else "Usando peça de exemplo"
    texto = (
        "📢 *Publicidade/Apoiadores*\n\n"
        "A publicidade visual do diploma usa um espaço discreto no rodapé da página de conquistas.\n\n"
        f"*Peça atual:* {publicidade['nome']}\n"
        f"*Status da imagem:* {status_imagem}\n"
        f"*Mensagem:* {publicidade['mensagem']}\n\n"
        "Para substituir a peça de exemplo neste ciclo, inclua uma imagem aprovada em "
        "`assets/branding/sponsor_sindoficios.png`."
    )
    teclado = InlineKeyboardMarkup([
        [InlineKeyboardButton("🤝 Ver apoio institucional", callback_data="apoiar_menu")],
        [InlineKeyboardButton("🔙 Voltar ao admin", callback_data="area_admin")],
    ])
    await navegar_para(update, context, "Publicidade/Apoiadores", texto, teclado)


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
    application.add_handler(CallbackQueryHandler(mostrar_publicidade_admin, pattern="^admin_publicidade$"))
    application.add_handler(CallbackQueryHandler(mostrar_pix, pattern="^mostrar_pix$"))
    application.add_handler(CallbackQueryHandler(mostrar_lojinha, pattern="^mostrar_lojinha$"))
