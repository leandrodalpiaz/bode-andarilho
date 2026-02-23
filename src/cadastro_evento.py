from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, ConversationHandler, CallbackQueryHandler,
    MessageHandler, filters
)
from src.sheets import cadastrar_evento
from src.permissoes import get_nivel
from datetime import datetime

(
    CEV_NOME_LOJA, CEV_NUMERO_LOJA, CEV_ORIENTE, CEV_GRAU,
    CEV_TIPO_SESSAO, CEV_RITO, CEV_POTENCIA, CEV_TRAJE,
    CEV_ENDERECO, CEV_AGAPE, CEV_AGAPE_GRATUITO,
    CEV_AGAPE_VALOR, CEV_OBSERVACOES, CEV_CONFIRMACAO,
    CEV_DATA
) = range(15)

FRASE_AGAPE = (
    "Sua confirmação nos ajuda a organizar melhor o ágape e evitar desperdícios. "
    "Caso não possa comparecer, por favor cancele sua presença com antecedência. "
    "Obrigado, irmão!"
)

DIAS_SEMANA = {
    0: "Segunda-feira",
    1: "Terça-feira",
    2: "Quarta-feira",
    3: "Quinta-feira",
    4: "Sexta-feira",
    5: "Sábado",
    6: "Domingo"
}

def formatar_resumo(d: dict) -> str:
    agape_info = d.get("agape", "Não")
    if agape_info == "Sim - Gratuito":
        agape_texto = "Sim (Gratuito)"
    elif agape_info.startswith("Sim - R$"):
        agape_texto = f"Sim ({agape_info.replace('Sim - ', '')})"
    elif agape_info == "Sim - Dividido no local":
        agape_texto = "Sim (Dividido no local)"
    else:
        agape_texto = "Não"

    return (
        f"📋 *Resumo do evento*\n\n"
        f"📅 Data: {d.get('data', '')}\n"
        f"📆 Dia: {d.get('dia_semana', '')}\n"
        f"🏛️ Loja: {d.get('nome_loja', '')} nº {d.get('numero_loja', '')}\n"
        f"📍 Oriente: {d.get('oriente', '')}\n"
        f"🎓 Grau: {d.get('grau', '')}\n"
        f"📌 Tipo: {d.get('tipo_sessao', '')}\n"
        f"⚜️ Rito: {d.get('rito', '')}\n"
        f"🏛️ Potência: {d.get('potencia', '')}\n"
        f"👔 Traje: {d.get('traje', '')}\n"
        f"🍽️ Ágape: {agape_texto}\n"
        f"📍 Endereço: {d.get('endereco', '')}\n"
        f"📝 Observações: {d.get('observacoes', '')}\n\n"
        f"Confirma o cadastro?"
    )

async def iniciar_cadastro_evento(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    telegram_id = update.effective_user.id
    if get_nivel(telegram_id) not in ["secretario", "admin"]:
        await query.edit_message_text("Você não tem permissão para cadastrar eventos.")
        return ConversationHandler.END

    context.user_data.clear()
    context.user_data["cadastro_evento"] = {}

    await query.edit_message_text(
        "📅 *Cadastrar novo evento*\n\n"
        "Qual é a data do evento?\n"
        "_(ex: 25/03 ou 25-03)_",
        parse_mode="Markdown"
    )
    return CEV_DATA

async def receber_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text.strip()
    texto = texto.replace("-", "/")

    partes = texto.split("/")
    if len(partes) < 2:
        await update.message.reply_text("Data inválida. Por favor informe no formato dd/mm ou dd-mm.")
        return CEV_DATA

    try:
        dia = int(partes[0])
        mes = int(partes[1])
        ano = datetime.now().year
        data_obj = datetime(ano, mes, dia)
        data_formatada = data_obj.strftime("%d/%m/%Y")
        dia_semana = DIAS_SEMANA[data_obj.weekday()]
    except Exception:
        await update.message.reply_text("Data inválida. Por favor informe no formato dd/mm ou dd-mm.")
        return CEV_DATA

    context.user_data["cadastro_evento"]["data"] = data_formatada
    context.user_data["cadastro_evento"]["dia_semana"] = dia_semana

    await update.message.reply_text(
        f"📆 Dia da semana: *{dia_semana}*\n\nQual é o nome da loja?",
        parse_mode="Markdown"
    )
    return CEV_NOME_LOJA

async def receber_nome_loja(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["cadastro_evento"]["nome_loja"] = update.message.text.strip()
    await update.message.reply_text("Qual é o número da loja?")
    return CEV_NUMERO_LOJA

async def receber_numero_loja(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["cadastro_evento"]["numero_loja"] = update.message.text.strip()
    await update.message.reply_text("Qual é o oriente? (cidade)")
    return CEV_ORIENTE

async def receber_oriente(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["cadastro_evento"]["oriente"] = update.message.text.strip()

    teclado = InlineKeyboardMarkup([
        [InlineKeyboardButton("Aprendiz", callback_data="grau_Aprendiz")],
        [InlineKeyboardButton("Companheiro", callback_data="grau_Companheiro")],
        [InlineKeyboardButton("Mestre", callback_data="grau_Mestre")],
    ])
    await update.message.reply_text("Qual é o grau da sessão?", reply_markup=teclado)
    return CEV_GRAU

async def receber_grau(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    grau = query.data.replace("grau_", "")
    context.user_data["cadastro_evento"]["grau"] = grau

    teclado = InlineKeyboardMarkup([
        [InlineKeyboardButton("Ordinária", callback_data="tipo_Ordinária")],
        [InlineKeyboardButton("Magna", callback_data="tipo_Magna")],
        [InlineKeyboardButton("Iniciação", callback_data="tipo_Iniciação")],
        [InlineKeyboardButton("Especial", callback_data="tipo_Especial")],
    ])
    await query.edit_message_text("Qual é o tipo de sessão?", reply_markup=teclado)
    return CEV_TIPO_SESSAO

async def receber_tipo_sessao(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    tipo = query.data.replace("tipo_", "")
    context.user_data["cadastro_evento"]["tipo_sessao"] = tipo

    teclado = InlineKeyboardMarkup([
        [InlineKeyboardButton("Escocês", callback_data="rito_Escocês")],
        [InlineKeyboardButton("York", callback_data="rito_York")],
        [InlineKeyboardButton("Brasileiro", callback_data="rito_Brasileiro")],
        [InlineKeyboardButton("Moderno", callback_data="rito_Moderno")],
        [InlineKeyboardButton("Schröder", callback_data="rito_Schröder")],
    ])
    await query.edit_message_text("Qual é o rito?", reply_markup=teclado)
    return CEV_RITO

async def receber_rito(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    rito = query.data.replace("rito_", "")
    context.user_data["cadastro_evento"]["rito"] = rito

    await query.edit_message_text("Qual é a potência? (ex: GOB, GLESP, COMAB...)")
    return CEV_POTENCIA

async def receber_potencia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["cadastro_evento"]["potencia"] = update.message.text.strip()

    teclado = InlineKeyboardMarkup([
        [InlineKeyboardButton("Traje escuro", callback_data="traje_Traje escuro")],
        [InlineKeyboardButton("Terno e gravata", callback_data="traje_Terno e gravata")],
        [InlineKeyboardButton("Traje a rigor", callback_data="traje_Traje a rigor")],
        [InlineKeyboardButton("Casual", callback_data="traje_Casual")],
    ])
    await update.message.reply_text("Qual é o traje obrigatório?", reply_markup=teclado)
    return CEV_TRAJE

async def receber_traje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    traje = query.data.replace("traje_", "")
    context.user_data["cadastro_evento"]["traje"] = traje

    await query.edit_message_text("Qual é o endereço da sessão?")
    return CEV_ENDERECO

async def receber_endereco(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["cadastro_evento"]["endereco"] = update.message.text.strip()

    teclado = InlineKeyboardMarkup([
        [InlineKeyboardButton("Sim", callback_data="agape_sim"),
         InlineKeyboardButton("Não", callback_data="agape_nao")],
    ])
    await update.message.reply_text("Haverá ágape?", reply_markup=teclado)
    return CEV_AGAPE

async def receber_agape(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "agape_nao":
        context.user_data["cadastro_evento"]["agape"] = "Não"
        await query.edit_message_text("Deseja adicionar alguma observação? (ou envie — para pular)")
        return CEV_OBSERVACOES

    teclado = InlineKeyboardMarkup([
        [InlineKeyboardButton("Sim, gratuito", callback_data="gratuito_sim"),
         InlineKeyboardButton("Não, será cobrado", callback_data="gratuito_nao")],
    ])
    await query.edit_message_text("O ágape será gratuito?", reply_markup=teclado)
    return CEV_AGAPE_GRATUITO

async def receber_agape_gratuito(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "gratuito_sim":
        context.user_data["cadastro_evento"]["agape"] = "Sim - Gratuito"
        obs_base = FRASE_AGAPE
        context.user_data["cadastro_evento"]["observacoes"] = obs_base
        await query.edit_message_text(
            f"✅ Ágape gratuito registrado.\n\n"
            f"A seguinte observação será incluída automaticamente:\n\n"
            f"_{obs_base}_\n\n"
            f"Deseja acrescentar algo? (ou envie — para manter apenas esta mensagem)",
            parse_mode="Markdown"
        )
        return CEV_OBSERVACOES

    teclado = InlineKeyboardMarkup([
        [InlineKeyboardButton("💰 Valor fixo", callback_data="pgto_valor")],
        [InlineKeyboardButton("➗ Dividido no local", callback_data="pgto_divisao")],
    ])
    await query.edit_message_text("Como será o pagamento do ágape?", reply_markup=teclado)
    return CEV_AGAPE_VALOR

async def receber_agape_valor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "pgto_divisao":
        context.user_data["cadastro_evento"]["agape"] = "Sim - Dividido no local"
        obs_base = FRASE_AGAPE
        context.user_data["cadastro_evento"]["observacoes"] = obs_base
        await query.edit_message_text(
            f"✅ Ágape dividido no local registrado.\n\n"
            f"A seguinte observação será incluída automaticamente:\n\n"
            f"_{obs_base}_\n\n"
            f"Deseja acrescentar algo? (ou envie — para manter apenas esta mensagem)",
            parse_mode="Markdown"
        )
        return CEV_OBSERVACOES

    await query.edit_message_text("Qual é o valor do ágape? (ex: R$ 35,00)")
    return CEV_AGAPE_VALOR

async def receber_valor_agape(update: Update, context: ContextTypes.DEFAULT_TYPE):
    valor = update.message.text.strip()
    context.user_data["cadastro_evento"]["agape"] = f"Sim - R$ {valor}"
    obs_base = FRASE_AGAPE
    context.user_data["cadastro_evento"]["observacoes"] = obs_base
    await update.message.reply_text(
        f"✅ Valor registrado.\n\n"
        f"A seguinte observação será incluída automaticamente:\n\n"
        f"_{obs_base}_\n\n"
        f"Deseja acrescentar algo? (ou envie — para manter apenas esta mensagem)",
        parse_mode="Markdown"
    )
    return CEV_OBSERVACOES

async def receber_observacoes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text.strip()
    obs_base = context.user_data["cadastro_evento"].get("observacoes", "")

    if texto == "—" or texto == "-":
        obs_final = obs_base
    else:
        obs_final = f"{obs_base} {texto}".strip() if obs_base else texto

    context.user_data["cadastro_evento"]["observacoes"] = obs_final

    resumo = formatar_resumo(context.user_data["cadastro_evento"])
    teclado = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Confirmar", callback_data="cev_confirmar"),
         InlineKeyboardButton("❌ Cancelar", callback_data="cev_cancelar")],
    ])
    await update.message.reply_text(resumo, parse_mode="Markdown", reply_markup=teclado)
    return CEV_CONFIRMACAO

async def confirmar_cadastro_evento(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "cev_cancelar":
        await query.edit_message_text("❌ Cadastro cancelado.")
        return ConversationHandler.END

    dados = context.user_data["cadastro_evento"]
    telegram_id = update.effective_user.id

    evento = {
        "data": dados.get("data", ""),
        "dia_semana": dados.get("dia_semana", ""),
        "nome_loja": dados.get("nome_loja", ""),
        "numero_loja": dados.get("numero_loja", ""),
        "oriente": dados.get("oriente", ""),
        "grau": dados.get("grau", ""),
        "tipo_sessao": dados.get("tipo_sessao", ""),
        "rito": dados.get("rito", ""),
        "potencia": dados.get("potencia", ""),
        "traje": dados.get("traje", ""),
        "agape": dados.get("agape", "Não"),
        "observacoes": dados.get("observacoes", ""),
        "telegram_id_grupo": "",
        "telegram_id_secretario": str(telegram_id),
        "status": "Ativo",
        "endereco": dados.get("endereco", ""),
    }

    cadastrar_evento(evento)

    await query.edit_message_text(
        "✅ *Evento cadastrado com sucesso!*\n\n"
        "O evento já está disponível para os membros.",
        parse_mode="Markdown"
    )
    return ConversationHandler.END

cadastro_evento_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(iniciar_cadastro_evento, pattern="^cadastrar_evento$")],
    states={
        CEV_DATA: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_data)],
        CEV_NOME_LOJA: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_nome_loja)],
        CEV_NUMERO_LOJA: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_numero_loja)],
        CEV_ORIENTE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_oriente)],
        CEV_GRAU: [CallbackQueryHandler(receber_grau, pattern="^grau_")],
        CEV_TIPO_SESSAO: [CallbackQueryHandler(receber_tipo_sessao, pattern="^tipo_")],
        CEV_RITO: [CallbackQueryHandler(receber_rito, pattern="^rito_")],
        CEV_POTENCIA: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_potencia)],
        CEV_TRAJE: [CallbackQueryHandler(receber_traje, pattern="^traje_")],
        CEV_ENDERECO: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_endereco)],
        CEV_AGAPE: [CallbackQueryHandler(receber_agape, pattern="^agape_")],
        CEV_AGAPE_GRATUITO: [CallbackQueryHandler(receber_agape_gratuito, pattern="^gratuito_")],
        CEV_AGAPE_VALOR: [
            CallbackQueryHandler(receber_agape_valor, pattern="^pgto_"),
            MessageHandler(filters.TEXT & ~filters.COMMAND, receber_valor_agape),
        ],
        CEV_OBSERVACOES: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_observacoes)],
        CEV_CONFIRMACAO: [CallbackQueryHandler(confirmar_cadastro_evento, pattern="^cev_")],
    },
    fallbacks=[],
    allow_reentry=True
)
