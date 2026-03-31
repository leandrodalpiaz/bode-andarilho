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

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.error import Forbidden
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    CommandHandler,
)

from src.sheets_supabase import (
    listar_eventos,
    buscar_membro,
    listar_confirmacoes_por_evento,
    cancelar_todas_confirmacoes,
    atualizar_evento,
    obter_secretario_responsavel_evento,
    usuario_pode_gerenciar_evento,
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
    sincronizar_resumo_evento_grupo,
)
from src.permissoes import get_nivel
from src.ajuda.dicas import enviar_dica_contextual
from src.miniapp import WEBAPP_URL_EVENTO

from src.bot import (
    navegar_para,
    voltar_ao_menu_principal,
    _enviar_ou_editar_mensagem,
    TIPO_RESULTADO
)
from src.messages import (
    EDICAO_EVENTO_DADOS_NAO_ENCONTRADOS,
    EDICAO_EVENTO_CONTEXTO_PERDIDO,
    EDICAO_EVENTO_SUCESSO_TMPL,
    EDICAO_EVENTO_FALHA,
    EDICAO_EVENTO_CANCELADA,
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
    "observacoes": {"nome": "Ordem do dia / observações", "chave": "Observações"},
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


def _confirmacao_com_agape(agape_valor: str) -> bool:
    """Identifica confirmações com ágape em diferentes formatos legados."""
    texto = str(agape_valor or "").lower()
    if "sem ágape" in texto or "sem agape" in texto:
        return False
    marcadores = ("com ágape", "com agape", "confirmada", "gratuito", "pago", "sim")
    return any(marcador in texto for marcador in marcadores)


def _callback_voltar_area(nivel: str) -> str:
    """Define para qual painel o usuário deve voltar."""
    return "area_admin" if str(nivel) == "3" else "area_secretario"


def _botao_cadastrar_evento(texto: str = "📌 Cadastrar evento") -> InlineKeyboardButton:
    """Retorna botão de cadastro priorizando o Mini App."""
    if WEBAPP_URL_EVENTO:
        return InlineKeyboardButton(texto, web_app=WebAppInfo(url=WEBAPP_URL_EVENTO))
    return InlineKeyboardButton(texto, callback_data="cadastrar_evento")


def _registrar_ultima_edicao(evento: dict, user_id: int, user_nome: str = "") -> None:
    """Atualiza campos de auditoria de edição no payload do evento."""
    evento["Última edição por (Telegram ID)"] = str(user_id)
    evento["Última edição por (Nome)"] = (user_nome or "").strip()


async def _notificar_confirmados_evento(
    context: ContextTypes.DEFAULT_TYPE,
    evento: dict,
    id_evento: str,
    motivo: str,
    editor_id: Optional[int] = None,
    campo_nome: str = "",
    novo_valor: str = "",
    confirmacoes: Optional[list] = None,
) -> None:
    """Notifica no privado os irmãos que já confirmaram presença no evento."""
    confirmacoes = confirmacoes if confirmacoes is not None else (listar_confirmacoes_por_evento(id_evento) or [])
    if not confirmacoes:
        return

    nome_loja = str(evento.get("Nome da loja", "") or "").strip()
    numero = str(evento.get("Número da loja", "") or "").strip()
    numero_fmt = f" {numero}" if numero else ""
    data_txt = str(evento.get("Data do evento", "") or "").strip()
    hora = str(evento.get("Hora", "") or "").strip()

    teclado = None

    if motivo == "cancelamento":
        texto = (
            "⛔ *SESSÃO CANCELADA*\n\n"
            "A sessão que você havia confirmado foi cancelada pelo secretário.\n\n"
            f"🏛 {nome_loja}{numero_fmt}\n"
            f"📅 {data_txt}\n"
            f"🕕 {hora}\n\n"
            "Sua confirmação foi removida automaticamente."
        )
        teclado = InlineKeyboardMarkup([
            [InlineKeyboardButton("🏠 Menu principal", callback_data="menu_principal")]
        ])
    elif motivo == "refazer":
        texto = (
            "🔄 *SESSÃO REABERTA*\n\n"
            "A sessão foi reativada e está novamente disponível para confirmações.\n\n"
            f"🏛 {nome_loja}{numero_fmt}\n"
            f"📅 {data_txt}\n"
            f"🕕 {hora}\n\n"
            "Se desejar participar, confirme novamente no bot."
        )
        teclado = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔎 Ver sessão", callback_data=f"evento|{_encode_cb(id_evento)}")],
            [InlineKeyboardButton("🏠 Menu principal", callback_data="menu_principal")],
        ])
    else:
        detalhe = ""
        if campo_nome:
            detalhe = f"Campo alterado: *{campo_nome}*\nNovo valor: *{novo_valor or '-'}*\n\n"
        texto = (
            "⚠️ *ATUALIZAÇÃO NA SESSÃO*\n\n"
            "A sessão que você confirmou teve alteração de informações.\n\n"
            f"🏛 {nome_loja}{numero_fmt}\n"
            f"📅 {data_txt}\n"
            f"🕕 {hora}\n\n"
            f"{detalhe}"
            "Confira os detalhes atualizados no bot."
        )
        teclado = InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Cancelar presença", callback_data=f"cancelar|{_encode_cb(id_evento)}")],
            [InlineKeyboardButton("🔎 Ver sessão", callback_data=f"evento|{_encode_cb(id_evento)}")],
            [InlineKeyboardButton("🏠 Menu principal", callback_data="menu_principal")],
        ])

    enviados = 0
    for c in confirmacoes:
        raw_tid = c.get("Telegram ID", c.get("telegram_id", ""))
        try:
            tid = int(float(str(raw_tid).strip()))
        except Exception:
            continue

        if editor_id and tid == int(editor_id):
            continue

        try:
            await context.bot.send_message(
                chat_id=tid,
                text=texto,
                parse_mode="Markdown",
                reply_markup=teclado,
            )
            enviados += 1
        except Forbidden:
            logger.info("Não foi possível notificar %s no privado (bloqueado/iniciou sem chat).", tid)
        except Exception as e:
            logger.warning("Falha ao notificar %s sobre atualização do evento %s: %s", tid, id_evento, e)

    logger.info("Notificações privadas enviadas para %s confirmado(s) do evento %s (motivo=%s).", enviados, id_evento, motivo)


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
        [_botao_cadastrar_evento()],
        [InlineKeyboardButton("📋 Meus eventos", callback_data="meus_eventos")],
        [InlineKeyboardButton("👥 Ver confirmados por evento", callback_data="ver_confirmados_secretario")],
        [InlineKeyboardButton("🏛️ Minhas lojas", callback_data="menu_lojas")],
        [InlineKeyboardButton("🔔 Configurar notificações", callback_data="menu_notificacoes")],
        [InlineKeyboardButton("🏆 Meus Marcos de Secretário", callback_data="mostrar_marcos_secretario")],
        [InlineKeyboardButton("🔄 Ver eventos cancelados", callback_data="listar_eventos_cancelados")],
        [InlineKeyboardButton("🔙 Voltar ao menu", callback_data="menu_principal")],
    ])

    await navegar_para(
        update, context,
        "Área do Secretário",
        "📋 *Bem-vindo à Área do Secretário*\n\nO que deseja fazer?",
        teclado
    )
    await enviar_dica_contextual(update, context, "area_secretario_lojas")


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
            if obter_secretario_responsavel_evento(ev) == int(user_id)
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
            [_botao_cadastrar_evento("➕ Cadastrar evento")],
            [InlineKeyboardButton("🔙 Voltar", callback_data=_callback_voltar_area(nivel))],
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

    botoes.append([_botao_cadastrar_evento("➕ Cadastrar novo")])
    botoes.append([InlineKeyboardButton("🔙 Voltar", callback_data=_callback_voltar_area(nivel))])

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
    nivel = get_nivel(user_id)
    
    if not usuario_pode_gerenciar_evento(user_id, nivel, evento):
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
        [InlineKeyboardButton("📋 Copiar lista de confirmados", callback_data=f"copiar_lista|{_encode_cb(id_evento)}")],
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
    nivel = get_nivel(user_id)
    
    if not usuario_pode_gerenciar_evento(user_id, nivel, evento):
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
        if _confirmacao_com_agape(agape):
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

        tipo_agape = "Com ágape" if _confirmacao_com_agape(agape) else "Sem ágape"
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
    nivel = get_nivel(user_id)
    
    if not usuario_pode_gerenciar_evento(user_id, nivel, evento):
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
        if _confirmacao_com_agape(agape_texto):
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
    nivel = get_nivel(user_id)
    
    if not usuario_pode_gerenciar_evento(user_id, nivel, evento):
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
    nivel = get_nivel(user_id)
    
    if not usuario_pode_gerenciar_evento(user_id, nivel, evento):
        await _enviar_ou_editar_mensagem(
            context, user_id, TIPO_RESULTADO,
            "⛔ Permissão negada."
        )
        return

    evento["Status"] = "Cancelado"
    _registrar_ultima_edicao(evento, user_id, update.effective_user.full_name or "")
    sucesso = atualizar_evento(0, evento)
    
    if sucesso:
        evento["_aviso_resumo"] = "horário alterado ou evento cancelado"
        confirmacoes_antes = listar_confirmacoes_por_evento(id_evento) or []
        cancelar_todas_confirmacoes(id_evento)
        await sincronizar_resumo_evento_grupo(context, evento)
        await _notificar_confirmados_evento(
            context,
            evento,
            id_evento,
            motivo="cancelamento",
            editor_id=user_id,
            confirmacoes=confirmacoes_antes,
        )
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
        await update.message.reply_text(EDICAO_EVENTO_DADOS_NAO_ENCONTRADOS)
        return ConversationHandler.END

    campo_info = CAMPOS_EVENTO_EDITAVEIS.get(campo_id)
    evento = context.user_data.get("evento_gerenciado_dados")
    
    if not campo_info or not evento:
        await update.message.reply_text(EDICAO_EVENTO_CONTEXTO_PERDIDO)
        return ConversationHandler.END

    evento[campo_info["chave"]] = novo_valor
    _registrar_ultima_edicao(evento, update.effective_user.id, update.effective_user.full_name or "")

    id_evento = normalizar_id_evento(evento)
    sucesso = atualizar_evento(0, evento)

    if sucesso:
        evento["_aviso_resumo"] = "horário alterado ou evento cancelado"
        await sincronizar_resumo_evento_grupo(context, evento)
        await _notificar_confirmados_evento(
            context,
            evento,
            id_evento,
            motivo="edicao",
            editor_id=update.effective_user.id,
            campo_nome=campo_info["nome"],
            novo_valor=novo_valor,
        )
        await update.message.reply_text(
            EDICAO_EVENTO_SUCESSO_TMPL.format(campo_nome=campo_info['nome'])
        )
    else:
        await update.message.reply_text(EDICAO_EVENTO_FALHA)

    context.user_data.pop("editando_campo_evento", None)
    context.user_data.pop("evento_gerenciado_id", None)
    context.user_data.pop("evento_gerenciado_dados", None)
    
    return ConversationHandler.END


async def cancelar_edicao_evento(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancela o processo de edição."""
    if update.callback_query:
        await update.callback_query.answer()
        await _enviar_ou_editar_mensagem(
            context,
            update.effective_user.id,
            TIPO_RESULTADO,
            EDICAO_EVENTO_CANCELADA,
        )
    elif update.message:
        await update.message.reply_text(EDICAO_EVENTO_CANCELADA)

    context.user_data.pop("editando_campo_evento", None)
    context.user_data.pop("evento_gerenciado_id", None)
    context.user_data.pop("evento_gerenciado_dados", None)
    return ConversationHandler.END


# ============================================
# VER CONFIRMADOS DO SECRETÁRIO
# ============================================

async def ver_confirmados_secretario(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menu para visualizar confirmados de um evento específico do secretário."""
    query = update.callback_query
    user_id = update.effective_user.id
    nivel = get_nivel(user_id)

    # Lista eventos visíveis ao perfil.
    eventos = listar_eventos() or []
    if nivel == "3":
        eventos_secretario = [e for e in eventos if str(e.get("Status", "")).lower() in ("ativo", "")]
        botao_voltar = "area_admin"
    else:
        eventos_secretario = [
            e for e in eventos
            if obter_secretario_responsavel_evento(e) == int(user_id)
        ]
        botao_voltar = "area_secretario"
    
    if not eventos_secretario:
        if query:
            msg_vazio = "Nenhum evento encontrado." if nivel == "3" else "Você não tem eventos cadastrados."
            await query.answer(msg_vazio, show_alert=True)
        return
    
    if query:
        await query.answer()
    
    # Ordenar por data mais próxima
    eventos_secretario = _eventos_ordenados(eventos_secretario)
    
    # Criar botões para cada evento
    botoes = []
    for ev in eventos_secretario[:15]:  # Limitar a 15 eventos para não ficar muito longo
        nome_loja = str(ev.get("Nome da loja", "") or "").strip()
        data = str(ev.get("Data do evento", "") or "").strip()
        numero = str(ev.get("Número da loja", "") or "").strip()
        numero_fmt = f" {numero}" if numero else ""
        
        id_evento = normalizar_id_evento(ev)
        lbl = f"{nome_loja}{numero_fmt} - {data}"
        botoes.append([
            InlineKeyboardButton(lbl, callback_data=f"visualizar_confirmados|{_encode_cb(id_evento)}")
        ])
    
    botoes.append([InlineKeyboardButton("🔙 Voltar", callback_data=botao_voltar)])
    
    from src.bot import navegar_para
    await navegar_para(
        update, context,
        "Ver Confirmados",
        "👥 *Selecione um evento para visualizar os confirmados:*",
        InlineKeyboardMarkup(botoes)
    )


async def visualizar_confirmados(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Exibe lista detalhada de confirmados com informações de ágape."""
    query = update.callback_query
    _, id_evento_cod = query.data.split("|", 1)
    id_evento = _decode_cb(id_evento_cod)
    
    user_id = update.effective_user.id
    
    # Buscar evento
    eventos = listar_eventos() or []
    evento = next((ev for ev in eventos if normalizar_id_evento(ev) == id_evento), None)
    
    if not evento:
        await query.answer("Evento não encontrado.", show_alert=True)
        return
    
    # Verificar permissão
    nivel = get_nivel(user_id)
    
    if not usuario_pode_gerenciar_evento(user_id, nivel, evento):
        await query.answer("⛔ Permissão negada.", show_alert=True)
        return
    
    await query.answer()
    
    # Buscar confirmações
    confirmacoes = listar_confirmacoes_por_evento(id_evento) or []
    # DEBUG: log how many confirmations were found
    logger.debug(f"confirmacoes para evento {id_evento}: {len(confirmacoes)}")
    
    # eliminar duplicatas (por Telegram ID ou combinação de campos identificadores)
    vistos = set()
    unicos = []
    for c in confirmacoes:
        tid = str(c.get("Telegram ID") or c.get("telegram_id") or "").strip()
        if tid:
            chave = tid
        else:
            # fallback: use campos que identificam o membro, não a loja inteira
            nome = str(c.get("Nome", "")).strip()
            grau = str(c.get("Grau", "")).strip()
            cargo = str(c.get("Cargo", "")).strip()
            chave = nome + "|" + grau + "|" + cargo
        if chave and chave not in vistos:
            vistos.add(chave)
            unicos.append(c)
    confirmacoes = unicos
    logger.debug(f"confirmacoes únicas para evento {id_evento}: {len(confirmacoes)}")

    # Processar dados
    nome_loja = str(evento.get("Nome da loja", "") or "").strip()
    numero = str(evento.get("Número da loja", "") or "").strip()
    numero_fmt = f" {numero}" if numero else ""
    data = str(evento.get("Data do evento", "") or "").strip()
    hora = str(evento.get("Hora", "") or "").strip()
    
    total = len(confirmacoes)
    com_agape = 0
    sem_agape = 0
    linhas_detalhadas = []
    
    for c in confirmacoes:
        agape_raw = str(c.get("Ágape", "") or "").lower()
        
        # Contar ágape
        if _confirmacao_com_agape(agape_raw):
            com_agape += 1
            agape_flag = "Com ágape"
        else:
            sem_agape += 1
            agape_flag = "Sem ágape"
        
        # Montar informações do membro
        tid = c.get("Telegram ID") or c.get("telegram_id")
        membro = None
        if tid:
            try:
                membro = buscar_membro(int(float(tid)))
            except:
                pass
        
        if membro:
            nome = membro.get("Nome", "Desconhecido")
            grau = membro.get("Grau", "")
            loja = membro.get("Loja", "")
            numero_loja = membro.get("Número da loja", "")
            oriente = membro.get("Oriente", "")
            vm = "VM" if _eh_vm(membro) else ""
        else:
            nome = c.get("Nome", "Desconhecido")
            grau = c.get("Grau", "")
            loja = c.get("Loja", "")
            numero_loja = c.get("Número da loja", "")
            oriente = c.get("Oriente", "")
            vm = ""
        
        numero_fmt_membro = f" {numero_loja}" if numero_loja else ""
        # linha simples para ficha padrão
        linha = (
            f"{vm} | {grau} | {nome} | {loja}{numero_fmt_membro} - {oriente} | {agape_flag}"
        )
        linhas_detalhadas.append(linha)
    
    # Montar mensagem
    titulo = f"📊 *CONFIRMADOS - {nome_loja}{numero_fmt}*\n"
    header = f"📅 {data} | 🕕 {hora}\n\n"
    stats = (
        f"✅ Total: {total}\n"
        f"🍽 Com ágape: {com_agape}\n"
        f"❌ Sem ágape: {sem_agape}\n\n"
    )
    
    if linhas_detalhadas:
        corpo = "\n".join(linhas_detalhadas[:20])  # Limitar a 20 para não ficar muito grande
        if len(linhas_detalhadas) > 20:
            corpo += f"\n... e mais {len(linhas_detalhadas) - 20}"
    else:
        corpo = "_Nenhuma presença confirmada até o momento._"
    
    texto = titulo + header + stats + corpo
    
    teclado = InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Ver resumo", callback_data=f"resumo_evento|{_encode_cb(id_evento)}")],
        [InlineKeyboardButton("🔙 Voltar", callback_data="ver_confirmados_secretario")],
    ])
    
    from src.bot import navegar_para
    await navegar_para(
        update, context,
        "Confirmados do Evento",
        texto,
        teclado,
        limpar_conteudo=True
    )


# ============================================
# REFAZER EVENTOS CANCELADOS
# ============================================

async def listar_eventos_cancelados(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lista os eventos cancelados do secretário para possível reabertura."""
    user_id = update.effective_user.id
    nivel = get_nivel(user_id)

    eventos = listar_eventos() or []
    
    # Filtra eventos cancelados
    if nivel == "3":
        eventos_filtrados = [ev for ev in eventos if ev.get("Status", "").lower() == "cancelado"]
        titulo = "🔄 *Eventos Cancelados*"
    else:
        eventos_filtrados = [
            ev for ev in eventos 
            if obter_secretario_responsavel_evento(ev) == int(user_id)
            and ev.get("Status", "").lower() == "cancelado"
        ]
        titulo = "🔄 *Meus Eventos Cancelados*"

    if not eventos_filtrados:
        teclado = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Voltar", callback_data=_callback_voltar_area(nivel))],
        ])
        await navegar_para(
            update, context,
            "Área do Secretário > Eventos Cancelados",
            f"{titulo}\n\nNenhum evento cancelado encontrado.",
            teclado
        )
        return

    eventos_cancelados = list(reversed(_eventos_ordenados(eventos_filtrados)))  # Mais recentes primeiro
    botoes = []
    for ev in eventos_cancelados[:20]:
        id_evento = normalizar_id_evento(ev)
        line = _linha_botao_evento(ev)
        botoes.append([
            InlineKeyboardButton(
                f"🔄 {line}",
                callback_data=f"confirmar_refazer|{_encode_cb(id_evento)}"
            )
        ])

    botoes.append([InlineKeyboardButton("🔙 Voltar", callback_data=_callback_voltar_area(nivel))])

    await navegar_para(
        update, context,
        "Área do Secretário > Eventos Cancelados",
        f"{titulo}\n\nSelecione um evento para refazer:",
        InlineKeyboardMarkup(botoes)
    )


async def confirmar_refazer_evento(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mostra confirmação antes de refazer o evento."""
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
    nivel = get_nivel(user_id)
    
    if not usuario_pode_gerenciar_evento(user_id, nivel, evento):
        await _enviar_ou_editar_mensagem(
            context, user_id, TIPO_RESULTADO,
            "⛔ Permissão negada."
        )
        return

    # Verifica se está realmente cancelado
    if evento.get("Status", "").lower() != "cancelado":
        await _enviar_ou_editar_mensagem(
            context, user_id, TIPO_RESULTADO,
            "Este evento não está cancelado."
        )
        return

    teclado = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Sim, refazer evento", callback_data=f"executar_refazer|{_encode_cb(id_evento)}")],
        [InlineKeyboardButton("❌ Não, voltar", callback_data="listar_eventos_cancelados")],
    ])

    await navegar_para(
        update, context,
        "Área do Secretário > Refazer Evento",
        f"*Refazer evento*\n\nTem certeza que deseja reabrir este evento?\n\n"
        f"{_formatar_resumo_evento(evento)}\n\n"
        f"⚠️ As confirmações que foram removidas NÃO serão recuperadas.",
        teclado
    )


async def executar_refazer_evento(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Executa a reabertura do evento (refazer)."""
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
    nivel = get_nivel(user_id)
    
    if not usuario_pode_gerenciar_evento(user_id, nivel, evento):
        await _enviar_ou_editar_mensagem(
            context, user_id, TIPO_RESULTADO,
            "⛔ Permissão negada."
        )
        return

    # Reativa o evento
    evento["Status"] = "Ativo"
    _registrar_ultima_edicao(evento, user_id, update.effective_user.full_name or "")
    sucesso = atualizar_evento(0, evento)
    
    if sucesso:
        evento["_aviso_resumo"] = "horário alterado ou evento cancelado"
        await sincronizar_resumo_evento_grupo(context, evento)
        await _notificar_confirmados_evento(context, evento, id_evento, motivo="refazer", editor_id=user_id)
        await navegar_para(
            update, context,
            "Área do Secretário",
            "✅ *Evento reaberto com sucesso!*\n\n"
            f"O evento {evento.get('Nome da loja', '')} foi reativado e aparecerá em 'Meus eventos'.",
            InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Voltar", callback_data=_callback_voltar_area(nivel))
            ]])
        )
    else:
        await _enviar_ou_editar_mensagem(
            context, user_id, TIPO_RESULTADO,
            "❌ Erro ao refazer evento. Tente novamente mais tarde."
        )


# ============================================
# CONVERSATION HANDLER
# ============================================

editar_evento_secretario_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(editar_evento_inicio, pattern="^editar_evento_secretario$")],
    states={
        SELECIONAR_CAMPO: [CallbackQueryHandler(selecionar_campo_evento, pattern=r"^editar_campo_evento\|")],
        NOVO_VALOR: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_novo_valor_evento)],
    },
    fallbacks=[
        CommandHandler("cancelar", cancelar_edicao_evento),
        CallbackQueryHandler(cancelar_edicao_evento, pattern="^cancelar$"),
    ],
)
