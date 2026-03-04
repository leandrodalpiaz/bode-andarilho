# src/eventos_secretario.py
from __future__ import annotations

import logging
import urllib.parse
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    CommandHandler,
)

from src.sheets import (
    listar_eventos,
    buscar_membro,
    listar_confirmacoes_por_evento,
    cancelar_todas_confirmacoes,
    atualizar_evento,
    cadastrar_evento,
)
from src.eventos import (
    normalizar_id_evento,
    _encode_cb,
    _decode_cb,
    _linha_botao_evento,
    montar_linha_confirmado,
    _eventos_ordenados,
    parse_data_evento,
    traduzir_dia,
)
from src.permissoes import get_nivel

logger = logging.getLogger(__name__)

# Estados da conversação para edição de evento
SELECIONAR_CAMPO, NOVO_VALOR = range(2)

# Mapeamento de campos editáveis por secretário/admin
CAMPOS_EVENTO_EDITAVEIS = {
    "data": {"nome": "Data do evento (DD/MM/AAAA)", "chave": "Data do evento"},
    "hora": {"nome": "Horário (HH:MM)", "chave": "Hora"},
    "nome_loja": {"nome": "Nome da loja", "chave": "Nome da loja"},
    "numero_loja": {"nome": "Número da loja", "chave": "Número da loja"},
    "oriente": {"nome": "Oriente", "chave": "Oriente"},
    "grau": {"nome": "Grau mínimo", "chave": "Grau"},
    "tipo_sessao": {"nome": "Tipo de sessão", "chave": "Tipo de sessão"},
    "rito": {"nome": "Rito", "chave": "Rito"},
    "potencia": {"nome": "Potência", "chave": "Potência"},
    "traje": {"nome": "Traje obrigatório", "chave": "Traje obrigatório"},
    "agape": {"nome": "Ágape (texto livre)", "chave": "Ágape"},
    "observacoes": {"nome": "Observações", "chave": "Observações"},
    "endereco": {"nome": "Endereço da sessão", "chave": "Endereço da sessão"},
}


async def _safe_edit(query, text: str, **kwargs):
    try:
        await query.edit_message_text(text, **kwargs)
    except Exception as e:
        if "Message is not modified" not in str(e):
            raise


# =========================
# 1. Meus eventos (listagem)
# =========================
async def meus_eventos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lista todos os eventos criados pelo secretário (Telegram ID do secretário)."""
    query = update.callback_query
    if not query:
        return
    await query.answer()

    user_id = update.effective_user.id
    nivel = get_nivel(user_id)
    if nivel not in ("2", "3"):
        await _safe_edit(query, "⛔ Acesso negado.")
        return

    eventos = listar_eventos() or []
    # Filtra eventos onde o Telegram ID do secretário corresponde ao user_id
    meus = [ev for ev in eventos if str(ev.get("Telegram ID do secretário", "")).strip() == str(user_id)]

    if not meus:
        teclado = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Cadastrar evento", callback_data="cadastrar_evento")],
            [InlineKeyboardButton("⬅️ Voltar", callback_data="area_secretario")],
        ])
        await _safe_edit(query, "Você ainda não cadastrou nenhum evento.", reply_markup=teclado)
        return

    meus = _eventos_ordenados(meus)
    botoes = []
    for ev in meus[:20]:  # limite para não estourar
        id_evento = normalizar_id_evento(ev)
        botoes.append([
            InlineKeyboardButton(
                _linha_botao_evento(ev),
                callback_data=f"gerenciar_evento|{_encode_cb(id_evento)}"
            )
        ])

    botoes.append([InlineKeyboardButton("➕ Cadastrar novo", callback_data="cadastrar_evento")])
    botoes.append([InlineKeyboardButton("⬅️ Voltar", callback_data="area_secretario")])

    await _safe_edit(
        query,
        "📋 *Meus eventos*\n\nSelecione um evento para gerenciar:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(botoes),
    )


# =========================
# 2. Menu de gerenciamento de um evento específico
# =========================
async def menu_gerenciar_evento(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mostra opções para editar, ver confirmados, cancelar evento."""
    query = update.callback_query
    if not query:
        return
    await query.answer()

    data = query.data
    if not data.startswith("gerenciar_evento|"):
        return

    _, id_evento_cod = data.split("|", 1)
    id_evento = _decode_cb(id_evento_cod)

    eventos = listar_eventos() or []
    evento = next((ev for ev in eventos if normalizar_id_evento(ev) == id_evento), None)
    if not evento:
        await _safe_edit(query, "Evento não encontrado.")
        return

    # Verifica permissão: só quem criou ou admin pode gerenciar
    user_id = update.effective_user.id
    criador_id = str(evento.get("Telegram ID do secretário", "")).strip()
    nivel = get_nivel(user_id)
    if str(user_id) != criador_id and nivel != "3":
        await _safe_edit(query, "⛔ Você não tem permissão para gerenciar este evento.")
        return

    context.user_data["evento_gerenciado_id"] = id_evento
    context.user_data["evento_gerenciado_dados"] = evento

    nome = evento.get("Nome da loja", "")
    data_txt = evento.get("Data do evento", "")
    hora = evento.get("Hora", "")

    teclado = InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Editar evento", callback_data="editar_evento_secretario")],
        [InlineKeyboardButton("👥 Ver confirmados", callback_data=f"ver_confirmados|{_encode_cb(id_evento)}")],
        [InlineKeyboardButton("❌ Cancelar evento", callback_data=f"confirmar_cancelamento|{_encode_cb(id_evento)}")],
        [InlineKeyboardButton("⬅️ Voltar", callback_data="meus_eventos")],
    ])

    await _safe_edit(
        query,
        f"*Gerenciar evento*\n\n"
        f"🏛 {nome}\n"
        f"📅 {data_txt} {hora}\n\n"
        f"Escolha uma opção:",
        parse_mode="Markdown",
        reply_markup=teclado,
    )


# =========================
# 3. Cancelar evento (com confirmação)
# =========================
async def confirmar_cancelamento(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Primeiro passo: pede confirmação para cancelar o evento."""
    query = update.callback_query
    if not query:
        return
    await query.answer()

    data = query.data
    if not data.startswith("confirmar_cancelamento|"):
        return

    _, id_evento_cod = data.split("|", 1)
    id_evento = _decode_cb(id_evento_cod)

    eventos = listar_eventos() or []
    evento = next((ev for ev in eventos if normalizar_id_evento(ev) == id_evento), None)
    if not evento:
        await _safe_edit(query, "Evento não encontrado.")
        return

    # Verifica permissão novamente
    user_id = update.effective_user.id
    criador_id = str(evento.get("Telegram ID do secretário", "")).strip()
    nivel = get_nivel(user_id)
    if str(user_id) != criador_id and nivel != "3":
        await _safe_edit(query, "⛔ Permissão negada.")
        return

    nome = evento.get("Nome da loja", "")
    data_txt = evento.get("Data do evento", "")
    hora = evento.get("Hora", "")

    teclado = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Sim, cancelar evento", callback_data=f"cancelar_evento|{_encode_cb(id_evento)}")],
        [InlineKeyboardButton("❌ Não, voltar", callback_data=f"gerenciar_evento|{_encode_cb(id_evento)}")],
    ])

    await _safe_edit(
        query,
        f"*Cancelar evento*\n\n"
        f"Tem certeza que deseja cancelar o evento?\n"
        f"🏛 {nome}\n"
        f"📅 {data_txt} {hora}\n\n"
        f"⚠️ Isso removerá todas as confirmações e marcará o evento como cancelado.",
        parse_mode="Markdown",
        reply_markup=teclado,
    )


async def executar_cancelamento(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Executa o cancelamento do evento: muda status e remove confirmações."""
    query = update.callback_query
    if not query:
        return
    await query.answer()

    data = query.data
    if not data.startswith("cancelar_evento|"):
        return

    _, id_evento_cod = data.split("|", 1)
    id_evento = _decode_cb(id_evento_cod)

    eventos = listar_eventos() or []
    evento = next((ev for ev in eventos if normalizar_id_evento(ev) == id_evento), None)
    if not evento:
        await _safe_edit(query, "Evento não encontrado.")
        return

    # Verifica permissão
    user_id = update.effective_user.id
    criador_id = str(evento.get("Telegram ID do secretário", "")).strip()
    nivel = get_nivel(user_id)
    if str(user_id) != criador_id and nivel != "3":
        await _safe_edit(query, "⛔ Permissão negada.")
        return

    # Atualiza status para "Cancelado"
    evento["Status"] = "Cancelado"
    sucesso = atualizar_evento(0, evento)  # usando o índice 0, mas a função ignora e usa ID se possível
    if sucesso:
        # Remove todas as confirmações
        cancelar_todas_confirmacoes(id_evento)
        await _safe_edit(query, "✅ Evento cancelado com sucesso.\nTodas as confirmações foram removidas.")
    else:
        await _safe_edit(query, "❌ Erro ao cancelar evento. Tente novamente mais tarde.")

    context.user_data.pop("evento_gerenciado_id", None)
    context.user_data.pop("evento_gerenciado_dados", None)


# =========================
# 4. Editar evento (ConversationHandler)
# =========================
async def editar_evento_inicio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Inicia o processo de edição de um evento (chamado pelo menu gerenciar)."""
    query = update.callback_query
    if not query:
        return ConversationHandler.END
    await query.answer()

    if query.data != "editar_evento_secretario":
        return ConversationHandler.END

    evento = context.user_data.get("evento_gerenciado_dados")
    if not evento:
        await _safe_edit(query, "Dados do evento não encontrados. Tente novamente.")
        return ConversationHandler.END

    # Cria botões para os campos editáveis
    botoes = []
    for campo_id, campo_info in CAMPOS_EVENTO_EDITAVEIS.items():
        valor_atual = evento.get(campo_info["chave"], "")
        if valor_atual is None:
            valor_atual = ""
        botoes.append([
            InlineKeyboardButton(
                f"✏️ {campo_info['nome']}: {str(valor_atual)[:30]}",
                callback_data=f"editar_campo_evento|{campo_id}"
            )
        ])

    botoes.append([InlineKeyboardButton("⬅️ Cancelar", callback_data=f"gerenciar_evento|{_encode_cb(normalizar_id_evento(evento))}")])
    teclado = InlineKeyboardMarkup(botoes)

    await _safe_edit(
        query,
        f"*Editando evento:* {evento.get('Nome da loja', '')}\n\n"
        f"Selecione o campo que deseja alterar:",
        parse_mode="Markdown",
        reply_markup=teclado,
    )
    return SELECIONAR_CAMPO


async def selecionar_campo_evento(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Usuário selecionou um campo para editar."""
    query = update.callback_query
    if not query:
        return ConversationHandler.END
    await query.answer()

    data = query.data
    if not data.startswith("editar_campo_evento|"):
        return ConversationHandler.END

    campo_id = data.split("|")[1]
    campo_info = CAMPOS_EVENTO_EDITAVEIS.get(campo_id)
    if not campo_info:
        await _safe_edit(query, "Campo inválido.")
        return ConversationHandler.END

    context.user_data["editando_campo_evento"] = campo_id
    evento = context.user_data.get("evento_gerenciado_dados", {})
    valor_atual = evento.get(campo_info["chave"], "")

    await _safe_edit(
        query,
        f"✏️ *Editando {campo_info['nome']}*\n\n"
        f"Valor atual: {valor_atual}\n\n"
        f"Digite o novo valor (ou /cancelar para desistir):",
        parse_mode="Markdown",
    )
    return NOVO_VALOR


async def receber_novo_valor_evento(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recebe o novo valor e atualiza o evento."""
    novo_valor = update.message.text.strip()
    campo_id = context.user_data.get("editando_campo_evento")
    if not campo_id:
        await update.message.reply_text("Erro: dados não encontrados. Tente novamente.")
        return ConversationHandler.END

    campo_info = CAMPOS_EVENTO_EDITAVEIS.get(campo_id)
    evento = context.user_data.get("evento_gerenciado_dados")
    if not campo_info or not evento:
        await update.message.reply_text("Erro: dados do evento não encontrados.")
        return ConversationHandler.END

    # Atualiza o dicionário do evento
    evento[campo_info["chave"]] = novo_valor

    # Salva na planilha
    id_evento = normalizar_id_evento(evento)
    sucesso = atualizar_evento(0, evento)  # a função atualizar_evento usa ID se disponível

    if sucesso:
        await update.message.reply_text(
            f"✅ {campo_info['nome']} atualizado com sucesso para:\n{novo_valor}\n\n"
            f"Use /start para voltar ao menu principal."
        )
    else:
        await update.message.reply_text("❌ Erro ao atualizar o campo. Tente novamente mais tarde.")

    # Limpa dados da sessão
    context.user_data.pop("editando_campo_evento", None)
    context.user_data.pop("evento_gerenciado_id", None)
    context.user_data.pop("evento_gerenciado_dados", None)
    return ConversationHandler.END


async def cancelar_edicao_evento(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancela o processo de edição."""
    await update.message.reply_text("Edição cancelada.")
    context.user_data.pop("editando_campo_evento", None)
    context.user_data.pop("evento_gerenciado_id", None)
    context.user_data.pop("evento_gerenciado_dados", None)
    return ConversationHandler.END


# ConversationHandler para editar evento
editar_evento_secretario_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(editar_evento_inicio, pattern="^editar_evento_secretario$")],
    states={
        SELECIONAR_CAMPO: [CallbackQueryHandler(selecionar_campo_evento, pattern="^editar_campo_evento\|")],
        NOVO_VALOR: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_novo_valor_evento)],
    },
    fallbacks=[
        CommandHandler("cancelar", cancelar_edicao_evento),
        CallbackQueryHandler(cancelar_edicao_evento, pattern="^cancelar$"),
    ],
)