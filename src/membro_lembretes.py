from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from src.bot import navegar_para, _enviar_ou_editar_mensagem, TIPO_RESULTADO
from src.sheets_supabase import get_preferencia_lembretes, set_notificacao_status


async def menu_lembretes_membro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    ativo = get_preferencia_lembretes(user_id)
    status_texto = "✅ Ativados" if ativo else "🔕 Desativados"

    teclado = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔔 Ativar lembretes", callback_data="lembretes_membro_ativar")],
        [InlineKeyboardButton("🔕 Desativar lembretes", callback_data="lembretes_membro_desativar")],
        [InlineKeyboardButton("🔙 Voltar ao menu", callback_data="menu_principal")],
    ])

    texto = (
        "🔔 *Meus Lembretes*\n\n"
        f"Status atual: {status_texto}\n\n"
        "Aqui você escolhe se deseja receber lembretes automáticos no privado "
        "para as sessões que confirmou.\n\n"
        "Quando ativados, o bot envia:\n"
        "• um lembrete na véspera da sessão\n"
        "• um aviso no dia da sessão ao meio-dia"
    )

    await navegar_para(update, context, "Meus Lembretes", texto, teclado)


async def lembretes_membro_ativar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if set_notificacao_status(user_id, True):
        await navegar_para(
            update,
            context,
            "Meus Lembretes",
            "✅ *Lembretes ativados com sucesso!*\n\n"
            "Você voltará a receber avisos privados das sessões que confirmar.",
            InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Voltar", callback_data="menu_lembretes")]
            ]),
        )
        return

    await _enviar_ou_editar_mensagem(
        context,
        user_id,
        TIPO_RESULTADO,
        "❌ *Erro ao ativar lembretes.*\n\nTente novamente em alguns instantes.",
        limpar_conteudo=True,
    )


async def lembretes_membro_desativar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if set_notificacao_status(user_id, False):
        await navegar_para(
            update,
            context,
            "Meus Lembretes",
            "🔕 *Lembretes desativados com sucesso!*\n\n"
            "Você deixará de receber avisos privados das sessões que confirmar.",
            InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Voltar", callback_data="menu_lembretes")]
            ]),
        )
        return

    await _enviar_ou_editar_mensagem(
        context,
        user_id,
        TIPO_RESULTADO,
        "❌ *Erro ao desativar lembretes.*\n\nTente novamente em alguns instantes.",
        limpar_conteudo=True,
    )
