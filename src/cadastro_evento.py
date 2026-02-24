# src/cadastro_evento.py
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler, MessageHandler, CommandHandler, filters, CallbackQueryHandler
from src.sheets import cadastrar_evento, listar_eventos, buscar_membro
from src.permissoes import get_nivel
from datetime import datetime
import os
import time

# Estados da conversação para o cadastro de evento
DATA, HORARIO, NOME_LOJA, NUMERO_LOJA, ORIENTE, GRAU, TIPO_SESSAO, RITO, POTENCIA, TRAJE, AGAPE, AGAPE_TIPO, OBSERVACOES, ENDERECO = range(14)

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

    # Armazena o ID do usuário que está cadastrando (será o secretário padrão)
    context.user_data["novo_evento_telegram_id_secretario"] = str(user_id)
    
    # Se a interação veio de um grupo, armazena o ID do grupo automaticamente
    if update.effective_chat.type in ["group", "supergroup"]:
        context.user_data["novo_evento_telegram_id_grupo"] = str(update.effective_chat.id)
        await query.edit_message_text(
            "O cadastro de eventos deve ser feito no meu chat privado. "
            "Por favor, acesse meu privado clicando no meu nome e utilize o menu 'Área do Secretário' para cadastrar.\n\n"
            f"✅ O ID do grupo ({update.effective_chat.id}) foi salvo automaticamente."
        )
        return ConversationHandler.END

    # Se está em privado, pergunta a data
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
            [InlineKeyboardButton("Dividido entre os Irmãos", callback_data="agape_dividido")]
        ])
        await query.edit_message_text(
            "O Ágape será *Gratuito* ou *Dividido entre os Irmãos*?",
            parse_mode="Markdown",
            reply_markup=teclado_tipo_agape
        )
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
    
    # Verifica se o ID do grupo já foi definido automaticamente
    if "novo_evento_telegram_id_grupo" not in context.user_data:
        await update.message.reply_text(
            "Qual o *Telegram ID do grupo* onde o evento será publicado?\n\n"
            "Para obter o ID, adicione o bot ao grupo e envie /id no grupo. "
            "Ou digite 'N/A' se não quiser publicar automaticamente.",
            parse_mode="Markdown"
        )
        return ID_GRUPO
    else:
        # Se já tem ID do grupo (veio do grupo), pula direto para endereço
        await update.message.reply_text("Qual o *Endereço da sessão*?", parse_mode="Markdown")
        return ENDERECO

async def receber_id_grupo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recebe o ID do grupo digitado pelo usuário."""
    id_grupo = update.message.text.strip()
    
    # Verifica se é um valor que indica "não informado"
    if id_grupo in VALORES_NAO_INFORMADO:
        context.user_data["novo_evento_telegram_id_grupo"] = ""
        await update.message.reply_text("OK. Nenhum grupo será usado para publicação.")
    else:
        context.user_data["novo_evento_telegram_id_grupo"] = id_grupo
    
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
        "telegram_id_grupo": context.user_data.get("novo_evento_telegram_id_grupo", ""),
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

    # Obtém a lista atualizada de eventos para encontrar o índice
    eventos = listar_eventos()
    indice_evento = 0
    for i, ev in enumerate(eventos):
        if (ev.get("Data do evento") == dados_evento["data"] and 
            ev.get("Nome da loja") == dados_evento["nome_loja"] and
            ev.get("Número da loja") == dados_evento["numero_loja"]):
            indice_evento = i
            break
    else:
        indice_evento = int(time.time())

    # Publicar o evento no grupo
    grupo_id = dados_evento.get("telegram_id_grupo", "").strip()
    
    # Se não tem grupo ou é valor inválido, não publica
    if not grupo_id or grupo_id in VALORES_NAO_INFORMADO:
        print("ℹ️ Nenhum grupo válido especificado para publicação.")
        await update.message.reply_text("✅ Evento cadastrado com sucesso! (Nenhum grupo para publicação)")
    else:
        # Tenta publicar
        try:
            # Remove possíveis espaços e converte para inteiro
            grupo_id_limpo = grupo_id.strip().replace(" ", "")
            grupo_id_int = int(float(grupo_id_limpo))
            
            mensagem_grupo = (
                f"🐐 *Nova sessão disponível para visitas!*\n"
                f"━━━━━━━━━━━━━━━━\n"
                f"🏛 *LOJA {dados_evento['nome_loja']} {dados_evento['numero_loja']}*\n"
                f"━━━━━━━━━━━━━━━━\n\n"
                f"📍 Oriente: {dados_evento['oriente']}\n"
                f"⚜️ Potência: {dados_evento['potencia']}\n"
                f"📅 Data: {dados_evento['data']} ({dados_evento['dia_semana']})\n"
                f"🕯 Tipo de sessão: {dados_evento['tipo_sessao']}\n"
                f"📖 Rito: {dados_evento['rito']}\n"
                f"🔺 Grau mínimo: {dados_evento['grau']}\n"
                f"👔 Traje: {dados_evento['traje']}\n"
                f"🍽 Ágape: {dados_evento['agape']}\n"
            )
            
            if dados_evento['observacoes'] and dados_evento['observacoes'] not in ["N/A", "n/a"]:
                mensagem_grupo += f"\n📌 Observações: {dados_evento['observacoes']}"
            
            botoes = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Confirmar Presença", callback_data=f"confirmar_{indice_evento}")],
                [InlineKeyboardButton("👥 Ver confirmados", callback_data=f"ver_confirmados_{indice_evento}")]
            ])
            
            await context.bot.send_message(
                chat_id=grupo_id_int,
                text=mensagem_grupo,
                parse_mode="Markdown",
                reply_markup=botoes
            )
            print(f"✅ Evento publicado no grupo {grupo_id_int} com índice {indice_evento}")
            await update.message.reply_text(f"✅ Evento cadastrado e publicado no grupo com sucesso!")
            
        except Exception as e:
            print(f"❌ Erro ao publicar no grupo: {e}")
            await update.message.reply_text(f"⚠️ Evento cadastrado, mas não foi possível publicar no grupo (ID: {grupo_id}). O grupo existe e o bot está lá?")
    
    await update.message.reply_text("Use /start para voltar ao menu principal.")
    return ConversationHandler.END

async def cancelar_cadastro_evento(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Cadastro de evento cancelado. Use /start para voltar ao menu principal.")
    return ConversationHandler.END

# Definindo o estado ID_GRUPO (precisa ser um número diferente dos outros)
ID_GRUPO = 14

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
        AGAPE_TIPO: [CallbackQueryHandler(receber_agape_tipo, pattern="^agape_(gratuito|dividido)$")],
        OBSERVACOES: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_observacoes)],
        ID_GRUPO: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_id_grupo)],
        ENDERECO: [MessageHandler(filters.TEXT & ~filters.COMMAND, finalizar_cadastro_evento)],
    },
    fallbacks=[CommandHandler("cancelar", cancelar_cadastro_evento)],
)