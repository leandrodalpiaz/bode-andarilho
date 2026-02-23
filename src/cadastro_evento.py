# src/cadastro_evento.py
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler, MessageHandler, CommandHandler, filters, CallbackQueryHandler
from src.sheets import cadastrar_evento
from datetime import datetime
import os

# Estados da conversação para o cadastro de evento
DATA, HORARIO, NOME_LOJA, NUMERO_LOJA, ORIENTE, GRAU, TIPO_SESSAO, RITO, POTENCIA, TRAJE, AGAPE, AGAPE_TIPO, OBSERVACOES, ID_GRUPO, ID_SECRETARIO, ENDERECO = range(16) # HORARIO adicionado, range ajustado

async def novo_evento_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_id = os.getenv("ADMIN_TELEGRAM_ID")
    if admin_id and str(update.effective_user.id) != admin_id:
        await update.callback_query.edit_message_text("Você não tem permissão para cadastrar eventos.")
        return ConversationHandler.END

    await update.callback_query.answer()
    await update.callback_query.edit_message_text("Certo, vamos cadastrar um novo evento.\n\nQual a *Data do evento*? (Ex: 25/03/2026)", parse_mode="Markdown")
    return DATA

async def receber_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["novo_evento_data"] = update.message.text
    await update.message.reply_text("Qual o *Horário do evento*? (Ex: 19:30)", parse_mode="Markdown") # Nova pergunta
    return HORARIO # Novo estado

async def receber_horario(update: Update, context: ContextTypes.DEFAULT_TYPE): # Nova função
    context.user_data["novo_evento_horario"] = update.message.text
    await update.message.reply_text("Qual o *Nome da loja*?", parse_mode="Markdown")
    return NOME_LOJA

async def receber_nome_loja(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["novo_evento_nome_loja"] = update.message.text
    await update.message.reply_text("Qual o *Número da loja*?", parse_mode="Markdown")
    return NUMERO_LOJA

async def receber_numero_loja(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["novo_evento_numero_loja"] = update.message.text
    await update.message.reply_text("Qual o *Oriente*?", parse_mode="Markdown")
    return ORIENTE

async def receber_oriente(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["novo_evento_oriente"] = update.message.text
    await update.message.reply_text("Qual o *Grau mínimo* para o evento?", parse_mode="Markdown")
    return GRAU

async def receber_grau(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["novo_evento_grau"] = update.message.text
    await update.message.reply_text("Qual o *Tipo de sessão*? (Ex: Ordinária, Magna)", parse_mode="Markdown")
    return TIPO_SESSAO

async def receber_tipo_sessao(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["novo_evento_tipo_sessao"] = update.message.text
    await update.message.reply_text("Qual o *Rito*?", parse_mode="Markdown")
    return RITO

async def receber_rito(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["novo_evento_rito"] = update.message.text
    await update.message.reply_text("Qual a *Potência*?", parse_mode="Markdown")
    return POTENCIA

async def receber_potencia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["novo_evento_potencia"] = update.message.text
    await update.message.reply_text("Qual o *Traje obrigatório*?", parse_mode="Markdown")
    return TRAJE

async def receber_traje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["novo_evento_traje"] = update.message.text

    teclado_agape = InlineKeyboardMarkup([
        [InlineKeyboardButton("Sim", callback_data="agape_sim")],
        [InlineKeyboardButton("Não", callback_data="agape_nao")]
    ])
    await update.message.reply_text("Haverá *Ágape*?", parse_mode="Markdown", reply_markup=teclado_agape)
    return AGAPE

async def receber_agape(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    resposta_agape = query.data.split("_")[1]

    if resposta_agape == "sim":
        context.user_data["novo_evento_agape"] = "Sim"
        teclado_tipo_agape = InlineKeyboardMarkup([
            [InlineKeyboardButton("Gratuito", callback_data="agape_gratuito")],
            [InlineKeyboardButton("Dividido entre os Irmãos", callback_data="agape_dividido")]
        ])
        await query.edit_message_text("O Ágape será *Gratuito* ou *Dividido entre os Irmãos*?", parse_mode="Markdown", reply_markup=teclado_tipo_agape)
        return AGAPE_TIPO
    elif resposta_agape == "nao":
        context.user_data["novo_evento_agape"] = "Não"
        context.user_data["novo_evento_agape_tipo"] = "N/A"
        await query.edit_message_text("Certo. Alguma *Observação*? (Se não houver, digite 'N/A')", parse_mode="Markdown")
        return OBSERVACOES
    else:
        await query.edit_message_text("Opção inválida para Ágape. Por favor, selecione 'Sim' ou 'Não'.")
        return AGAPE

async def receber_agape_tipo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    tipo_agape = query.data.split("_")[1]

    if tipo_agape == "gratuito":
        context.user_data["novo_evento_agape_tipo"] = "Gratuito"
    elif tipo_agape == "dividido":
        context.user_data["novo_evento_agape_tipo"] = "Dividido entre os Irmãos"
    else:
        await query.edit_message_text("Opção inválida para tipo de Ágape. Por favor, selecione 'Gratuito' ou 'Dividido'.")
        return AGAPE_TIPO

    await query.edit_message_text("Certo. Alguma *Observação*? (Se não houver, digite 'N/A')", parse_mode="Markdown")
    return OBSERVACOES

async def receber_observacoes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["novo_evento_observacoes"] = update.message.text
    await update.message.reply_text("Qual o *Telegram ID do grupo* do evento? (Se não houver, digite 'N/A')", parse_mode="Markdown")
    return ID_GRUPO

async def receber_id_grupo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["novo_evento_telegram_id_grupo"] = update.message.text
    await update.message.reply_text("Qual o *Telegram ID do secretário* responsável? (Se não houver, digite 'N/A')", parse_mode="Markdown")
    return ID_SECRETARIO

async def receber_id_secretario(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["novo_evento_telegram_id_secretario"] = update.message.text
    await update.message.reply_text("Qual o *Endereço da sessão*?", parse_mode="Markdown")
    return ENDERECO

async def finalizar_cadastro_evento(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["novo_evento_endereco"] = update.message.text

    agape_final = context.user_data["novo_evento_agape"]
    if agape_final == "Sim":
        agape_final += f" ({context.user_data.get('novo_evento_agape_tipo', 'N/A')})"

    dados_evento = {
        "data": context.user_data["novo_evento_data"],
        "dia_semana": "",
        "hora": context.user_data["novo_evento_horario"], # Campo "hora" adicionado
        "nome_loja": context.user_data["novo_evento_nome_loja"],
        "numero_loja": context.user_data["novo_evento_numero_loja"],
        "oriente": context.user_data["novo_evento_oriente"],
        "grau": context.user_data["novo_evento_grau"],
        "tipo_sessao": context.user_data["novo_evento_tipo_sessao"],
        "rito": context.user_data["novo_evento_rito"],
        "potencia": context.user_data["novo_evento_potencia"],
        "traje": context.user_data["novo_evento_traje"],
        "agape": agape_final,
        "observacoes": context.user_data["novo_evento_observacoes"],
        "telegram_id_grupo": context.user_data["novo_evento_telegram_id_grupo"],
        "telegram_id_secretario": context.user_data["novo_evento_telegram_id_secretario"],
        "endereco": context.user_data["novo_evento_endereco"],
        "status": "Ativo",
    }

    try:
        data_obj = datetime.strptime(dados_evento["data"], "%d/%m/%Y")
        dados_evento["dia_semana"] = data_obj.strftime("%A")
    except ValueError:
        dados_evento["dia_semana"] = "Inválido"

    cadastrar_evento(dados_evento)
    await update.message.reply_text("✅ Evento cadastrado com sucesso! Use /start para voltar ao menu principal.")
    return ConversationHandler.END

async def cancelar_cadastro_evento(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Cadastro de evento cancelado. Use /start para voltar ao menu principal.")
    return ConversationHandler.END

cadastro_evento_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(novo_evento_start, pattern="^cadastrar_evento$")],
    states={
        DATA: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_data)],
        HORARIO: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_horario)], # Novo estado
        NOME_LOJA: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_nome_loja)],
        NUMERO_LOJA: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_numero_loja)],
        ORIENTE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_oriente)],
        GRAU: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_grau)],
        TIPO_SESSAO: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_tipo_sessao)],
        RITO: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_rito)],
        POTENCIA: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_potencia)],
        TRAJE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_traje)],
        AGAPE: [CallbackQueryHandler(receber_agape, pattern="^agape_(sim|nao)$")],
        AGAPE_TIPO: [CallbackQueryHandler(receber_agape_tipo, pattern="^agape_(gratuito|dividido)$")],
        OBSERVACOES: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_observacoes)],
        ID_GRUPO: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_id_grupo)],
        ID_SECRETARIO: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_id_secretario)],
        ENDERECO: [MessageHandler(filters.TEXT & ~filters.COMMAND, finalizar_cadastro_evento)],
    },
    fallbacks=[CommandHandler("cancelar", cancelar_cadastro_evento)],
)
