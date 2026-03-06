# src/eventos_secretario.py
# ============================================
# BODE ANDARILHO - ÁREA DO SECRETÁRIO
# ============================================
# 
# Este módulo gerencia todas as funcionalidades exclusivas para secretários:
# - Visualização dos eventos criados pelo secretário
# - Gerenciamento de eventos (editar, cancelar)
# - Resumo rápido de confirmações
# - Cópia da lista de confirmados para compartilhamento
# 
# Todas as funções que exibem resultados utilizam o sistema de
# navegação do bot.py para manter a consistência da interface.
# 
# ============================================

from __future__ import annotations

import logging
import urllib.parse
from datetime import datetime
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
    _eh_vm,
)
from src.permissoes import get_nivel

from src.bot import (
    navegar_para,
    voltar_ao_menu_principal,
    _enviar_ou_editar_mensagem,
    TIPO_RESULTADO
)

logger = logging.getLogger(__name__)

# ============================================
# CONSTANTES E CONFIGURAÇÕES
# ============================================

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


# ============================================
# FUNÇÕES AUXILIARES
# ============================================

async def _safe_edit(query, text: str, **kwargs):
    """Edita mensagem ignorando erro 'Message not modified'."""
    try:
        await query.edit_message_text(text, **kwargs)
    except Exception as e:
        if "Message is not modified" not in str(e):
            raise


def _formatar_resumo_evento(evento: dict) -> str:
    """Formata o resumo de um evento para exibição."""
    nome = evento.get("Nome da loja", "")
    numero = evento.get("Número da loja", "")
    numero_fmt = f" {numero}" if numero else ""
    data_txt = evento.get("Data do evento", "")
    hora = evento.get("Hora", "")
    
    return f"🏛 {nome}{numero_fmt}\n📅 {data_txt} {hora}"


# ============================================
# FUNÇÃO PRINCIPAL DO MENU SECRETÁRIO
# ============================================

async def exibir_menu_secretario(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Exibe o menu principal da área do secretário.
    Esta função é chamada pelo bot.py quando o usuário acessa a área.
    """
    user_id = update.effective_user.id
    nivel = get_nivel(user_id)
    
    if nivel not in ["2", "3"]:
        await _enviar_ou_editar_mensagem(
            context, user_id, TIPO_RESULTADO,
            "⛔ Você não tem permissão para acessar esta área."
        )
        return

    teclado = InlineKeyboardMarkup([
        [InlineKeyboardButton("📌 Cadastrar evento", callback_data="cadastrar_evento")],
        [InlineKeyboardButton("📋 Meus eventos", callback_data="meus_eventos")],
        [InlineKeyboardButton("👥 Ver confirmados por evento", callback_data="ver_confirmados_secretario")],
        [InlineKeyboardButton("🏛️ Minhas lojas", callback_data="menu_lojas")],
        [InlineKeyboardButton("🔔 Configurar notificações", callback_data="menu_notificacoes")],
        [InlineKeyboardButton("🔙 Voltar ao menu", callback_data="menu_principal")],
    ])

    await navegar_para(
        update, context,
        "Área do Secretário",
        "📋 *Bem-vindo à Área do Secretário*\n\nO que deseja fazer?",
        teclado
    )


# ============================================
# MEUS EVENTOS (LISTAGEM)
# ============================================

async def meus_eventos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lista os eventos do secretário (ou todos se for admin)."""
    user_id = update.effective_user.id
    nivel = get_nivel(user_id)

    eventos = listar_eventos() or []
    
    if nivel == "3":
        eventos_filtrados = [ev for ev in eventos if ev.get("Status", "").lower() in ("ativo", "")]
        titulo = "📋 *Todos os eventos*"
    else:
        eventos_filtrados = [
            ev for ev in eventos 
            if str(ev.get("Telegram ID do secretário", "")).strip() == str(user_id)
        ]
        titulo = "📋 *Meus eventos*"

    # Filtra apenas eventos futuros
    hoje = datetime.now().date()
    eventos_futuros = []
    for ev in eventos_filtrados:
        data_str = ev.get("Data do evento", "")
        try:
            data_evento = datetime.strptime(data_str, "%d/%m/%Y").date()
            if data_evento >= hoje:
                eventos_futuros.append(ev)
        except:
            eventos_futuros.append(ev)

    if not eventos_futuros:
        teclado = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Cadastrar evento", callback_data="cadastrar_evento")],
            [InlineKeyboardButton("🔙 Voltar", callback_data="area_secretario")],
        ])
        await navegar_para(
            update, context,
            "Área do Secretário > Meus Eventos",
            f"{titulo}\n\nNenhum evento futuro encontrado.",
            teclado
        )
        return

    eventos_futuros = _eventos_ordenados(eventos_futuros)
    botoes = []
    for ev in eventos_futuros[:20]:
        id_evento = normalizar_id_evento(ev)
        botoes.append([
            InlineKeyboardButton(
                _linha_botao_evento(ev),
                callback_data=f"gerenciar_evento|{_encode_cb(id_evento)}"
            )
        ])

    botoes.append([InlineKeyboardButton("➕ Cadastrar novo", callback_data="cadastrar_evento")])
    botoes.append([InlineKeyboardButton("🔙 Voltar", callback_data="area_secretario")])

    await navegar_para(
        update, context,
        "Área do Secretário > Meus Eventos",
        f"{titulo}\n\nSelecione um evento para gerenciar:",
        InlineKeyboardMarkup(botoes)
    )


# ============================================
# GERENCIAMENTO DE EVENTO
# ============================================

async def menu_gerenciar_evento(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menu de opções para gerenciar um evento específico."""
    query = update.callback_query
    _, id_evento_cod = query.data.split("|", 1)
    id_evento = _decode_cb(id_evento_cod)

    eventos = listar_eventos() or []
    evento = next((ev for ev in eventos if normalizar_id_evento(ev) == id_evento), None)

    if not evento:
        await _enviar_ou_editar_mensagem(
            context, update.effective_user.id, TIPO_RESULTADO,
            "Evento não encontrado."
        )
        return

    # Verifica permissão
    user_id = update.effective_user.id
    criador_id = str(evento.get("Telegram ID do secretário", "")).strip()
    nivel = get_nivel(user_id)
    
    if str(user_id) != criador_id and nivel != "3":
        await _enviar_ou_editar_mensagem(
            context, user_id, TIPO_RESULTADO,
            "⛔ Você não tem permissão para gerenciar este evento."
        )
        return

    context.user_data["evento_gerenciado_id"] = id_evento
    context.user_data["evento_gerenciado_dados"] = evento

    nome = evento.get("Nome da loja", "")
    data_txt = evento.get("Data do evento", "")
    hora = evento.get("Hora", "")

    teclado = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Resumo da sessão", callback_data=f"resumo_evento|{_encode_cb(id_evento)}")],
        [InlineKeyboardButton("✏️ Editar evento", callback_data="editar_evento_secretario")],
        [InlineKeyboardButton("👥 Ver confirmados", callback_data=f"ver_confirmados|{_encode_cb(id_evento)}")],
        [InlineKeyboardButton("📋 Copiar lista", callback_data=f"copiar_lista|{_encode_cb(id_evento)}")],
        [InlineKeyboardButton("❌ Cancelar evento", callback_data=f"confirmar_cancelamento|{_encode_cb(id_evento)}")],
        [InlineKeyboardButton("🔙 Voltar", callback_data="meus_eventos")],
    ])

    await navegar_para(
        update, context,
        f"Área do Secretário > {nome}",
        f"*Gerenciar evento*\n\n{_formatar_resumo_evento(evento)}\n\nEscolha uma opção:",
        teclado
    )


# ============================================
# RESUMO DE CONFIRMAÇÕES
# ============================================

async def resumo_confirmados(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Exibe um resumo rápido das confirmações do evento."""
    query = update.callback_query
    _, id_evento_cod = query.data.split("|", 1)
    id_evento = _decode_cb(id_evento_cod)

    eventos = listar_eventos() or []
    evento = next((ev for ev in eventos if normalizar_id_evento(ev) == id_evento), None)

    if not evento:
        await _enviar_ou_editar_mensagem(
            context, update.effective_user.id, TIPO_RESULTADO,
            "Evento não encontrado."
        )
        return

    # Verifica permissão
    user_id = update.effective_user.id
    criador_id = str(evento.get("Telegram ID do secretário", "")).strip()
    nivel = get_nivel(user_id)
    
    if str(user_id) != criador_id and nivel != "3":
        await _enviar_ou_editar_mensagem(
            context, user_id, TIPO_RESULTADO,
            "⛔ Permissão negada."
        )
        return

    confirmacoes = listar_confirmacoes_por_evento(id_evento) or []
    
    total = len(confirmacoes)
    com_agape = 0
    sem_agape = 0
    lista_detalhada = []

    for c in confirmacoes:
        agape = str(c.get("Ágape", "") or "").lower()
        if "com ágape" in agape or "confirmada" in agape:
            com_agape += 1
        else:
            sem_agape += 1

        tid = c.get("Telegram ID") or c.get("telegram_id")
        if tid:
            try:
                membro = buscar_membro(int(float(tid)))
                if membro:
                    nome = membro.get("Nome", "Desconhecido")
                    grau = membro.get("Grau", "")
                    vm = "VM " if _eh_vm(membro) else ""
                else:
                    nome = c.get("Nome", "Desconhecido")
                    grau = c.get("Grau", "")
                    vm = ""
            except:
                nome = c.get("Nome", "Desconhecido")
                grau = c.get("Grau", "")
                vm = ""
        else:
            nome = c.get("Nome", "Desconhecido")
            grau = c.get("Grau", "")
            vm = ""

        tipo_agape = "Com ágape" if "com ágape" in agape else "Sem ágape"
        lista_detalhada.append(f"• {vm}{nome} - {grau} ({tipo_agape})")

    nome_loja = evento.get("Nome da loja", "")
    numero = evento.get("Número da loja", "")
    numero_fmt = f" {numero}" if numero else ""
    data_txt = evento.get("Data do evento", "")
    hora = evento.get("Hora", "")

    resumo = (
        f"📊 *RESUMO DA SESSÃO*\n\n"
        f"🏛 {nome_loja}{numero_fmt}\n"
        f"📅 {data_txt} - {hora}\n\n"
        f"✅ *Total de confirmados:* {total}\n"
        f"🍽 *Com ágape:* {com_agape}\n"
        f"🚫 *Sem ágape:* {sem_agape}\n\n"
    )

    if lista_detalhada:
        resumo += "*Lista resumida:*\n" + "\n".join(lista_detalhada[:15])
        if len(lista_detalhada) > 15:
            resumo += f"\n... e mais {len(lista_detalhada) - 15} irmãos"
    else:
        resumo += "Nenhuma confirmação até o momento."

    teclado = InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 Ver lista completa", callback_data=f"ver_confirmados|{_encode_cb(id_evento)}")],
        [InlineKeyboardButton("🔙 Voltar", callback_data=f"gerenciar_evento|{_encode_cb(id_evento)}")],
    ])

    await navegar_para(
        update, context,
        f"Área do Secretário > Resumo",
        resumo,
        teclado
    )


# ============================================
# COPIAR LISTA DE CONFIRMADOS
# ============================================

async def copiar_lista_confirmados(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gera um texto formatado da lista de confirmados para copiar."""
    query = update.callback_query
    _, id_evento_cod = query.data.split("|", 1)
    id_evento = _decode_cb(id_evento_cod)

    eventos = listar_eventos() or []
    evento = next((ev for ev in eventos if normalizar_id_evento(ev) == id_evento), None)

    if not evento:
        await _enviar_ou_editar_mensagem(
            context, update.effective_user.id, TIPO_RESULTADO,
            "Evento não encontrado."
        )
        return

    # Verifica permissão
    user_id = update.effective_user.id
    criador_id = str(evento.get("Telegram ID do secretário", "")).strip()
    nivel = get_nivel(user_id)
    
    if str(user_id) != criador_id and nivel != "3":
        await _enviar_ou_editar_mensagem(
            context, user_id, TIPO_RESULTADO,
            "⛔ Permissão negada."
        )
        return

    confirmacoes = listar_confirmacoes_por_evento(id_evento) or []
    
    nome_loja = evento.get("Nome da loja", "")
    numero = evento.get("Número da loja", "")
    numero_fmt = f" {numero}" if numero else ""
    data_txt = evento.get("Data do evento", "")
    hora = evento.get("Hora", "")

    com_agape = []
    sem_agape = []
    
    for c in confirmacoes:
        tid = c.get("Telegram ID") or c.get("telegram_id")
        if tid:
            try:
                membro = buscar_membro(int(float(tid)))
                if membro:
                    nome = membro.get("Nome", "Desconhecido")
                    grau = membro.get("Grau", "")
                    vm = "VM " if _eh_vm(membro) else ""
                else:
                    nome = c.get("Nome", "Desconhecido")
                    grau = c.get("Grau", "")
                    vm = ""
            except:
                nome = c.get("Nome", "Desconhecido")
                grau = c.get("Grau", "")
                vm = ""
        else:
            nome = c.get("Nome", "Desconhecido")
            grau = c.get("Grau", "")
            vm = ""

        agape_texto = str(c.get("Ágape", "") or "").lower()
        if "com ágape" in agape_texto or "confirmada" in agape_texto:
            com_agape.append(f"• {vm}{nome} - {grau}")
        else:
            sem_agape.append(f"• {vm}{nome} - {grau}")

    total = len(confirmacoes)
    total_com = len(com_agape)
    total_sem = len(sem_agape)

    linhas = []
    linhas.append(f"📋 LISTA DE CONFIRMADOS - {nome_loja}{numero_fmt}")
    linhas.append(f"📅 {data_txt} - {hora}")
    linhas.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    linhas.append("")
    linhas.append(f"📊 TOTAL: {total} irmãos")
    linhas.append(f"🍽 COM ÁGAPE: {total_com}")
    linhas.append(f"🚫 SEM ÁGAPE: {total_sem}")
    linhas.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    linhas.append("")
    
    if com_agape:
        linhas.append("COM ÁGAPE:")
        linhas.extend(com_agape)
        linhas.append("")
    
    if sem_agape:
        linhas.append("SEM ÁGAPE:")
        linhas.extend(sem_agape)
        linhas.append("")
    
    linhas.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    linhas.append("📎 Clique no texto acima, selecione 'Copiar' e cole onde desejar.")

    texto_final = "\n".join(linhas)

    # Envia como mensagem separada (não no sistema de navegação)
    await context.bot.send_message(
        chat_id=user_id,
        text=texto_final,
        parse_mode=None,
    )

    await query.answer("✅ Lista gerada! Verifique a mensagem acima.")


# ============================================
# CANCELAMENTO DE EVENTO
# ============================================

async def confirmar_cancelamento(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Primeiro passo: pede confirmação para cancelar o evento."""
    query = update.callback_query
    _, id_evento_cod = query.data.split("|", 1)
    id_evento = _decode_cb(id_evento_cod)

    eventos = listar_eventos() or []
    evento = next((ev for ev in eventos if normalizar_id_evento(ev) == id_evento), None)

    if not evento:
        await _enviar_ou_editar_mensagem(
            context, update.effective_user.id, TIPO_RESULTADO,
            "Evento não encontrado."
        )
        return

    # Verifica permissão
    user_id = update.effective_user.id
    criador_id = str(evento.get("Telegram ID do secretário", "")).strip()
    nivel = get_nivel(user_id)
    
    if str(user_id) != criador_id and nivel != "3":
        await _enviar_ou_editar_mensagem(
            context, user_id, TIPO_RESULTADO,
            "⛔ Permissão negada."
        )
        return

    nome = evento.get("Nome da loja", "")
    data_txt = evento.get("Data do evento", "")
    hora = evento.get("Hora", "")

    teclado = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Sim, cancelar evento", callback_data=f"cancelar_evento|{_encode_cb(id_evento)}")],
        [InlineKeyboardButton("❌ Não, voltar", callback_data=f"gerenciar_evento|{_encode_cb(id_evento)}")],
    ])

    await navegar_para(
        update, context,
        f"Área do Secretário > Cancelar",
        f"*Cancelar evento*\n\nTem certeza que deseja cancelar o evento?\n"
        f"{_formatar_resumo_evento(evento)}\n\n"
        f"⚠️ Isso removerá todas as confirmações.",
        teclado
    )


async def executar_cancelamento(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Executa o cancelamento do evento."""
    query = update.callback_query
    _, id_evento_cod = query.data.split("|", 1)
    id_evento = _decode_cb(id_evento_cod)

    eventos = listar_eventos() or []
    evento = next((ev for ev in eventos if normalizar_id_evento(ev) == id_evento), None)

    if not evento:
        await _enviar_ou_editar_mensagem(
            context, update.effective_user.id, TIPO_RESULTADO,
            "Evento não encontrado."
        )
        return

    # Verifica permissão
    user_id = update.effective_user.id
    criador_id = str(evento.get("Telegram ID do secretário", "")).strip()
    nivel = get_nivel(user_id)
    
    if str(user_id) != criador_id and nivel != "3":
        await _enviar_ou_editar_mensagem(
            context, user_id, TIPO_RESULTADO,
            "⛔ Permissão negada."
        )
        return

    evento["Status"] = "Cancelado"
    sucesso = atualizar_evento(0, evento)
    
    if sucesso:
        cancelar_todas_confirmacoes(id_evento)
        await navegar_para(
            update, context,
            "Área do Secretário",
            "✅ Evento cancelado com sucesso.\nTodas as confirmações foram removidas.",
            InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Voltar", callback_data="meus_eventos")
            ]])
        )
    else:
        await _enviar_ou_editar_mensagem(
            context, user_id, TIPO_RESULTADO,
            "❌ Erro ao cancelar evento. Tente novamente mais tarde."
        )

    context.user_data.pop("evento_gerenciado_id", None)
    context.user_data.pop("evento_gerenciado_dados", None)


# ============================================
# EDIÇÃO DE EVENTO (CONVERSATION HANDLER)
# ============================================

async def editar_evento_inicio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Inicia o processo de edição de um evento."""
    query = update.callback_query
    await query.answer()

    if query.data != "editar_evento_secretario":
        return ConversationHandler.END

    evento = context.user_data.get("evento_gerenciado_dados")
    if not evento:
        await _enviar_ou_editar_mensagem(
            context, update.effective_user.id, TIPO_RESULTADO,
            "Dados do evento não encontrados. Tente novamente."
        )
        return ConversationHandler.END

    botoes = []
    for campo_id, campo_info in CAMPOS_EVENTO_EDITAVEIS.items():
        valor_atual = evento.get(campo_info["chave"], "")
        botoes.append([
            InlineKeyboardButton(
                f"✏️ {campo_info['nome']}: {str(valor_atual)[:30]}",
                callback_data=f"editar_campo_evento|{campo_id}"
            )
        ])

    botoes.append([InlineKeyboardButton("🔙 Cancelar", callback_data=f"gerenciar_evento|{_encode_cb(normalizar_id_evento(evento))}")])
    teclado = InlineKeyboardMarkup(botoes)

    await navegar_para(
        update, context,
        f"Área do Secretário > Editar",
        f"*Editando evento:* {evento.get('Nome da loja', '')}\n\nSelecione o campo que deseja alterar:",
        teclado
    )
    return SELECIONAR_CAMPO


async def selecionar_campo_evento(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Usuário selecionou um campo para editar."""
    query = update.callback_query
    await query.answer()

    data = query.data
    if not data.startswith("editar_campo_evento|"):
        return ConversationHandler.END

    campo_id = data.split("|")[1]
    campo_info = CAMPOS_EVENTO_EDITAVEIS.get(campo_id)
    if not campo_info:
        await _enviar_ou_editar_mensagem(
            context, update.effective_user.id, TIPO_RESULTADO,
            "Campo inválido."
        )
        return ConversationHandler.END

    context.user_data["editando_campo_evento"] = campo_id
    evento = context.user_data.get("evento_gerenciado_dados", {})
    valor_atual = evento.get(campo_info["chave"], "")

    await navegar_para(
        update, context,
        f"Área do Secretário > Editar > {campo_info['nome']}",
        f"✏️ *Editando {campo_info['nome']}*\n\n"
        f"Valor atual: {valor_atual}\n\n"
        f"Digite o novo valor (ou /cancelar para desistir):",
        None
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

    evento[campo_info["chave"]] = novo_valor

    id_evento = normalizar_id_evento(evento)
    sucesso = atualizar_evento(0, evento)

    if sucesso:
        await update.message.reply_text(
            f"✅ {campo_info['nome']} atualizado com sucesso!\n\n"
            f"Use o menu acima para continuar."
        )
    else:
        await update.message.reply_text("❌ Erro ao atualizar o campo. Tente novamente mais tarde.")

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


# ============================================
# CONVERSATION HANDLER
# ============================================

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