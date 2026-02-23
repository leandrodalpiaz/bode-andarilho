from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from src.sheets import (
    listar_eventos, buscar_membro, registrar_confirmacao,
    cancelar_confirmacao, buscar_confirmacao
)

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
        botoes.append([InlineKeyboardButton(f"{data} — {nome}", callback_data=f"evento_{i}")])

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
    context.user_data["evento_selecionado"] = indice

    data = evento.get("Data do evento", "")
    nome_loja = evento.get("Nome da loja", "")
    horario = evento.get("Hora", "")
    endereco = evento.get("Endereço da sessão", "")
    grau = evento.get("Grau mínimo", "")
    tipo = evento.get("Tipo de sessão", "")
    rito = evento.get("Rito", "")
    potencia = evento.get("Potência", "")
    traje = evento.get("Traje obrigatório", "")
    agape = evento.get("Ágape", "")
    obs = evento.get("Observações", "")

    texto = (
        f"📅 *{data}* — {nome_loja}\n"
        f"🕐 Horário: {horario}\n"
        f"📍 Endereço: {endereco}\n"
        f"🔷 Grau mínimo: {grau}\n"
        f"📋 Tipo: {tipo}\n"
        f"✡️ Rito: {rito}\n"
        f"⚡ Potência: {potencia}\n"
        f"👔 Traje: {traje}\n"
        f"🍽️ Ágape: {agape}\n"
    )

    if obs:
        texto += f"\n📝 Obs: {obs}"

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

async def confirmar_presenca(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    indice = int(query.data.split("_")[1])
    eventos = listar_eventos()
    evento = eventos[indice]

    telegram_id = update.effective_user.id
    membro = buscar_membro(telegram_id)

    if not membro:
        await query.edit_message_text("Seu cadastro não foi encontrado. Envie /start para se cadastrar.")
        return

    id_evento = evento.get("Data do evento", "") + " — " + evento.get("Nome da loja", "")

    dados = {
        "id_evento": id_evento,
        "telegram_id": telegram_id,
        "nome": membro.get("Nome", ""),
        "grau": membro.get("Grau", ""),
        "cargo": membro.get("Cargo", ""),
        "loja": membro.get("Loja", ""),
        "oriente": membro.get("Oriente", ""),
        "potencia": membro.get("Potência", ""),
        "agape": evento.get("Ágape", ""),
    }

    registrar_confirmacao(dados)

    await query.edit_message_text(
        f"✅ Presença confirmada, irmão {membro.get('Nome', '')}!\n\n"
        f"Evento: {id_evento}\n\n"
        f"Até lá! 🐐"
    )

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
            f"Se mudar de ideia, basta confirmar novamente. 🐐"
        )
    else:
        await query.edit_message_text("Não foi possível cancelar. Tente novamente.")
