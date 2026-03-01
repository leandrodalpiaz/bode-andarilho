# src/eventos_secretario.py
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, CallbackQueryHandler, MessageHandler, filters
from src.sheets import listar_eventos, atualizar_evento, cancelar_todas_confirmacoes, buscar_membro
from src.permissoes import get_nivel
from datetime import datetime
import urllib.parse
import re
import logging

logger = logging.getLogger(__name__)

# Estados da conversação
SELECIONAR_EVENTO, CONFIRMAR_EXCLUSAO, EDITAR_CAMPO, NOVO_VALOR = range(4)

# Mapeamento de campos editáveis
CAMPOS_EVENTO = {
    "data": {"nome": "Data", "chave": "Data do evento"},
    "hora": {"nome": "Horário", "chave": "Hora"},
    "nome_loja": {"nome": "Nome da loja", "chave": "Nome da loja"},
    "numero_loja": {"nome": "Número", "chave": "Número da loja"},
    "oriente": {"nome": "Oriente", "chave": "Oriente"},
    "grau": {"nome": "Grau mínimo", "chave": "Grau"},
    "tipo_sessao": {"nome": "Tipo de sessão", "chave": "Tipo de sessão"},
    "rito": {"nome": "Rito", "chave": "Rito"},
    "potencia": {"nome": "Potência", "chave": "Potência"},
    "traje": {"nome": "Traje", "chave": "Traje obrigatório"},
    "agape": {"nome": "Ágape", "chave": "Ágape"},
    "observacoes": {"nome": "Observações", "chave": "Observações"},
    "endereco": {"nome": "Endereço", "chave": "Endereço da sessão"},
}

def sanitizar_callback(texto: str) -> str:
    """Remove caracteres especiais e substitui espaços por underline para callback_data seguro."""
    if not isinstance(texto, str):
        texto = str(texto)
    return re.sub(r'[^a-zA-Z0-9_]', '_', texto)

async def meus_eventos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lista eventos criados pelo secretário atual (ou todos se admin)."""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    nivel = get_nivel(user_id)
    eventos = listar_eventos()

    if nivel == "3":
        eventos_usuario = eventos  # admin vê todos
    else:
        eventos_usuario = [e for e in eventos if str(e.get("Telegram ID do secretário")) == str(user_id)]

    if not eventos_usuario:
        await query.edit_message_text(
            "Você não criou nenhum evento ainda." if nivel != "3" else "Não há eventos cadastrados.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Voltar", callback_data="area_secretario" if nivel == "2" else "area_admin")
            ]])
        )
        return

    texto = "Selecione um evento para gerenciar:\n\n"
    botoes = []
    for evento in eventos_usuario:
        data = evento.get("Data do evento", "")
        nome = evento.get("Nome da loja", "")
        numero = evento.get("Número da loja", "")
        status = "✅" if evento.get("Status") == "Ativo" else "❌"
        id_evento = f"{data} — {nome}"
        id_evento_sanitizado = sanitizar_callback(id_evento)
        botoes.append([InlineKeyboardButton(
            f"{status} {data} - {nome} {numero}",
            callback_data=f"gerenciar_evento|{id_evento_sanitizado}"
        )])

    botoes.append([InlineKeyboardButton("⬅️ Voltar", callback_data="area_secretario" if nivel == "2" else "area_admin")])
    await query.edit_message_text(texto, reply_markup=InlineKeyboardMarkup(botoes))

async def menu_gerenciar_evento(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menu de opções para um evento específico."""
    query = update.callback_query
    await query.answer()

    _, id_evento_sanitizado = query.data.split("|", 1)
    eventos = listar_eventos()
    evento = None
    id_evento_real = None
    for ev in eventos:
        id_teste = f"{ev.get('Data do evento', '')} — {ev.get('Nome da loja', '')}"
        if sanitizar_callback(id_teste) == id_evento_sanitizado:
            evento = ev
            id_evento_real = id_teste
            break

    if not evento:
        await query.edit_message_text("Evento não encontrado. Pode ter sido excluído.")
        return

    user_id = update.effective_user.id
    nivel = get_nivel(user_id)
    autor_id = str(evento.get("Telegram ID do secretário", ""))

    if nivel != "3" and str(user_id) != autor_id:
        await query.edit_message_text("⛔ Você não tem permissão para gerenciar este evento.")
        return

    context.user_data["evento_gerenciando"] = {
        "id_evento": id_evento_real,
        "evento": evento,
        "id_sanitizado": id_evento_sanitizado
    }

    data = evento.get("Data do evento", "")
    nome = evento.get("Nome da loja", "")
    numero = evento.get("Número da loja", "")
    status = evento.get("Status", "Ativo")

    texto = (
        f"📅 *{data} — {nome} {numero}*\n"
        f"Status: {'✅ Ativo' if status == 'Ativo' else '❌ Cancelado'}\n\n"
        f"*O que deseja fazer?*"
    )

    botoes = [
        [InlineKeyboardButton("✏️ Editar evento", callback_data=f"editar_evento|{id_evento_sanitizado}")],
        [InlineKeyboardButton("❌ Cancelar evento", callback_data=f"confirmar_cancelamento|{id_evento_sanitizado}")],
        [InlineKeyboardButton("⬅️ Voltar", callback_data="meus_eventos")]
    ]

    await query.edit_message_text(texto, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(botoes))

async def confirmar_cancelamento(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Pede confirmação para cancelar o evento."""
    query = update.callback_query
    await query.answer()

    _, id_evento_sanitizado = query.data.split("|", 1)
    eventos = listar_eventos()
    evento = None
    for ev in eventos:
        id_teste = f"{ev.get('Data do evento', '')} — {ev.get('Nome da loja', '')}"
        if sanitizar_callback(id_teste) == id_evento_sanitizado:
            evento = ev
            break

    if not evento:
        await query.edit_message_text("Evento não encontrado.")
        return

    data = evento.get("Data do evento", "")
    nome = evento.get("Nome da loja", "")
    numero = evento.get("Número da loja", "")

    texto = (
        f"❓ *Confirmar cancelamento*\n\n"
        f"Evento: {data} — {nome} {numero}\n\n"
        f"Esta ação irá:\n"
        f"• Marcar o evento como cancelado\n"
        f"• Publicar aviso no grupo\n"
        f"• Remover todas as confirmações\n\n"
        f"Tem certeza?"
    )

    botoes = [
        [InlineKeyboardButton("✅ Sim, cancelar", callback_data=f"cancelar_evento|{id_evento_sanitizado}")],
        [InlineKeyboardButton("🔙 Não, voltar", callback_data=f"gerenciar_evento|{id_evento_sanitizado}")]
    ]

    await query.edit_message_text(texto, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(botoes))

async def executar_cancelamento(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Executa o cancelamento do evento e publica aviso no grupo."""
    query = update.callback_query
    await query.answer()

    _, id_evento_sanitizado = query.data.split("|", 1)
    eventos = listar_eventos()
    evento = None
    indice = None
    id_evento_real = None
    for i, ev in enumerate(eventos):
        id_teste = f"{ev.get('Data do evento', '')} — {ev.get('Nome da loja', '')}"
        if sanitizar_callback(id_teste) == id_evento_sanitizado:
            evento = ev
            indice = i
            id_evento_real = id_teste
            break

    if not evento:
        await query.edit_message_text("Evento não encontrado.")
        return

    # Atualiza status na planilha
    evento["Status"] = "Cancelado"
    if not atualizar_evento(indice, evento):
        await query.edit_message_text("Erro ao cancelar evento. Tente novamente.")
        return

    # Remove todas as confirmações deste evento
    cancelar_todas_confirmacoes(id_evento_real)

    # Determina quem está cancelando
    user_id = update.effective_user.id
    nivel = get_nivel(user_id)
    autor_nome = "Administrador" if nivel == "3" else "Secretário"
    autor_info = f"pelo {autor_nome}"

    # Publica aviso no grupo
    grupo_id = evento.get("Telegram ID do grupo")
    if grupo_id and str(grupo_id).strip() not in ["", "N/A", "n/a"]:
        try:
            grupo_id_int = int(float(str(grupo_id).strip()))
            mensagem_grupo = (
                f"❌ *EVENTO CANCELADO {autor_info.upper()}*\n"
                f"━━━━━━━━━━━━━━━━\n"
                f"🏛 *LOJA {evento['Nome da loja']} {evento['Número da loja']}*\n"
                f"━━━━━━━━━━━━━━━━\n\n"
                f"📍 Data: {evento['Data do evento']}\n"
                f"🕕 Horário: {evento['Hora']}\n\n"
                f"Este evento foi cancelado {autor_info}.\n"
                f"Todas as confirmações foram removidas."
            )
            await context.bot.send_message(
                chat_id=grupo_id_int,
                text=mensagem_grupo,
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Erro ao publicar cancelamento: {e}")

    # Notifica todos os membros que haviam confirmado (opcional, pode ser implementado depois)
    # Por enquanto, apenas avisa no privado do autor
    await query.edit_message_text(
        f"✅ Evento cancelado com sucesso!\n"
        f"O aviso foi publicado no grupo e todas as confirmações foram removidas.",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("⬅️ Voltar", callback_data="meus_eventos")
        ]])
    )

async def iniciar_edicao(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Inicia o processo de edição de um evento."""
    query = update.callback_query
    await query.answer()

    _, id_evento_sanitizado = query.data.split("|", 1)
    eventos = listar_eventos()
    evento = None
    id_evento_real = None
    for ev in eventos:
        id_teste = f"{ev.get('Data do evento', '')} — {ev.get('Nome da loja', '')}"
        if sanitizar_callback(id_teste) == id_evento_sanitizado:
            evento = ev
            id_evento_real = id_teste
            break

    if not evento:
        await query.edit_message_text("Evento não encontrado.")
        return ConversationHandler.END

    context.user_data["editando_evento"] = {
        "id_evento": id_evento_real,
        "evento": evento,
        "id_sanitizado": id_evento_sanitizado
    }

    botoes = []
    for campo_id, campo_info in CAMPOS_EVENTO.items():
        valor_atual = evento.get(campo_info["chave"], "Não informado")
        botoes.append([InlineKeyboardButton(
            f"✏️ {campo_info['nome']}: {str(valor_atual)[:30]}",
            callback_data=f"editar_campo_evento|{campo_id}"
        )])

    botoes.append([InlineKeyboardButton("⬅️ Voltar", callback_data=f"gerenciar_evento|{id_evento_sanitizado}")])

    await query.edit_message_text(
        "📝 *Editar Evento*\n\n"
        "Selecione o campo que deseja alterar:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(botoes)
    )
    return EDITAR_CAMPO

async def selecionar_campo_evento(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Usuário selecionou um campo para editar."""
    query = update.callback_query
    await query.answer()

    campo_id = query.data.split("|")[1]
    campo_info = CAMPOS_EVENTO.get(campo_id)

    if not campo_info:
        await query.edit_message_text("Campo inválido.")
        return ConversationHandler.END

    context.user_data["campo_editando_evento"] = campo_id
    dados = context.user_data["editando_evento"]
    evento = dados["evento"]
    valor_atual = evento.get(campo_info["chave"], "Não informado")

    await query.edit_message_text(
        f"✏️ *Editando {campo_info['nome']}*\n\n"
        f"Valor atual: {valor_atual}\n\n"
        f"Digite o novo valor (ou /cancelar para desistir):",
        parse_mode="Markdown"
    )
    return NOVO_VALOR

async def receber_novo_valor_evento(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recebe o novo valor e atualiza o evento."""
    novo_valor = update.message.text.strip()
    campo_id = context.user_data.get("campo_editando_evento")
    campo_info = CAMPOS_EVENTO.get(campo_id)
    dados = context.user_data.get("editando_evento")

    if not campo_info or not dados:
        await update.message.reply_text("Erro: dados não encontrados. Tente novamente.")
        return ConversationHandler.END

    id_evento_real = dados["id_evento"]
    evento = dados["evento"]
    id_evento_sanitizado = dados["id_sanitizado"]

    # Atualiza o campo
    evento[campo_info["chave"]] = novo_valor

    # Encontra o índice atualizado
    eventos = listar_eventos()
    indice = None
    for i, ev in enumerate(eventos):
        if (ev.get("Data do evento", "") + " — " + ev.get("Nome da loja", "")) == id_evento_real:
            indice = i
            break

    if indice is None:
        await update.message.reply_text("Erro: evento não encontrado na lista atual.")
        return ConversationHandler.END

    # Salva na planilha
    if not atualizar_evento(indice, evento):
        await update.message.reply_text("Erro ao atualizar evento. Tente novamente.")
        return ConversationHandler.END

    # Remove todas as confirmações (pois o evento foi alterado)
    cancelar_todas_confirmacoes(id_evento_real)

    # Determina quem está editando
    user_id = update.effective_user.id
    nivel = get_nivel(user_id)
    autor_nome = "Administrador" if nivel == "3" else "Secretário"
    autor_info = f"pelo {autor_nome}"

    # Publica aviso de alteração no grupo
    grupo_id = evento.get("Telegram ID do grupo")
    if grupo_id and str(grupo_id).strip() not in ["", "N/A", "n/a"]:
        try:
            grupo_id_int = int(float(str(grupo_id).strip()))
            mensagem_grupo = (
                f"📝 *EVENTO ALTERADO {autor_info.upper()}*\n"
                f"━━━━━━━━━━━━━━━━\n"
                f"🏛 *LOJA {evento['Nome da loja']} {evento['Número da loja']}*\n"
                f"━━━━━━━━━━━━━━━━\n\n"
                f"📍 Nova data: {evento['Data do evento']}\n"
                f"🕕 Horário: {evento['Hora']}\n"
                f"📍 Oriente: {evento['Oriente']}\n\n"
                f"*Campo alterado:* {campo_info['nome']}\n"
                f"*Novo valor:* {novo_valor}\n\n"
                f"Todas as confirmações foram removidas. Por favor, reconfirme sua presença se necessário."
            )
            await context.bot.send_message(
                chat_id=grupo_id_int,
                text=mensagem_grupo,
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Erro ao publicar alteração: {e}")

    await update.message.reply_text(
        f"✅ {campo_info['nome']} atualizado com sucesso!\n"
        f"Todas as confirmações foram removidas e um aviso foi publicado no grupo.\n\n"
        f"Use /start para voltar ao menu principal."
    )

    context.user_data.pop("editando_evento", None)
    context.user_data.pop("campo_editando_evento", None)

    return ConversationHandler.END

async def cancelar_edicao(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Edição cancelada.")
    return ConversationHandler.END

editar_evento_secretario_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(iniciar_edicao, pattern="^editar_evento\\|")],
    states={
        EDITAR_CAMPO: [CallbackQueryHandler(selecionar_campo_evento, pattern="^editar_campo_evento\\|")],
        NOVO_VALOR: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_novo_valor_evento)],
    },
    fallbacks=[CommandHandler("cancelar", cancelar_edicao)],
)