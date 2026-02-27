# src/cadastro_evento.py
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler, MessageHandler, CommandHandler, filters, CallbackQueryHandler
from src.sheets import cadastrar_evento, listar_eventos
from src.permissoes import get_nivel
from datetime import datetime
import os
import re
import urllib.parse

# ID DO GRUPO PRINCIPAL
GRUPO_PRINCIPAL_ID = os.getenv("GRUPO_PRINCIPAL_ID", "-1003721338228")

# Estados da conversação para o cadastro de evento
DATA, HORARIO, NOME_LOJA, NUMERO_LOJA, ORIENTE, GRAU, TIPO_SESSAO, RITO, POTENCIA, TRAJE, AGAPE, AGAPE_TIPO, OBSERVACOES_TEM, OBSERVACOES_TEXTO, ENDERECO, CONFIRMAR = range(16)

# Valores que indicam "não informado"
VALORES_NAO_INFORMADO = ["", "N/A", "n/a", "nao", "não", "n", "N", "0", "A", "a"]

async def novo_evento_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Inicia o cadastro de evento, com verificação de permissão."""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    nivel = get_nivel(user_id)

    if nivel not in ["2", "3"]:
        await query.edit_message_text("Você não tem permissão para cadastrar eventos.")
        return ConversationHandler.END

    # Armazena o ID do usuário que está cadastrando
    context.user_data["novo_evento_telegram_id_secretario"] = str(user_id)

    # Se veio do grupo, captura ID mas não mostra
    if update.effective_chat.type in ["group", "supergroup"]:
        context.user_data["novo_evento_telegram_id_grupo"] = str(update.effective_chat.id)
        await query.edit_message_text(
            "🔔 O cadastro de eventos deve ser feito no meu chat privado.\n\n"
            "Por favor, acesse meu privado clicando no meu nome e utilize o menu 'Área do Secretário' para cadastrar."
        )
        return ConversationHandler.END

    # Se está em privado, define grupo principal automaticamente
    context.user_data["novo_evento_telegram_id_grupo"] = GRUPO_PRINCIPAL_ID

    # Inicia o cadastro
    await query.edit_message_text(
        "Certo, vamos cadastrar um novo evento.\n\nQual a *Data do evento*? (Ex: 25/03/2026)",
        parse_mode="Markdown"
    )
    return DATA

async def receber_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data_text = update.message.text.strip()
    try:
        data_obj = datetime.strptime(data_text, "%d/%m/%Y")
        hoje = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        if data_obj < hoje:
            await update.message.reply_text("A data não pode ser no passado. Por favor, informe uma data futura (Ex: 25/03/2026).")
            return DATA
    except ValueError:
        await update.message.reply_text("Formato inválido. Use DD/MM/AAAA (Ex: 25/03/2026).")
        return DATA

    context.user_data["novo_evento_data"] = data_text
    await update.message.reply_text("Qual o *Horário do evento*? (Ex: 19:30)", parse_mode="Markdown")
    return HORARIO

async def receber_horario(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
            [InlineKeyboardButton("Pago (dividido entre irmãos)", callback_data="agape_pago")]
        ])
        await query.edit_message_text(
            "O Ágape será *Gratuito* ou *Pago*?",
            parse_mode="Markdown",
            reply_markup=teclado_tipo_agape
        )
        return AGAPE_TIPO
    elif resposta_agape == "nao":
        context.user_data["novo_evento_agape"] = "Não"
        context.user_data["novo_evento_agape_tipo"] = "N/A"
        # 🔥 CORREÇÃO: Pergunta se tem observações com botões
        teclado_obs = InlineKeyboardMarkup([
            [InlineKeyboardButton("Sim", callback_data="obs_sim")],
            [InlineKeyboardButton("Não", callback_data="obs_nao")]
        ])
        await query.edit_message_text(
            "Deseja adicionar alguma *Observação*?",
            parse_mode="Markdown",
            reply_markup=teclado_obs
        )
        return OBSERVACOES_TEM
    else:
        await query.edit_message_text("Opção inválida para Ágape. Por favor, selecione 'Sim' ou 'Não'.")
        return AGAPE

async def receber_agape_tipo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    tipo_agape = query.data.split("_")[1]

    if tipo_agape == "gratuito":
        context.user_data["novo_evento_agape_tipo"] = "Gratuito"
    elif tipo_agape == "pago":
        context.user_data["novo_evento_agape_tipo"] = "Pago (dividido)"
    else:
        await query.edit_message_text("Opção inválida para tipo de Ágape. Por favor, selecione 'Gratuito' ou 'Pago'.")
        return AGAPE_TIPO

    # 🔥 CORREÇÃO: Pergunta se tem observações com botões
    teclado_obs = InlineKeyboardMarkup([
        [InlineKeyboardButton("Sim", callback_data="obs_sim")],
        [InlineKeyboardButton("Não", callback_data="obs_nao")]
    ])
    await query.edit_message_text(
        "Deseja adicionar alguma *Observação*?",
        parse_mode="Markdown",
        reply_markup=teclado_obs
    )
    return OBSERVACOES_TEM

async def receber_observacoes_tem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Processa a resposta sobre se há observações."""
    query = update.callback_query
    await query.answer()
    
    resposta = query.data
    if resposta == "obs_sim":
        await query.edit_message_text(
            "Por favor, digite a *Observação* do evento:",
            parse_mode="Markdown"
        )
        return OBSERVACOES_TEXTO
    else:  # obs_nao
        context.user_data["novo_evento_observacoes"] = "N/A"
        await query.edit_message_text("Qual o *Endereço da sessão*?", parse_mode="Markdown")
        return ENDERECO

async def receber_observacoes_texto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recebe o texto da observação."""
    context.user_data["novo_evento_observacoes"] = update.message.text
    await update.message.reply_text("Qual o *Endereço da sessão*?", parse_mode="Markdown")
    return ENDERECO

async def receber_endereco(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recebe o endereço e mostra resumo para confirmação."""
    context.user_data["novo_evento_endereco"] = update.message.text

    # Monta o resumo do evento
    agape_final = context.user_data["novo_evento_agape"]
    if agape_final == "Sim":
        agape_final += f" ({context.user_data.get('novo_evento_agape_tipo', 'N/A')})"

    # Traduzir dia da semana para o resumo
    try:
        data_obj = datetime.strptime(context.user_data["novo_evento_data"], "%d/%m/%Y")
        dia_semana_ingles = data_obj.strftime("%A")
        dias = {
            "Monday": "Segunda-feira", "Tuesday": "Terça-feira", "Wednesday": "Quarta-feira",
            "Thursday": "Quinta-feira", "Friday": "Sexta-feira", "Saturday": "Sábado", "Sunday": "Domingo"
        }
        dia_semana_pt = dias.get(dia_semana_ingles, dia_semana_ingles)
    except:
        dia_semana_pt = "Inválido"

    resumo = (
        f"📋 *RESUMO DO EVENTO*\n\n"
        f"📅 Data: {context.user_data['novo_evento_data']} ({dia_semana_pt})\n"
        f"🕕 Horário: {context.user_data['novo_evento_horario']}\n"
        f"🏛 Loja: {context.user_data['novo_evento_nome_loja']} {context.user_data['novo_evento_numero_loja']}\n"
        f"📍 Oriente: {context.user_data['novo_evento_oriente']}\n"
        f"⚜️ Potência: {context.user_data['novo_evento_potencia']}\n"
        f"🔷 Grau mínimo: {context.user_data['novo_evento_grau']}\n"
        f"📋 Tipo: {context.user_data['novo_evento_tipo_sessao']}\n"
        f"✡️ Rito: {context.user_data['novo_evento_rito']}\n"
        f"👔 Traje: {context.user_data['novo_evento_traje']}\n"
        f"🍽 Ágape: {agape_final}\n"
        f"📌 Obs: {context.user_data['novo_evento_observacoes']}\n"
        f"📍 Endereço: {context.user_data['novo_evento_endereco']}\n\n"
        f"*Tudo certo?*"
    )

    botoes = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Sim, publicar", callback_data="confirmar_publicacao")],
        [InlineKeyboardButton("🔄 Refazer cadastro", callback_data="refazer_cadastro")],
        [InlineKeyboardButton("❌ Cancelar", callback_data="cancelar_publicacao")]
    ])

    await update.message.reply_text(resumo, parse_mode="Markdown", reply_markup=botoes)
    return CONFIRMAR

async def confirmar_publicacao(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Confirma e publica o evento."""
    query = update.callback_query
    await query.answer()

    agape_final = context.user_data["novo_evento_agape"]
    if agape_final == "Sim":
        agape_final += f" ({context.user_data.get('novo_evento_agape_tipo', 'N/A')})"

    dados_evento = {
        "data": context.user_data["novo_evento_data"],
        "dia_semana": "",
        "hora": context.user_data["novo_evento_horario"],
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
        "telegram_id_grupo": context.user_data.get("novo_evento_telegram_id_grupo", GRUPO_PRINCIPAL_ID),
        "telegram_id_secretario": context.user_data.get("novo_evento_telegram_id_secretario", ""),
        "endereco": context.user_data["novo_evento_endereco"],
        "status": "Ativo",
    }

    try:
        data_obj = datetime.strptime(dados_evento["data"], "%d/%m/%Y")
        dados_evento["dia_semana"] = data_obj.strftime("%A")
    except ValueError:
        dados_evento["dia_semana"] = "Inválido"

    # Salva o evento na planilha
    cadastrar_evento(dados_evento)

    # Publica no grupo principal
    grupo_id_int = int(GRUPO_PRINCIPAL_ID)
    
    # Traduzir dia da semana
    dias = {
        "Monday": "Segunda-feira", "Tuesday": "Terça-feira", "Wednesday": "Quarta-feira",
        "Thursday": "Quinta-feira", "Friday": "Sexta-feira", "Saturday": "Sábado", "Sunday": "Domingo"
    }
    dia_semana_pt = dias.get(dados_evento['dia_semana'], dados_evento['dia_semana'])

    # 🔥 CORREÇÃO: Callback_data sem caracteres especiais
    id_evento = f"{dados_evento['data']} — {dados_evento['nome_loja']}"
    id_evento_codificado = urllib.parse.quote(id_evento, safe='')

    # Determinar botões baseado no tipo de ágape
    agape_texto = dados_evento['agape'].lower()
    if "pago" in agape_texto or "dividido" in agape_texto:
        botoes = [
            [InlineKeyboardButton("🍽 Participar com ágape (pago)", callback_data=f"confirmar|{id_evento_codificado}|pago")],
            [InlineKeyboardButton("🚫 Participar sem ágape", callback_data=f"confirmar|{id_evento_codificado}|sem")],
        ]
    elif "gratuito" in agape_texto:
        botoes = [
            [InlineKeyboardButton("🍽 Participar com ágape (gratuito)", callback_data=f"confirmar|{id_evento_codificado}|gratuito")],
            [InlineKeyboardButton("🚫 Participar sem ágape", callback_data=f"confirmar|{id_evento_codificado}|sem")],
        ]
    else:  # sem ágape
        botoes = [
            [InlineKeyboardButton("✅ Confirmar presença", callback_data=f"confirmar|{id_evento_codificado}|sem")],
        ]
    botoes.append([InlineKeyboardButton("👥 Ver confirmados", callback_data=f"ver_confirmados|{id_evento_codificado}")])

    mensagem_grupo = (
        f"🐐 *Nova sessão disponível para visitas!*\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"🏛 *LOJA {dados_evento['nome_loja']} {dados_evento['numero_loja']}*\n"
        f"━━━━━━━━━━━━━━━━\n\n"
        f"📍 Oriente: {dados_evento['oriente']}\n"
        f"⚜️ Potência: {dados_evento['potencia']}\n"
        f"📅 Data: {dados_evento['data']} ({dia_semana_pt})\n"
        f"🕕 Horário: {dados_evento['hora']}\n"
        f"🕯 Tipo de sessão: {dados_evento['tipo_sessao']}\n"
        f"📖 Rito: {dados_evento['rito']}\n"
        f"🔺 Grau mínimo: {dados_evento['grau']}\n"
        f"👔 Traje: {dados_evento['traje']}\n"
        f"🍽 Ágape: {dados_evento['agape']}\n"
    )

    if dados_evento['observacoes'] and dados_evento['observacoes'] not in ["N/A", "n/a"]:
        mensagem_grupo += f"\n📌 Observações: {dados_evento['observacoes']}"

    await context.bot.send_message(
        chat_id=grupo_id_int,
        text=mensagem_grupo,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(botoes)
    )

    print(f"✅ Evento publicado no grupo {grupo_id_int}")
    await query.edit_message_text("✅ Evento cadastrado e publicado no grupo com sucesso!\n\nUse /start para voltar ao menu principal.")

    # Limpa dados da sessão
    context.user_data.clear()
    return ConversationHandler.END

async def refazer_cadastro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reinicia o cadastro do zero."""
    query = update.callback_query
    await query.answer()
    
    # Limpa dados anteriores mas mantém o ID do grupo
    grupo_id = context.user_data.get("novo_evento_telegram_id_grupo", GRUPO_PRINCIPAL_ID)
    secretario_id = context.user_data.get("novo_evento_telegram_id_secretario", "")
    
    context.user_data.clear()
    context.user_data["novo_evento_telegram_id_grupo"] = grupo_id
    context.user_data["novo_evento_telegram_id_secretario"] = secretario_id
    
    await query.edit_message_text(
        "Vamos recomeçar o cadastro.\n\nQual a *Data do evento*? (Ex: 25/03/2026)",
        parse_mode="Markdown"
    )
    return DATA

async def cancelar_publicacao(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancela todo o processo."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Cadastro cancelado. Use /start para voltar ao menu principal.")
    context.user_data.clear()
    return ConversationHandler.END

async def cancelar_cadastro_evento(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Cadastro de evento cancelado. Use /start para voltar ao menu principal.")
    context.user_data.clear()
    return ConversationHandler.END

cadastro_evento_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(novo_evento_start, pattern="^cadastrar_evento$")],
    states={
        DATA: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_data)],
        HORARIO: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_horario)],
        NOME_LOJA: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_nome_loja)],
        NUMERO_LOJA: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_numero_loja)],
        ORIENTE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_oriente)],
        GRAU: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_grau)],
        TIPO_SESSAO: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_tipo_sessao)],
        RITO: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_rito)],
        POTENCIA: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_potencia)],
        TRAJE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_traje)],
        AGAPE: [CallbackQueryHandler(receber_agape, pattern="^agape_(sim|nao)$")],
        AGAPE_TIPO: [CallbackQueryHandler(receber_agape_tipo, pattern="^agape_(gratuito|pago)$")],
        OBSERVACOES_TEM: [CallbackQueryHandler(receber_observacoes_tem, pattern="^(obs_sim|obs_nao)$")],
        OBSERVACOES_TEXTO: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_observacoes_texto)],
        ENDERECO: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_endereco)],
        CONFIRMAR: [
            CallbackQueryHandler(confirmar_publicacao, pattern="^confirmar_publicacao$"),
            CallbackQueryHandler(refazer_cadastro, pattern="^refazer_cadastro$"),
            CallbackQueryHandler(cancelar_publicacao, pattern="^cancelar_publicacao$")
        ],
    },
    fallbacks=[CommandHandler("cancelar", cancelar_cadastro_evento)],
)