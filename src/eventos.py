# src/eventos.py
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler, CallbackQueryHandler, MessageHandler, filters, CommandHandler
from src.sheets import (
    listar_eventos, buscar_membro, registrar_confirmacao,
    cancelar_confirmacao, buscar_confirmacao
)

AGAPE_CHOICE = range(1)

async def mostrar_eventos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    eventos = listar_eventos()
    if not eventos:
        await query.edit_message_text("Não há eventos ativos no momento. Volte em breve, irmão.")
        return

    botoes = []
    for i, evento in enumerate(eventos):
        nome = evento.get("Nome da loja", "Evento")
        data = evento.get("Data do evento", "")
        numero_loja = evento.get("Número da loja", "")
        potencia = evento.get("Potência", "")
        botoes.append([InlineKeyboardButton(
            f"{data} - {nome} {numero_loja} - {potencia}",
            callback_data=f"evento_{i}"
        )])

    teclado = InlineKeyboardMarkup(botoes)
    await query.edit_message_text("Selecione um evento para ver os detalhes:", reply_markup=teclado)

async def mostrar_detalhes_evento(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

    texto = (
        f"📅 *{data} — {nome_loja} {numero_loja} - {potencia}*\n"
        f"🕕 Horário: {horario if horario else 'Não informado'}\n"
        f"📍 Endereço: {endereco}\n"
        f"🔷 Grau mínimo: {grau}\n"
        f"📋 Tipo: {tipo}\n"
        f"✡️ Rito: {rito}\n"
        f"⚡ Potência: {potencia}\n"
        f"👔 Traje: {traje}\n"
        f"🍽️ Ágape: {agape}\n"
    )

    if obs and obs.strip().lower() not in ["n/a", "n"]:
        texto += f"\n📌 Obs: {obs}"
    else:
        texto += "\n📌 Obs: Sem observações"

    telegram_id = update.effective_user.id
    id_evento = data + " — " + nome_loja
    ja_confirmou = buscar_confirmacao(id_evento, telegram_id)

    if ja_confirmou:
        botoes = [
            [InlineKeyboardButton("❌ Cancelar presença", callback_data=f"cancelar_{indice}")],
            [InlineKeyboardButton("⬅️ Voltar", callback_data="ver_eventos")]
        ]
    else:
        botoes = [
            [InlineKeyboardButton("✅ Confirmar presença", callback_data=f"confirmar_{indice}")],
            [InlineKeyboardButton("⬅️ Voltar", callback_data="ver_eventos")]
        ]

    teclado = InlineKeyboardMarkup(botoes)
    await query.edit_message_text(texto, parse_mode="Markdown", reply_markup=teclado)

async def iniciar_confirmacao_presenca(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    chat_type = update.effective_chat.type
    if chat_type in ["group", "supergroup"]:
        await query.edit_message_text(
            "Você será redirecionado para o chat privado para concluir a confirmação. "
            "Por favor, verifique suas mensagens diretas com o bot."
        )
        indice = int(query.data.split("_")[1])
        eventos = listar_eventos()
        evento = eventos[indice]
        context.user_data["evento_confirmando"] = evento
        membro = buscar_membro(update.effective_user.id)
        if not membro:
            await context.bot.send_message(
                chat_id=update.effective_user.id,
                text="Seu cadastro não foi encontrado. Envie /start para se cadastrar."
            )
            return ConversationHandler.END
        context.user_data["membro_confirmando"] = membro

        id_evento = evento.get("Data do evento", "") + " — " + evento.get("Nome da loja", "")
        ja_confirmou = buscar_confirmacao(id_evento, update.effective_user.id)
        if ja_confirmou:
            await context.bot.send_message(
                chat_id=update.effective_user.id,
                text="Você já confirmou presença para este evento."
            )
            return ConversationHandler.END

        if evento.get("Ágape", "").lower().startswith("sim"):
            agape_info = evento.get("Ágape", "Sim").replace("Sim ", "").strip()
            if agape_info:
                agape_info = f"*Tipo:* {agape_info.replace('(', '').replace(')', '')}\n"
            else:
                agape_info = ""

            teclado_agape = InlineKeyboardMarkup([
                [InlineKeyboardButton("Sim", callback_data="agape_participar_sim")],
                [InlineKeyboardButton("Não", callback_data="agape_participar_nao")]
            ])
            await context.bot.send_message(
                chat_id=update.effective_user.id,
                text=f"Este evento oferece ágape!\n{agape_info}Você deseja participar do ágape?",
                parse_mode="Markdown",
                reply_markup=teclado_agape
            )
            return AGAPE_CHOICE
        else:
            context.user_data["participacao_agape"] = "Não aplicável"
            # Chama finalizar_confirmacao_presenca com o update original, mas forçando chat_privado=True
            # Precisamos passar o update correto. Como estamos no grupo, o update é do grupo.
            # Vamos criar um novo contexto? Melhor: chamar a função passando o chat_id manualmente.
            return await finalizar_confirmacao_presenca(update, context, chat_privado=True)

    else:
        # Já está em privado
        indice = int(query.data.split("_")[1])
        eventos = listar_eventos()
        evento = eventos[indice]
        membro = buscar_membro(update.effective_user.id)
        if not membro:
            await query.edit_message_text("Seu cadastro não foi encontrado. Envie /start para se cadastrar.")
            return ConversationHandler.END

        id_evento = evento.get("Data do evento", "") + " — " + evento.get("Nome da loja", "")
        ja_confirmou = buscar_confirmacao(id_evento, update.effective_user.id)
        if ja_confirmou:
            await query.edit_message_text("Você já confirmou presença para este evento.")
            return ConversationHandler.END

        context.user_data["evento_confirmando"] = evento
        context.user_data["membro_confirmando"] = membro

        if evento.get("Ágape", "").lower().startswith("sim"):
            agape_info = evento.get("Ágape", "Sim").replace("Sim ", "").strip()
            if agape_info:
                agape_info = f"*Tipo:* {agape_info.replace('(', '').replace(')', '')}\n"
            else:
                agape_info = ""

            teclado_agape = InlineKeyboardMarkup([
                [InlineKeyboardButton("Sim", callback_data="agape_participar_sim")],
                [InlineKeyboardButton("Não", callback_data="agape_participar_nao")]
            ])
            await query.edit_message_text(
                f"Este evento oferece ágape!\n{agape_info}Você deseja participar do ágape?",
                parse_mode="Markdown",
                reply_markup=teclado_agape
            )
            return AGAPE_CHOICE
        else:
            context.user_data["participacao_agape"] = "Não aplicável"
            return await finalizar_confirmacao_presenca(update, context)

async def handle_agape_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    escolha_agape = query.data.split("_")[-1]

    if escolha_agape == "sim":
        context.user_data["participacao_agape"] = "Confirmada"
        await query.edit_message_text(
            "Irmão, sua confirmação para o ágape é muito valiosa! Ela nos ajuda a organizar tudo com carinho e evitar desperdícios. Contamos com sua colaboração!\n\n"
            "Preparando sua confirmação final..."
        )
    else:
        context.user_data["participacao_agape"] = "Não selecionada"
        await query.edit_message_text("Certo, sua participação no ágape não será registrada. Preparando sua confirmação final...")

    return await finalizar_confirmacao_presenca(update, context)

async def finalizar_confirmacao_presenca(update: Update, context: ContextTypes.DEFAULT_TYPE, chat_privado=False):
    evento = context.user_data["evento_confirmando"]
    membro = context.user_data["membro_confirmando"]
    participacao_agape = context.user_data.get("participacao_agape", "Não aplicável")

    id_evento = evento.get("Data do evento", "") + " — " + evento.get("Nome da loja", "")

    dados_confirmacao = {
        "id_evento": id_evento,
        "telegram_id": membro.get("Telegram ID", ""),
        "nome": membro.get("Nome", ""),
        "grau": membro.get("Grau", ""),
        "cargo": membro.get("Cargo", ""),
        "loja": membro.get("Loja", ""),
        "oriente": membro.get("Oriente", ""),
        "potencia": membro.get("Potência", ""),
        "agape": participacao_agape,
    }

    registrar_confirmacao(dados_confirmacao)

    data = evento.get("Data do evento", "")
    nome_loja = evento.get("Nome da loja", "")
    numero_loja = evento.get("Número da loja", "")
    horario = evento.get("Hora", "")
    endereco = evento.get("Endereço da sessão", "")
    potencia_evento = evento.get("Potência", "")

    resposta_final = f"✅ Presença confirmada, irmão {membro.get('Nome', '')}!\n\n"
    resposta_final += "*Resumo da Sessão Confirmada:*\n"
    resposta_final += f"📅 {data} — {nome_loja} {numero_loja} - {potencia_evento}\n"
    resposta_final += f"🕕 Horário: {horario if horario else 'Não informado'}\n"
    resposta_final += f"📍 Endereço: {endereco}\n"
    resposta_final += f"🍽️ Participação no ágape: {participacao_agape}\n\n"
    resposta_final += (
        "Sua confirmação aqui é um passo importante! Contudo, recordamos que o reconhecimento no dia do evento segue os protocolos de cada Loja e Potência. Certifique-se de estar em dia com as verificações necessárias.\n\n"
    )
    resposta_final += "Fraterno abraço! 🐐"

    # Determina para onde enviar a resposta
    if chat_privado:
        # Envia para o privado do usuário
        await context.bot.send_message(
            chat_id=membro.get("Telegram ID"),
            text=resposta_final,
            parse_mode="Markdown"
        )
    else:
        # Responde no chat atual (pode ser privado ou grupo, mas se for grupo, não deve acontecer)
        if update.callback_query:
            await update.callback_query.edit_message_text(resposta_final, parse_mode="Markdown")
        else:
            await update.message.reply_text(resposta_final, parse_mode="Markdown")

    # Limpa dados da sessão
    context.user_data.pop("evento_confirmando", None)
    context.user_data.pop("membro_confirmando", None)
    context.user_data.pop("participacao_agape", None)

    return ConversationHandler.END

async def cancelar_presenca(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    indice = int(query.data.split("_")[1])
    eventos = listar_eventos()
    evento = eventos[indice]

    telegram_id = update.effective_user.id
    id_evento = evento.get("Data do evento", "") + " — " + evento.get("Nome da loja", "")

    cancelou = cancelar_confirmacao(id_evento, telegram_id)

    if cancelou:
        await query.edit_message_text(
            f"❌ Presença cancelada.\n\n"
            f"Evento: {id_evento}\n\n"
            f"Se mudar de ideia, basta confirmar novamente. Fraterno abraço! 🐐"
        )
    else:
        await query.edit_message_text("Não foi possível cancelar. Você não estava confirmado para este evento.")

confirmacao_presenca_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(iniciar_confirmacao_presenca, pattern="^confirmar_")],
    states={
        AGAPE_CHOICE: [CallbackQueryHandler(handle_agape_choice, pattern="^agape_participar_(sim|nao)$")],
    },
    fallbacks=[CommandHandler("cancelar", cancelar_presenca)],
    map_to_parent={
        ConversationHandler.END: ConversationHandler.END,
    }
)