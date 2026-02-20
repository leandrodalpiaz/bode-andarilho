from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from src.sheets import listar_eventos, buscar_membro, registrar_confirmacao

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

    grau = evento.get("Grau mínimo", "")
    tipo = evento.get("Tipo de sessão", "")
    rito = evento.get("Rito", "")
    potencia = evento.get("Potência", "")
    traje = evento.get("Traje obrigatório", "")
    agape = evento.get("Ágape", "")
    obs = evento.get("Observações", "")

    texto = (
        f"📅 *{evento.get('Data do evento', '')}* — {evento.get('Nome da loja', '')}\n"
        f"🕐 Horário: {evento.get('Hora', '')}\n"
        f"📍 Local: {evento.get('Local', '')}\n"
        f"🔷 Grau mínimo: {grau}\n"
        f"📋 Tipo: {tipo}\n"
        f"✡️ Rito: {rito}\n"
        f"⚡ Potência: {potencia}\n"
        f"👔 Traje: {traje}\n"
        f"🍽️ Ágape: {agape}\n"
    )

    if obs:
        texto += f"\n📝 Obs: {obs}"

    teclado = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Confirmar presença", callback_data=f"confirmar_{indice}")],
        [InlineKeyboardButton("⬅️ Voltar", callback_data="ver_eventos")]
    ])

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

    dados = {
        "id_evento": evento.get("Data do evento", "") + " — " + evento.get("Nome da loja", ""),
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
        f"Evento: {dados['id_evento']}\n\n"
        f"Até lá! 🐐"
    )
