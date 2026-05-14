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
    listar_confirmacoes_por_eventos,
    cancelar_todas_confirmacoes,
    atualizar_evento,
    obter_secretario_responsavel_evento,
    usuario_pode_gerenciar_evento,
)
from src.ritos import normalizar_rito
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


def _id_evento_legado(evento: dict) -> str:
    return f"{evento.get('Data do evento', '')} — {evento.get('Nome da loja', '')}"


def _ids_evento_aliases(id_evento: str, evento: dict) -> list[str]:
    ids = [str(id_evento or "").strip(), str(normalizar_id_evento(evento) or "").strip(), _id_evento_legado(evento)]
    out: list[str] = []
    for raw in ids:
        s = str(raw or "").strip()
        if not s or s.lower() == "nan":
            continue
        if s not in out:
            out.append(s)
    return out

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
    """Atualiza campos de auditoria de edição nos dados do evento."""
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
    confirmacoes = (
        confirmacoes
        if confirmacoes is not None
        else (listar_confirmacoes_por_eventos(_ids_evento_aliases(id_evento, evento)) or [])
    )
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
    return await _exibir_menu_secretario_seguro(update, context)

async def _legacy_exibir_menu_secretario(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        [InlineKeyboardButton("✅ Validar Novos Irmãos", callback_data="listar_membros_pendentes")],
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
    evento = next(
        (
            ev
            for ev in eventos
            if normalizar_id_evento(ev) == id_evento or _id_evento_legado(ev) == id_evento
        ),
        None,
    )

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
    evento = next(
        (
            ev
            for ev in eventos
            if normalizar_id_evento(ev) == id_evento or _id_evento_legado(ev) == id_evento
        ),
        None,
    )

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

    confirmacoes = listar_confirmacoes_por_eventos(_ids_evento_aliases(id_evento, evento)) or []
    
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
    evento = next(
        (
            ev
            for ev in eventos
            if normalizar_id_evento(ev) == id_evento or _id_evento_legado(ev) == id_evento
        ),
        None,
    )

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

    confirmacoes = listar_confirmacoes_por_eventos(_ids_evento_aliases(id_evento, evento)) or []
    
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
    evento = next(
        (
            ev
            for ev in eventos
            if normalizar_id_evento(ev) == id_evento or _id_evento_legado(ev) == id_evento
        ),
        None,
    )

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
    if query:
        await query.answer("Cancelando evento...")
    _, id_evento_cod = query.data.split("|", 1)
    id_evento = _decode_cb(id_evento_cod)

    eventos = listar_eventos() or []
    evento = next(
        (
            ev
            for ev in eventos
            if normalizar_id_evento(ev) == id_evento or _id_evento_legado(ev) == id_evento
        ),
        None,
    )

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
    evento["Cancelado em"] = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    evento["Cancelado por (Telegram ID)"] = str(user_id)
    evento["Cancelado por (Nome)"] = (update.effective_user.full_name or "").strip()
    _registrar_ultima_edicao(evento, user_id, update.effective_user.full_name or "")
    sucesso = atualizar_evento(0, evento)
    
    if sucesso:
        evento["_aviso_resumo"] = "horário alterado ou evento cancelado"
        ids_aliases = _ids_evento_aliases(id_evento, evento)
        confirmacoes_antes = listar_confirmacoes_por_eventos(ids_aliases) or []
        for eid in ids_aliases:
            cancelar_todas_confirmacoes(eid)
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

    if campo_id == "rito":
        novo_valor = normalizar_rito(novo_valor) or novo_valor

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
    evento = next(
        (
            ev
            for ev in eventos
            if normalizar_id_evento(ev) == id_evento or _id_evento_legado(ev) == id_evento
        ),
        None,
    )
    
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
    confirmacoes = listar_confirmacoes_por_eventos(_ids_evento_aliases(id_evento, evento)) or []
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
            # alternativa: use campos que identificam o membro, não a loja inteira
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
    evento = next(
        (
            ev
            for ev in eventos
            if normalizar_id_evento(ev) == id_evento or _id_evento_legado(ev) == id_evento
        ),
        None,
    )

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
    evento = next(
        (
            ev
            for ev in eventos
            if normalizar_id_evento(ev) == id_evento or _id_evento_legado(ev) == id_evento
        ),
        None,
    )

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


# ============================================
# CÂMARA DE REFLEXÃO - VALIDAÇÃO DE NOVOS IRMÃOS
# ============================================

async def listar_membros_pendentes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lista os cadastros com status Pendente filtrando por responsabilidade de oficina."""
    user_id = update.effective_user.id
    nivel = get_nivel(user_id)
    
    if nivel not in ["2", "3"]:
        await _enviar_ou_editar_mensagem(
            context, user_id, TIPO_RESULTADO,
            "⛔ Você não tem permissão para acessar esta área."
        )
        return

    from src.sheets_supabase import listar_membros, listar_lojas
    
    membros_brutos = listar_membros(include_inativos=True) or []
    # Normalização do status Pendente
    pendentes_geral = []
    for m in membros_brutos:
        st = str(m.get("Status") or m.get("status") or "").strip().lower()
        if st == "pendente":
            pendentes_geral.append(m)

    if not pendentes_geral:
        await navegar_para(
            update, context,
            "Validar Novos Irmãos",
            "🎉 Nenhum cadastro aguarda validação na Câmara de Reflexão neste momento.",
            InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Voltar", callback_data=_callback_voltar_area(nivel))]])
        )
        return

    # Filtro de escopo
    filtrados = []
    if nivel == "3":
        filtrados = pendentes_geral
    else:
        # Secretário: Buscar apenas os que pertencem à loja que ele administra
        lojas_admin = listar_lojas(user_id, include_todas=False) or []
        
        # Cria chaves de correspondência resilientes
        import unicodedata
        import re
        def _key(txt: Any) -> str:
            b = unicodedata.normalize("NFKD", str(txt or "").strip())
            b = "".join(ch for ch in b if not unicodedata.combining(ch))
            return re.sub(r"\s+", "", b).lower()

        chaves_lojas_sec = set()
        for l in lojas_admin:
            lid = _key(l.get("ID") or l.get("id"))
            if lid:
                chaves_lojas_sec.add(f"id:{lid}")
            nome = _key(l.get("Nome da Loja") or l.get("nome_loja"))
            num = _key(l.get("Número") or l.get("numero") or "0")
            if nome:
                chaves_lojas_sec.add(f"nn:{nome}:{num}")
                
        for m in pendentes_geral:
            mid = _key(m.get("ID da loja") or m.get("loja_id"))
            mnome = _key(m.get("Loja") or m.get("loja"))
            mnum = _key(m.get("Número da loja") or m.get("numero_loja") or "0")
            
            match = False
            if mid and f"id:{mid}" in chaves_lojas_sec:
                match = True
            elif mnome and f"nn:{mnome}:{mnum}" in chaves_lojas_sec:
                match = True
            
            if match:
                filtrados.append(m)

    if not filtrados:
        await navegar_para(
            update, context,
            "Validar Novos Irmãos",
            "📋 Não há cadastros pendentes de validação vinculados à(s) sua(s) oficina(s) no momento.",
            InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Voltar", callback_data=_callback_voltar_area(nivel))]])
        )
        return

    botoes = []
    for m in filtrados[:50]:  # Limite de segurança
        nome = m.get("Nome", "Novo Obreiro")
        loja_label = m.get("Loja", "Sem Loja")
        tid = m.get("Telegram ID")
        
        label = f"👤 {nome} ({loja_label})"
        if len(label) > 36:
            label = label[:33] + "..."
            
        botoes.append([InlineKeyboardButton(label, callback_data=f"detalhe_pendente|{tid}")])

    botoes.append([InlineKeyboardButton("🔙 Voltar", callback_data=_callback_voltar_area(nivel))])

    titulo_painel = "Administração > Pendentes" if nivel == "3" else "Validar Novos Irmãos"
    await navegar_para(
        update, context,
        titulo_painel,
        f"📋 *Cadastros Pendentes ({len(filtrados)})*\n\nSelecione um Irmão para analisar dados e ativar:",
        InlineKeyboardMarkup(botoes)
    )


async def detalhe_pendente(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Exibe visão detalhada de dados do obreiro pendente para decisão."""
    query = update.callback_query
    user_id = update.effective_user.id
    nivel = get_nivel(user_id)
    
    if nivel not in ["2", "3"]:
        await _enviar_ou_editar_mensagem(context, user_id, TIPO_RESULTADO, "⛔ Sem permissão.")
        return

    _, tid = query.data.split("|", 1)
    
    from src.sheets_supabase import buscar_membro
    membro = buscar_membro(int(float(tid)))
    
    if not membro:
        await query.answer("❌ Registro pendente não encontrado.")
        await listar_membros_pendentes(update, context)
        return

    nome = membro.get("Nome", "-")
    grau = membro.get("Grau", "-")
    cargo = membro.get("Cargo", "Nenhum")
    loja = membro.get("Loja", "-")
    numero = membro.get("Número da loja", "")
    potencia = membro.get("Potência", "-")
    oriente = membro.get("Oriente", "-")
    veneravel = membro.get("Venerável Mestre", "-")
    
    num_fmt = f" nº {numero}" if numero else ""

    texto = (
        f"👤 *Análise de Credenciais*\n\n"
        f"▪️ Nome: *{nome}*\n"
        f"▪️ Grau: *{grau}*\n"
        f"▪️ Cargo declarado: *{cargo or 'Nenhum'}*\n"
        f"▪️ Loja: *{loja}{num_fmt}*\n"
        f"▪️ Potência: *{potencia}*\n"
        f"▪️ Oriente: *{oriente}*\n"
        f"▪️ Venerável Mestre: *{veneravel}*\n\n"
        f"Deseja validar o acesso deste obreiro ao painel do Bode Andarilho?"
    )

    teclado = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Aprovar Registro", callback_data=f"aprovar_membro|{tid}"),
        ],
        [
            InlineKeyboardButton("❌ Recusar Registro", callback_data=f"confirmar_recusar_membro|{tid}"),
        ],
        [InlineKeyboardButton("🔙 Voltar à lista", callback_data="listar_membros_pendentes")]
    ])

    await navegar_para(
        update, context,
        "Validar > Detalhe",
        texto,
        teclado
    )


async def aprovar_membro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Altera o status para Ativo e envia notificação de boas vindas ao obreiro."""
    query = update.callback_query
    user_id = update.effective_user.id
    nivel = get_nivel(user_id)
    
    # REFINAMENTO DE SEGURANÇA: Verificação explícita do callback
    if nivel not in ["2", "3"]:
        await _enviar_ou_editar_mensagem(context, user_id, TIPO_RESULTADO, "⛔ Acesso negado.")
        return

    if query:
        await query.answer("Efetuando aprovação...")

    _, tid_str = query.data.split("|", 1)
    tid = int(float(tid_str))

    from src.sheets_supabase import atualizar_membro, buscar_membro, _cache_membros
    
    # Carrega dados antes de atualizar para notificação amigável
    membro = buscar_membro(tid)
    if not membro:
        await _enviar_ou_editar_mensagem(context, user_id, TIPO_RESULTADO, "❌ Obreiro não localizado no banco.")
        return

    # Atualiza
    sucesso = atualizar_membro(tid, {"Status": "Ativo"}, preservar_nivel=True)
    
    if sucesso:
        _cache_membros.pop(tid, None) # Invalida cache explicitamente

        # Envio de mensagem privada de liberação ao obreiro
        try:
            await context.bot.send_message(
                chat_id=tid,
                text=(
                    "✨ *Acesso Concedido!*\n\n"
                    "Saudações, Ir.·.!\n"
                    "Seu cadastro no Bode Andarilho foi validado e aprovado pela secretaria de sua oficina.\n\n"
                    "Agora seu acesso completo ao Painel do Obreiro está liberado!\n\n"
                    "Use o comando /start para acessar os recursos e confirmar presenças."
                ),
                parse_mode="Markdown"
            )
        except Exception as e_notif:
            logger.warning("Membro %s aprovado, mas notificação privada falhou: %s", tid, e_notif)

        await navegar_para(
            update, context,
            "Validar > Sucesso",
            f"✅ O cadastro de *{membro.get('Nome', 'Novo Obreiro')}* foi ativado com sucesso!\n\n"
            f"O Irmão recebeu uma notificação no privado.",
            InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Voltar", callback_data="listar_membros_pendentes")]])
        )
    else:
        await _enviar_ou_editar_mensagem(
            context, user_id, TIPO_RESULTADO,
            "❌ Falha técnica ao atualizar banco de dados. Tente novamente."
        )


async def confirmar_recusar_membro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Tela de confirmação destrutiva para recusar o cadastro."""
    query = update.callback_query
    user_id = update.effective_user.id
    nivel = get_nivel(user_id)
    
    if nivel not in ["2", "3"]:
        await _enviar_ou_editar_mensagem(context, user_id, TIPO_RESULTADO, "⛔ Acesso negado.")
        return

    _, tid = query.data.split("|", 1)
    
    from src.sheets_supabase import buscar_membro
    membro = buscar_membro(int(float(tid)))
    nome = membro.get("Nome", "este obreiro") if membro else "este obreiro"

    texto = (
        f"⚠️ *Confirmar Recusa de Cadastro*\n\n"
        f"Tem certeza de que deseja recusar o registro de *{nome}*?\n\n"
        f"Esta ação enviará uma notificação avisando-o sobre a divergência e EXCLUIRÁ os dados provisórios dele para que ele possa refazer o processo."
    )

    teclado = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("❌ Sim, recusar e excluir", callback_data=f"recusar_membro|{tid}"),
        ],
        [
            InlineKeyboardButton("🔙 Voltar", callback_data=f"detalhe_pendente|{tid}")
        ]
    ])

    await navegar_para(
        update, context,
        "Validar > Confirmação",
        texto,
        teclado
    )


async def recusar_membro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Notifica a recusa ao obreiro e executa o hard delete do registro pendente."""
    query = update.callback_query
    user_id = update.effective_user.id
    nivel = get_nivel(user_id)
    
    # REFINAMENTO DE SEGURANÇA: Verificação explícita do callback
    if nivel not in ["2", "3"]:
        await _enviar_ou_editar_mensagem(context, user_id, TIPO_RESULTADO, "⛔ Acesso negado.")
        return

    if query:
        await query.answer("Processando recusa...")

    _, tid_str = query.data.split("|", 1)
    tid = int(float(tid_str))

    from src.sheets_supabase import excluir_membro, buscar_membro
    
    membro = buscar_membro(tid)
    nome_membro = membro.get("Nome", "Novo Obreiro") if membro else "Obreiro"

    # REFINAMENTO DE SEGURANÇA: Enviar notificação ANTES de apagar dados
    try:
        await context.bot.send_message(
            chat_id=tid,
            text=(
                "⛔ *Registro não Validado*\n\n"
                "Ir.·., saudações!\n"
                "O Secretário da Loja revisou sua solicitação de cadastro e não pôde validá-la.\n"
                "Isto ocorre geralmente por erros de grafia no Nome, Loja, Número ou Potência.\n\n"
                "Seus dados temporários foram limpos. Sinta-se à vontade para usar o comando /start e preencher um novo formulário de acesso."
            ),
            parse_mode="Markdown"
        )
    except Exception as e_notif:
        logger.warning("Membro %s recusado, falha ao enviar aviso prévio: %s", tid, e_notif)

    # Realiza a exclusão física
    ok = excluir_membro(tid)
    
    if ok:
        await navegar_para(
            update, context,
            "Validar > Recusado",
            f"🚫 Registro de *{nome_membro}* recusado e excluído com sucesso.\n\n"
            f"O usuário foi devidamente notificado e o registro limpo.",
            InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Voltar", callback_data="listar_membros_pendentes")]])
        )
    else:
        await _enviar_ou_editar_mensagem(
            context, user_id, TIPO_RESULTADO,
            "❌ Ocorreu uma falha ao tentar apagar o registro do banco. Contate o suporte."
        )


# ==========================================================
# 10. MENU DO SECRETÁRIO SEGURO E TRAVA DE GESTÃO
# ==========================================================

async def _exibir_menu_secretario_seguro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Nova implementação segura do menu principal com trava de configuração,
    vouchers dinâmicos e ferramentas de bastão.
    """
    user_id = update.effective_user.id
    nivel = get_nivel(user_id)
    
    if nivel not in ["2", "3"]:
        await _enviar_ou_editar_mensagem(
            context, user_id, TIPO_RESULTADO,
            "⛔ Você não tem permissão para acessar esta área."
        )
        return

    # TRAVA DE SECRETÁRIO SEM OFICINA (Apenas para Nível 2)
    loja_vinculada = None
    if nivel == "2":
        from src.sheets_supabase import get_loja_por_secretario
        loja_vinculada = get_loja_por_secretario(user_id)
        
        if not loja_vinculada:
            texto_trava = (
                "⚠️ *OFICINA NÃO CONFIGURADA*\n\n"
                "Prezado Ir.·., identificamos que seu cadastro possui perfil de Secretário (Nível 2), "
                "mas ainda não há nenhuma Loja vinculada à sua gestão administrativa.\n\n"
                "Para liberar o acesso às ferramentas de gestão (Eventos, Vouchers e Validações), "
                "por favor realize o registro da sua Oficina tocando no botão abaixo:"
            )
            teclado_trava = InlineKeyboardMarkup([
                [InlineKeyboardButton("🏛️ Cadastrar Minha Loja", callback_data="cadastrar_loja_inicio")],
                [InlineKeyboardButton("🔙 Voltar ao menu", callback_data="menu_principal")],
            ])
            await navegar_para(update, context, "Área do Secretário", texto_trava, teclado_trava)
            return

    # Se for Admin ou passar da trava, exibe o menu completo!
    voucher_str = "🎫 Gerar Voucher Coletivo"
    if not loja_vinculada and nivel == "3":
        from src.sheets_supabase import get_loja_por_secretario
        loja_vinculada = get_loja_por_secretario(user_id)

    if loja_vinculada:
        from src.sheets_supabase import get_voucher_ativo_por_loja
        lid = loja_vinculada.get("ID da loja") or loja_vinculada.get("id")
        try:
            v_ativo = get_voucher_ativo_por_loja(lid)
            if v_ativo:
                usos = v_ativo.get("usos_atuais") or 0
                limite = v_ativo.get("limite_usos") or 100
                voucher_str = f"🎫 Voucher: {usos}/{limite} Usos"
        except Exception:
            pass

    # Construção do Teclado
    opcoes = [
        [_botao_cadastrar_evento()],
        [InlineKeyboardButton("✅ Validar Novos Irmãos", callback_data="listar_membros_pendentes")],
        [InlineKeyboardButton(voucher_str, callback_data="gerar_voucher_inicio")],
    ]
    
    if loja_vinculada or nivel == "3":
        opcoes.append([InlineKeyboardButton("🤝 Passagem de Bastão", callback_data="bastao_listar")])
        
    opcoes.extend([
        [InlineKeyboardButton("📋 Meus eventos", callback_data="meus_eventos")],
        [InlineKeyboardButton("👥 Ver confirmados por evento", callback_data="ver_confirmados_secretario")],
        [InlineKeyboardButton("👥 Membros da Minha Oficina", callback_data="admin_editar_membro")],
        [InlineKeyboardButton("🏛️ Minhas lojas", callback_data="menu_lojas")],
        [InlineKeyboardButton("🔔 Configurar notificações", callback_data="menu_notificacoes")],
        [InlineKeyboardButton("🏆 Meus Marcos de Secretário", callback_data="mostrar_marcos_secretario")],
        [InlineKeyboardButton("🔄 Ver eventos cancelados", callback_data="listar_eventos_cancelados")],
        [InlineKeyboardButton("🔙 Voltar ao menu", callback_data="menu_principal")],
    ])
    
    teclado = InlineKeyboardMarkup(opcoes)

    await navegar_para(
        update, context,
        "Área do Secretário",
        "📋 *Bem-vindo à Área do Secretário*\n\nO que deseja fazer?",
        teclado
    )
    await enviar_dica_contextual(update, context, "area_secretario_lojas")


# ==========================================================
# 11. MÓDULO DE VOUCHERS COLETIVOS (DEEP LINKING)
# ==========================================================

VOUCHER_LIMITE = 1

async def gerar_voucher_inicio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Exibe opções de limite para o novo voucher coletivo."""
    query = update.callback_query
    if query:
        await query.answer()
        
    user_id = update.effective_user.id
    nivel = get_nivel(user_id)
    if nivel not in ["2", "3"]:
        return ConversationHandler.END
        
    from src.sheets_supabase import get_loja_por_secretario, get_voucher_ativo_por_loja
    loja = get_loja_por_secretario(user_id)
    
    if not loja:
        await _enviar_ou_editar_mensagem(
            context, user_id, TIPO_RESULTADO,
            "⚠️ Esta funcionalidade exige uma Loja vinculada ao seu usuário."
        )
        return ConversationHandler.END

    lid = loja.get("ID da loja") or loja.get("id")
    v_ativo = get_voucher_ativo_por_loja(lid)
    
    texto_ativo = ""
    if v_ativo:
        token_at = v_ativo.get("token")
        usos = v_ativo.get("usos_atuais") or 0
        lim = v_ativo.get("limite_usos") or 100
        link = f"https://t.me/{context.bot.username}?start={token_at}"
        texto_ativo = (
            f"🎫 *Voucher Ativo Atual:*\n"
            f"📊 Usos: `{usos}/{lim}`\n"
            f"🔗 Link: `{link}`\n\n"
            f"⚠️ _Atenção: Gerar um novo voucher irá invalidar o link ativo acima._\n\n"
        )

    texto = (
        f"🎫 *GERAR VOUCHER COLETIVO*\n\n"
        f"{texto_ativo}"
        f"Escolha o limite máximo de utilizações para o novo link de convite:"
    )
    
    teclado = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("👥 50 Usos", callback_data="c_voucher|50"),
            InlineKeyboardButton("👥 100 Usos", callback_data="c_voucher|100"),
        ],
        [
            InlineKeyboardButton("👥 250 Usos", callback_data="c_voucher|250"),
            InlineKeyboardButton("⌨ Digitar limite...", callback_data="c_voucher_digitar"),
        ],
        [InlineKeyboardButton("🔙 Voltar ao painel", callback_data="menu_secretario")]
    ])
    
    await navegar_para(update, context, "Gerar Voucher", texto, teclado)
    return VOUCHER_LIMITE


async def gerar_voucher_processar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cria o voucher com base no clique do botão pré-definido."""
    query = update.callback_query
    await query.answer()
    
    data = query.data or ""
    
    if data == "c_voucher_digitar":
        await navegar_para(
            update, context,
            "Gerar Voucher",
            "⌨ *DIGITE O LIMITE*\n\nPor favor, envie uma mensagem apenas com o número desejado (ex: `15`):",
            InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancelar", callback_data="gerar_voucher_inicio")]])
        )
        return VOUCHER_LIMITE

    try:
        _, lim_str = data.split("|", 1)
        limite = int(lim_str)
    except Exception:
        limite = 100
        
    return await _finalizar_criacao_voucher(update, context, limite)


async def gerar_voucher_digitado(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Recebe e processa o limite numérico enviado via texto."""
    texto = (update.message.text or "").strip()
    user_id = update.effective_user.id
    
    try:
        limite = int(texto)
        if limite <= 0 or limite > 1000:
            raise ValueError()
    except Exception:
        await _enviar_ou_editar_mensagem(
            context, user_id, TIPO_RESULTADO,
            "⚠️ Por favor, insira um número inteiro válido entre 1 e 1000.",
            InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancelar", callback_data="gerar_voucher_inicio")]])
        )
        return VOUCHER_LIMITE
        
    return await _finalizar_criacao_voucher(update, context, limite)


async def _finalizar_criacao_voucher(update: Update, context: ContextTypes.DEFAULT_TYPE, limite: int) -> int:
    """Invoca a persistência de criação e exibe o link pronto ao Secretário."""
    user_id = update.effective_user.id
    
    from src.sheets_supabase import get_loja_por_secretario, criar_voucher
    loja = get_loja_por_secretario(user_id)
    if not loja:
        await _enviar_ou_editar_mensagem(context, user_id, TIPO_RESULTADO, "❌ Oficina não vinculada.")
        return ConversationHandler.END
        
    lid = loja.get("ID da loja") or loja.get("id")
    token = criar_voucher(lid, user_id, limite)
    
    if not token:
        await _enviar_ou_editar_mensagem(context, user_id, TIPO_RESULTADO, "❌ Falha ao gerar registro no banco de dados.")
        return ConversationHandler.END
        
    link_completo = f"https://t.me/{context.bot.username}?start={token}"
    nome_loja = loja.get("Nome da Loja") or loja.get("nome") or "Sua Loja"
    
    texto_sucesso = (
        f"✅ *VOUCHER COLETIVO CRIADO!*\n\n"
        f"O link abaixo está ativo e pré-configurado para a oficina *{nome_loja}*.\n\n"
        f"📊 *Limite de usos:* `{limite} cadastros`.\n\n"
        f"🔗 *Link de Convite:* (Toque para copiar)\n"
        f"`{link_completo}`\n\n"
        f"💡 *Como funciona:* Ao clicar no link, o novo Irmão iniciará o cadastro com todos os dados de Loja/Oriente pré-preenchidos, "
        f"sendo ativado *imediatamente* sem precisar aguardar aprovação na Câmara de Reflexão."
    )
    
    teclado = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Voltar à Área do Secretário", callback_data="menu_secretario")]
    ])
    
    await navegar_para(update, context, "Voucher Ativo", texto_sucesso, teclado)
    return ConversationHandler.END


# ==========================================================
# 12. MÓDULO PASSAGEM DE BASTÃO (TRANSMISSÃO DE OFÍCIO)
# ==========================================================

async def bastao_listar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lista os obreiros ativos da mesma Loja para transferência."""
    query = update.callback_query
    if query:
        await query.answer()
        
    user_id = update.effective_user.id
    nivel = get_nivel(user_id)
    if nivel not in ["2", "3"]:
        return

    from src.sheets_supabase import get_loja_por_secretario, listar_membros_por_loja
    loja = get_loja_por_secretario(user_id)
    if not loja:
        await _enviar_ou_editar_mensagem(context, user_id, TIPO_RESULTADO, "⚠️ Esta funcionalidade exige uma Loja vinculada.")
        return

    lid = loja.get("ID da loja") or loja.get("id")
    nome_loja = loja.get("Nome da Loja") or loja.get("nome")
    numero_loja = loja.get("Número") or loja.get("numero") or "0"
    
    membros = listar_membros_por_loja(loja_id=lid, nome_loja=nome_loja, numero_loja=numero_loja) or []
    membros_elegiveis = [m for m in membros if str(m.get("Telegram ID") or m.get("telegram_id")) != str(user_id)]

    texto = (
        "🤝 *PASSAGEM DE BASTÃO*\n\n"
        "Esta ferramenta transfere sua autoridade de Secretário da Loja para outro Ir.·. cadastrado.\n"
        "🚨 *Atenção:* Após concluir a transmissão, seu acesso será rebaixado para Nível 1 e o sucessor será promovido a Nível 2.\n\n"
        "Selecione o sucessor abaixo:"
    )
    
    if not membros_elegiveis:
        texto = (
            "🤝 *PASSAGEM DE BASTÃO*\n\n"
            "❌ Não foram encontrados outros obreiros *Ativos* vinculados a esta Loja.\n\n"
            "Peça para o futuro secretário cadastrar-se e ser validado antes de transmitir o bastão."
        )
        await navegar_para(
            update, context, "Transmitir Ofício", texto,
            InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Voltar", callback_data="menu_secretario")]])
        )
        return

    botoes = []
    for m in membros_elegiveis:
        m_id = m.get("Telegram ID") or m.get("telegram_id")
        m_nome = m.get("Nome") or m.get("nome") or "Obreiro"
        grau = m.get("Grau") or m.get("grau") or "M.·."
        botoes.append([InlineKeyboardButton(f"🔺 {m_nome} ({grau})", callback_data=f"bastao_conf|{m_id}")])
        
    botoes.append([InlineKeyboardButton("🔙 Voltar", callback_data="menu_secretario")])
    
    await navegar_para(update, context, "Transmitir Ofício", texto, InlineKeyboardMarkup(botoes))


async def bastao_confirmar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Pede a confirmação dupla para a passagem de bastão."""
    query = update.callback_query
    await query.answer()
    
    data = query.data or ""
    
    try:
        _, sucessor_id = data.split("|", 1)
    except Exception:
        await bastao_listar(update, context)
        return
        
    from src.sheets_supabase import buscar_membro
    sucessor = buscar_membro(sucessor_id)
    if not sucessor:
        await query.answer("Obreiro não localizado.", show_alert=True)
        return
        
    nome_suc = sucessor.get("Nome") or sucessor.get("nome") or "Novo Secretário"
    
    texto = (
        "🚨 *CONFIRMAÇÃO DUPLA*\n\n"
        f"Tem certeza absoluta que deseja transferir todos os seus poderes administrativos de Secretário para o Ir.·. *{nome_suc}*?\n\n"
        "1. Ele receberá plenos acessos de Nível 2 e será o dono desta Loja no sistema.\n"
        "2. Seu cadastro perderá acesso a esta Área do Secretário imediatamente após o clique."
    )
    
    teclado = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔥 SIM, TRANSMITIR BASTÃO", callback_data=f"bastao_executar|{sucessor_id}")],
        [InlineKeyboardButton("❌ Cancelar", callback_data="bastao_listar")]
    ])
    
    await navegar_para(update, context, "Confirmar Transmissão", texto, teclado)


async def bastao_executar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Executa a transação de banco de dados e avisa as duas partes."""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    data = query.data or ""
    
    try:
        _, sucessor_id = data.split("|", 1)
    except Exception:
        return

    from src.sheets_supabase import get_loja_por_secretario, buscar_membro, transferir_secretaria
    loja = get_loja_por_secretario(user_id)
    sucessor = buscar_membro(sucessor_id)
    
    if not loja or not sucessor:
        await _enviar_ou_editar_mensagem(context, user_id, TIPO_RESULTADO, "❌ Erro de vinculação. Operação cancelada.")
        return
        
    lid = loja.get("ID da loja") or loja.get("id")
    nome_loja = loja.get("Nome da Loja") or loja.get("nome") or "Loja"
    nome_suc = sucessor.get("Nome") or sucessor.get("nome") or "Obreiro"
    
    sucesso = transferir_secretaria(id_antigo=user_id, id_novo=sucessor_id, loja_id=lid)
    
    if not sucesso:
        await _enviar_ou_editar_mensagem(context, user_id, TIPO_RESULTADO, "❌ Falha crítica na transação. Tente novamente.")
        return
        
    # Hook Conquistas: Guardião da Chave Passada
    try:
        from src.conquistas import checar_e_conceder
        import asyncio
        asyncio.create_task(checar_e_conceder(user_id, "guardiao_chave", context.bot))
    except Exception:
        pass

    texto_ant = (
        "🤝 *BASTÃO TRANSMITIDO COM SUCESSO*\n\n"
        f"Agradecemos imensamente por seus valiosos serviços na administração da Oficina *{nome_loja}*.\n\n"
        f"O Ir.·. *{nome_suc}* assumiu a zeladoria no ambiente digital e seu acesso foi rebaixado ao perfil de Obreiro.\n\n"
        "Que o G.·.A.·.D.·.U.·. guie seus passos!"
    )
    await navegar_para(
        update, context, "Posse Transmitida", texto_ant,
        InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu Principal", callback_data="menu_principal")]])
    )
    
    try:
        texto_suc = (
            "🎉 *POSSE ADMINISTRATIVA CONCEDIDA*\n\n"
            f"Ir.·., você foi nomeado o novo Secretário responsável pela oficina *{nome_loja}* no bot!\n\n"
            "Seus privilégios de Nível 2 foram ativados e a Área do Secretário está liberada em seu painel principal.\n\n"
            "Desejamos um profícuo trabalho em sua nova jornada administrativa!"
        )
        teclado_suc = InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 Ir para Área do Secretário", callback_data="menu_secretario")],
            [InlineKeyboardButton("💡 Ajuda: Gerar Primeiro Voucher", callback_data="ajuda_voucher_boasvindas")],
        ])
        await context.bot.send_message(
            chat_id=int(float(sucessor_id)),
            text=texto_suc,
            reply_markup=teclado_suc,
            parse_mode="Markdown"
        )
    except Exception as ex:
        logger.warning("Falha ao notificar o sucessor %s privado: %s", sucessor_id, ex)


async def ajuda_voucher_boasvindas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Popup explicando o que é um voucher para o novo secretário."""
    query = update.callback_query
    await query.answer()
    
    texto = (
        "💡 *AJUDA RÁPIDA: VOUCHER COLETIVO*\n\n"
        "O *Voucher Coletivo* é a forma mais segura e rápida de trazer Irmãos da sua Loja para o bot.\n\n"
        "1️⃣ Acesse a *Área do Secretário > Gerar Voucher*.\n"
        "2️⃣ Escolha a quantidade máxima de utilizações.\n"
        "3️⃣ O bot gerará um link único exclusivo da sua oficina.\n"
        "4️⃣ Copie o link e envie no grupo de WhatsApp/Telegram da sua Loja.\n\n"
        "Ao clicar no link, o Irmão preenche apenas os dados pessoais e é *ATIVADO IMEDIATAMENTE*, "
        "sem precisar que você aprove cada cadastro individualmente!"
    )
    
    await navegar_para(
        update, context, "Ajuda Voucher", texto,
        InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Voltar à Área do Secretário", callback_data="menu_secretario")]])
    )


# ==========================================================
# 13. REGISTRO DE CONVERSATION HANDLER
# ==========================================================

voucher_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(gerar_voucher_inicio, pattern="^gerar_voucher_inicio$")],
    states={
        VOUCHER_LIMITE: [
            CallbackQueryHandler(gerar_voucher_processar, pattern=r"^c_voucher\||^c_voucher_digitar$"),
            MessageHandler(filters.TEXT & ~filters.COMMAND, gerar_voucher_digitado),
        ],
    },
    fallbacks=[
        CallbackQueryHandler(gerar_voucher_inicio, pattern="^gerar_voucher_inicio$"),
        CallbackQueryHandler(exibir_menu_secretario, pattern="^menu_secretario$"),
    ],
)
