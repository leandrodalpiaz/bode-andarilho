# src/eventos.py
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler, CallbackQueryHandler, MessageHandler, filters, CommandHandler
from src.sheets import (
    listar_eventos, buscar_membro, registrar_confirmacao,
    cancelar_confirmacao, buscar_confirmacao, listar_confirmacoes_por_evento
)
from datetime import datetime  # Importação necessária
import time
import re

# Dicionário para traduzir dias da semana para português
DIAS_SEMANA = {
    "Monday": "Segunda-feira",
    "Tuesday": "Terça-feira",
    "Wednesday": "Quarta-feira",
    "Thursday": "Quinta-feira",
    "Friday": "Sexta-feira",
    "Saturday": "Sábado",
    "Sunday": "Domingo"
}

AGAPE_CHOICE = range(1)

def traduzir_dia(dia_ingles):
    """Traduz o dia da semana para português."""
    return DIAS_SEMANA.get(dia_ingles, dia_ingles)

def traduzir_dia_abreviado(texto):
    """Traduz dias da semana em formato abreviado."""
    substituicoes = {
        "Monday": "Segunda",
        "Tuesday": "Terça",
        "Wednesday": "Quarta",
        "Thursday": "Quinta",
        "Friday": "Sexta",
        "Saturday": "Sábado",
        "Sunday": "Domingo"
    }
    for en, pt in substituicoes.items():
        texto = texto.replace(en, pt)
    return texto

def extrair_tipo_agape(texto_agape):
    """Extrai o tipo de ágape do texto da planilha."""
    texto = texto_agape.lower()
    if "pago" in texto or "dividido" in texto:
        return "pago"
    elif "gratuito" in texto:
        return "gratuito"
    else:
        return "sem"

async def mostrar_eventos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lista eventos disponíveis para seleção, agrupados por data."""
    query = update.callback_query
    await query.answer()

    eventos = listar_eventos()
    if not eventos:
        await query.edit_message_text("Não há eventos ativos no momento. Volte em breve, irmão.")
        return

    # Agrupar por data
    eventos_por_data = {}
    for i, evento in enumerate(eventos):
        data = evento.get("Data do evento", "")
        if data not in eventos_por_data:
            eventos_por_data[data] = []
        eventos_por_data[data].append((i, evento))

    # Criar botões por data
    botoes = []
    for data, evs in eventos_por_data.items():
        try:
            data_obj = datetime.strptime(data, "%d/%m/%Y")
            dia_semana = traduzir_dia(data_obj.strftime("%A"))
            data_formatada = f"{data_obj.strftime('%d/%m')} ({dia_semana[:3]})"
        except:
            data_formatada = data
        
        botoes.append([InlineKeyboardButton(
            f"📅 {data_formatada} - {len(evs)} evento(s)",
            callback_data=f"data_{data}"
        )])

    # Botão voltar
    from src.permissoes import get_nivel
    nivel = get_nivel(update.effective_user.id)
    
    botoes_voltar = []
    if update.effective_chat.type == "private":
        botoes_voltar = [[InlineKeyboardButton("⬅️ Voltar ao menu", callback_data="menu_principal")]]
    else:
        botoes_voltar = [[InlineKeyboardButton("⬅️ Voltar", callback_data="voltar_grupo")]]

    teclado = InlineKeyboardMarkup(botoes + botoes_voltar)
    await query.edit_message_text("Selecione uma data para ver os eventos:", reply_markup=teclado)

async def mostrar_eventos_por_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mostra eventos de uma data específica, agrupados por grau."""
    query = update.callback_query
    await query.answer()

    data = query.data.split("_", 1)[1]
    eventos = listar_eventos()
    eventos_data = [e for e in eventos if e.get("Data do evento") == data]

    if not eventos_data:
        await query.edit_message_text("Nenhum evento encontrado para esta data.")
        return

    # Agrupar por grau
    graus = {}
    for evento in eventos_data:
        grau = evento.get("Grau", "Indefinido")
        if grau not in graus:
            graus[grau] = []
        graus[grau].append(evento)

    botoes = []
    for grau, evs in graus.items():
        botoes.append([InlineKeyboardButton(
            f"🔺 {grau} - {len(evs)} evento(s)",
            callback_data=f"grau_{data}_{grau}"
        )])

    botoes.append([InlineKeyboardButton("⬅️ Voltar", callback_data="ver_eventos")])
    teclado = InlineKeyboardMarkup(botoes)
    
    try:
        data_obj = datetime.strptime(data, "%d/%m/%Y")
        data_formatada = data_obj.strftime("%d/%m/%Y")
    except:
        data_formatada = data
        
    await query.edit_message_text(
        f"📅 *{data_formatada}*\n\nSelecione o grau:",
        parse_mode="Markdown",
        reply_markup=teclado
    )

async def mostrar_eventos_por_grau(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lista eventos de uma data e grau específicos."""
    query = update.callback_query
    await query.answer()

    partes = query.data.split("_", 2)
    data = partes[1]
    grau = partes[2]

    eventos = listar_eventos()
    eventos_filtrados = [
        e for e in eventos 
        if e.get("Data do evento") == data and e.get("Grau") == grau
    ]

    if not eventos_filtrados:
        await query.edit_message_text("Nenhum evento encontrado.")
        return

    botoes = []
    for i, evento in enumerate(eventos_filtrados):
        # Encontrar índice global para callback
        indice_global = None
        for j, ev in enumerate(eventos):
            if (ev.get("Data do evento") == evento.get("Data do evento") and
                ev.get("Nome da loja") == evento.get("Nome da loja")):
                indice_global = j
                break

        if indice_global is not None:
            nome = evento.get("Nome da loja", "Evento")
            numero = evento.get("Número da loja", "")
            potencia = evento.get("Potência", "")
            horario = evento.get("Hora", "")
            botoes.append([InlineKeyboardButton(
                f"🏛 {nome} {numero} - {potencia} - {horario}",
                callback_data=f"evento_{indice_global}"
            )])

    botoes.append([InlineKeyboardButton("⬅️ Voltar", callback_data=f"data_{data}")])
    teclado = InlineKeyboardMarkup(botoes)
    
    try:
        data_obj = datetime.strptime(data, "%d/%m/%Y")
        data_formatada = data_obj.strftime("%d/%m/%Y")
    except:
        data_formatada = data
        
    await query.edit_message_text(
        f"📅 *{data_formatada} - {grau}*\n\nSelecione o evento:",
        parse_mode="Markdown",
        reply_markup=teclado
    )

async def mostrar_detalhes_evento(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mostra detalhes de um evento específico."""
    query = update.callback_query
    await query.answer()

    indice = int(query.data.split("_")[1])
    eventos = listar_eventos()
    if indice >= len(eventos):
        await query.edit_message_text("Evento não encontrado.")
        return

    evento = eventos[indice]
    context.user_data["evento_selecionado_indice"] = indice

    data = evento.get("Data do evento", "")
    nome_loja = evento.get("Nome da loja", "")
    numero_loja = evento.get("Número da loja", "")
    horario = evento.get("Hora", "")
    endereco = evento.get("Endereço da sessão", "")
    grau = evento.get("Grau", "")
    tipo = evento.get("Tipo de sessão", "")
    rito = evento.get("Rito", "")
    potencia = evento.get("Potência", "")
    traje = evento.get("Traje obrigatório", "")
    agape = evento.get("Ágape", "")
    obs = evento.get("Observações", "")
    oriente = evento.get("Oriente", "")
    dia_semana_ingles = evento.get("Dia da semana", "")

    dia_semana = traduzir_dia(dia_semana_ingles)

    texto = (
        f"📅 *{data} — {nome_loja} {numero_loja}*\n"
        f"━━━━━━━━━━━━━━━━\n\n"
        f"📍 Oriente: {oriente}\n"
        f"⚜️ Potência: {potencia}\n"
        f"📆 Dia: {dia_semana}\n"
        f"🕕 Horário: {horario if horario else 'Não informado'}\n"
        f"📍 Endereço: {endereco}\n"
        f"🔷 Grau mínimo: {grau}\n"
        f"📋 Tipo: {tipo}\n"
        f"✡️ Rito: {rito}\n"
        f"👔 Traje: {traje}\n"
        f"🍽️ Ágape: {agape}\n"
    )

    if obs and obs.strip().lower() not in ["n/a", "n", "nao", "não"]:
        texto += f"\n📌 Obs: {obs}"
    else:
        texto += "\n📌 Obs: Sem observações"

    telegram_id = update.effective_user.id
    id_evento = f"{data} — {nome_loja}"
    ja_confirmou = buscar_confirmacao(id_evento, telegram_id)

    # Determinar botões baseado no tipo de ágape
    tipo_agape = extrair_tipo_agape(agape)
    
    botoes = []
    
    if ja_confirmou:
        botoes.append([InlineKeyboardButton("❌ Cancelar presença", callback_data=f"cancelar_{indice}")])
    else:
        if tipo_agape == "gratuito":
            botoes.append([InlineKeyboardButton("🍽 Participar com ágape (gratuito)", callback_data=f"confirmar_{indice}_gratuito")])
            botoes.append([InlineKeyboardButton("🚫 Participar sem ágape", callback_data=f"confirmar_{indice}_sem")])
        elif tipo_agape == "pago":
            botoes.append([InlineKeyboardButton("🍽 Participar com ágape (pago)", callback_data=f"confirmar_{indice}_pago")])
            botoes.append([InlineKeyboardButton("🚫 Participar sem ágape", callback_data=f"confirmar_{indice}_sem")])
        else:  # sem ágape
            botoes.append([InlineKeyboardButton("✅ Confirmar presença", callback_data=f"confirmar_{indice}_sem")])
    
    botoes.append([InlineKeyboardButton("👥 Ver confirmados", callback_data=f"ver_confirmados_{indice}")])
    
    # Botão voltar depende do contexto
    if update.effective_chat.type == "private":
        botoes.append([InlineKeyboardButton("⬅️ Voltar", callback_data="ver_eventos")])
    else:
        botoes.append([InlineKeyboardButton("⬅️ Voltar", callback_data="voltar_grupo")])

    teclado = InlineKeyboardMarkup(botoes)
    
    # Se estiver em grupo, apenas envia a mensagem (não edita)
    if update.effective_chat.type in ["group", "supergroup"]:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=texto,
            parse_mode="Markdown",
            reply_markup=teclado
        )
        # Opcionalmente apaga a mensagem original do callback
        try:
            await query.delete_message()
        except:
            pass
    else:
        await query.edit_message_text(texto, parse_mode="Markdown", reply_markup=teclado)

async def ver_confirmados(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mostra lista de confirmados em mensagem temporária."""
    query = update.callback_query
    await query.answer()

    indice = int(query.data.split("_")[-1])
    eventos = listar_eventos()
    if indice >= len(eventos):
        await query.edit_message_text("Evento não encontrado.")
        return

    evento = eventos[indice]
    data = evento.get("Data do evento", "")
    nome_loja = evento.get("Nome da loja", "")
    id_evento = f"{data} — {nome_loja}"
    
    confirmacoes = listar_confirmacoes_por_evento(id_evento)
    
    if not confirmacoes:
        texto = f"👥 *CONFIRMADOS - {nome_loja}*\n📅 {data}\n\nNenhum irmão confirmou presença ainda.\n\nSeja o primeiro! 🐐"
    else:
        texto = f"👥 *CONFIRMADOS - {nome_loja}*\n📅 {data}\n\nTotal: {len(confirmacoes)} irmão(s)\n\n"
        for conf in confirmacoes:
            nome = conf.get("Nome", "Desconhecido")
            grau = conf.get("Grau", "")
            loja = conf.get("Loja", "")
            oriente = conf.get("Oriente", "")
            potencia = conf.get("Potência", "")
            agape = conf.get("Ágape", "")
            
            if "Confirmada" in str(agape) or "Sim" in str(agape):
                icone = "🍽"
                status = "Com ágape"
            else:
                icone = "🚫"
                status = "Sem ágape"
            
            texto += f"• {grau} {nome} - {loja} ({oriente}) - {potencia} - {icone} {status}\n"
    
    # Botões da mensagem temporária
    botoes = []
    
    # Verificar se o usuário atual está na lista
    user_id = update.effective_user.id
    user_confirmado = any(str(conf.get("Telegram ID")) == str(user_id) for conf in confirmacoes)
    
    if user_confirmado:
        botoes.append([InlineKeyboardButton("❌ Cancelar minha presença", callback_data=f"cancelar_{indice}")])
    else:
        # Determinar tipo de ágape para botão de confirmação
        agape = evento.get("Ágape", "")
        tipo_agape = extrair_tipo_agape(agape)
        
        if tipo_agape == "gratuito":
            botoes.append([InlineKeyboardButton("🍽 Confirmar com ágape (gratuito)", callback_data=f"confirmar_{indice}_gratuito")])
            botoes.append([InlineKeyboardButton("🚫 Confirmar sem ágape", callback_data=f"confirmar_{indice}_sem")])
        elif tipo_agape == "pago":
            botoes.append([InlineKeyboardButton("🍽 Confirmar com ágape (pago)", callback_data=f"confirmar_{indice}_pago")])
            botoes.append([InlineKeyboardButton("🚫 Confirmar sem ágape", callback_data=f"confirmar_{indice}_sem")])
        else:
            botoes.append([InlineKeyboardButton("✅ Confirmar presença", callback_data=f"confirmar_{indice}_sem")])
    
    botoes.append([InlineKeyboardButton("🔒 Fechar", callback_data=f"fechar_mensagem")])
    
    teclado = InlineKeyboardMarkup(botoes)
    
    # Enviar mensagem temporária
    mensagem = await query.edit_message_text(
        texto, 
        parse_mode="Markdown", 
        reply_markup=teclado
    )
    
    # Armazenar para possível auto-exclusão (opcional)

async def fechar_mensagem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Fecha (apaga) uma mensagem temporária."""
    query = update.callback_query
    await query.answer()
    
    try:
        await query.delete_message()
    except:
        await query.edit_message_text("Mensagem fechada.")

async def minhas_confirmacoes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mostra lista de eventos que o usuário confirmou."""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    eventos = listar_eventos()
    
    confirmados = []
    for i, evento in enumerate(eventos):
        id_evento = f"{evento.get('Data do evento', '')} — {evento.get('Nome da loja', '')}"
        if buscar_confirmacao(id_evento, user_id):
            confirmados.append((i, evento))

    if not confirmados:
        await query.edit_message_text(
            "Você não tem nenhuma presença confirmada no momento.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("📅 Ver eventos", callback_data="ver_eventos")
            ]])
        )
        return

    texto = "Você tem presença confirmada em:\n\n"
    botoes = []
    
    for idx, (indice, evento) in enumerate(confirmados):
        data = evento.get("Data do evento", "")
        nome = evento.get("Nome da loja", "")
        numero = evento.get("Número da loja", "")
        potencia = evento.get("Potência", "")
        horario = evento.get("Hora", "")
        
        texto += f"{idx+1}. 📅 {data} - {nome} {numero} - {potencia} - {horario}\n"
        botoes.append([InlineKeyboardButton(f"❌ Cancelar {idx+1}", callback_data=f"cancelar_{indice}")])
    
    botoes.append([InlineKeyboardButton("⬅️ Voltar", callback_data="menu_principal")])
    
    await query.edit_message_text(texto, reply_markup=InlineKeyboardMarkup(botoes))

async def iniciar_confirmacao_presenca(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Inicia processo de confirmação de presença."""
    query = update.callback_query
    await query.answer()

    # Extrair dados do callback
    partes = query.data.split("_")
    indice = int(partes[1])
    tipo_agape = partes[2] if len(partes) > 2 else "sem"

    eventos = listar_eventos()
    if indice >= len(eventos):
        await query.edit_message_text("Evento não encontrado.")
        return ConversationHandler.END

    evento = eventos[indice]
    user_id = update.effective_user.id
    membro = buscar_membro(user_id)

    # Se não for cadastrado, redirecionar para cadastro
    if not membro:
        # Armazenar dados para retornar após cadastro
        context.user_data["pos_cadastro"] = {
            "acao": "confirmar",
            "indice": indice,
            "tipo_agape": tipo_agape
        }
        
        if update.effective_chat.type in ["group", "supergroup"]:
            await query.edit_message_text(
                "🔔 Você precisa se cadastrar primeiro! Verifique suas mensagens privadas."
            )
        
        from src.cadastro import cadastro_start
        return await cadastro_start(update, context)

    # Verificar se já confirmou
    id_evento = f"{evento.get('Data do evento', '')} — {evento.get('Nome da loja', '')}"
    ja_confirmou = buscar_confirmacao(id_evento, user_id)
    
    if ja_confirmou:
        await query.edit_message_text("Você já confirmou presença para este evento.")
        return ConversationHandler.END

    # Registrar confirmação
    participacao_agape = "Confirmada" if tipo_agape != "sem" else "Não selecionada"
    if tipo_agape == "gratuito":
        desc_agape = "Gratuito"
    elif tipo_agape == "pago":
        desc_agape = "Pago"
    else:
        desc_agape = "Não aplicável"

    dados_confirmacao = {
        "id_evento": id_evento,
        "telegram_id": str(user_id),
        "nome": membro.get("Nome", ""),
        "grau": membro.get("Grau", ""),
        "cargo": membro.get("Cargo", ""),
        "loja": membro.get("Loja", ""),
        "oriente": membro.get("Oriente", ""),
        "potencia": membro.get("Potência", ""),
        "agape": f"{participacao_agape} ({desc_agape})" if participacao_agape == "Confirmada" else "Não",
    }

    registrar_confirmacao(dados_confirmacao)

    # Enviar mensagem de confirmação no privado
    data = evento.get("Data do evento", "")
    nome_loja = evento.get("Nome da loja", "")
    numero_loja = evento.get("Número da loja", "")
    horario = evento.get("Hora", "")
    potencia_evento = evento.get("Potência", "")
    dia_semana_ingles = evento.get("Dia da semana", "")
    dia_semana = traduzir_dia(dia_semana_ingles)

    resposta = f"✅ Presença confirmada, irmão {membro.get('Nome', '')}!\n\n"
    resposta += f"*Resumo da confirmação:*\n"
    resposta += f"📅 {data} — {nome_loja} {numero_loja}\n"
    resposta += f"⚜️ Potência: {potencia_evento}\n"
    resposta += f"📆 Dia: {dia_semana}\n"
    resposta += f"🕕 Horário: {horario}\n"
    resposta += f"🍽 Participação no ágape: {participacao_agape} ({desc_agape})\n\n"
    resposta += "Sua confirmação é muito importante! Ela nos ajuda a organizar tudo com carinho e evitar desperdícios.\n\n"
    resposta += "Fraterno abraço! 🐐"

    botoes_privado = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Cancelar presença", callback_data=f"cancelar_{indice}")],
        [InlineKeyboardButton("👥 Ver eventos", callback_data="ver_eventos")]
    ])

    await context.bot.send_message(
        chat_id=user_id,
        text=resposta,
        parse_mode="Markdown",
        reply_markup=botoes_privado
    )

    # Responder no grupo (se for o caso)
    if update.effective_chat.type in ["group", "supergroup"]:
        # Não enviar mensagem no grupo para evitar poluição
        await query.edit_message_text("✅ Presença confirmada! Verifique seu privado para detalhes.")
    else:
        await query.edit_message_text("✅ Presença confirmada! Verifique a mensagem acima.")

    return ConversationHandler.END

async def cancelar_presenca(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancela presença de um usuário em um evento."""
    query = update.callback_query
    await query.answer()

    indice = int(query.data.split("_")[1])
    eventos = listar_eventos()
    if indice >= len(eventos):
        await query.edit_message_text("Evento não encontrado.")
        return

    evento = eventos[indice]
    user_id = update.effective_user.id
    id_evento = f"{evento.get('Data do evento', '')} — {evento.get('Nome da loja', '')}"

    # Se veio de uma lista de confirmados no grupo, pedir confirmação no privado
    if update.effective_chat.type in ["group", "supergroup"] and query.data.startswith("cancelar_"):
        # Verificar se já está no processo de confirmação
        if "confirmando_cancelamento" in context.user_data:
            # Já está confirmando, processar
            pass
        else:
            # Enviar para privado
            botoes = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Sim, cancelar", callback_data=f"confirma_cancelar_{indice}")],
                [InlineKeyboardButton("🔙 Não, voltar", callback_data=f"evento_{indice}")]
            ])
            
            await context.bot.send_message(
                chat_id=user_id,
                text=f"Confirmar cancelamento da sessão {id_evento}?",
                reply_markup=botoes
            )
            
            await query.edit_message_text("Instruções enviadas no privado.")
            return

    # Processar cancelamento
    cancelou = cancelar_confirmacao(id_evento, user_id)

    if cancelou:
        await query.edit_message_text(
            f"❌ Presença cancelada.\n\n"
            f"Evento: {id_evento}\n\n"
            f"Se mudar de ideia, basta confirmar novamente. Fraterno abraço! 🐐"
        )
    else:
        await query.edit_message_text("Não foi possível cancelar. Você não estava confirmado para este evento.")

# ConversationHandler para confirmação de presença
confirmacao_presenca_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(iniciar_confirmacao_presenca, pattern="^confirmar_")],
    states={},
    fallbacks=[CommandHandler("cancelar", cancelar_presenca)],
)