# ============================================
# BODE ANDARILHO - GERENCIADOR DE MENUS E NAVEGAÇÃO
# ============================================
# 
# Este módulo coordena a experiência do Obreiro no bot.
# Implementa o sistema de "menu fixo" e mensagens de progresso:
# 
# 1. MENU PERMANENTE: Mantido no topo para acesso rápido às Colunas.
# 2. CONTEXTO (📍): Indica em qual oficina ou sala o Ir.·. se encontra.
# 3. RESULTADO: Exibe o conteúdo do trabalho ou a resposta da Grande Secretaria.
# 
# ============================================

from __future__ import annotations

import logging
import hashlib
import time
from typing import Dict, Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from src.sheets_supabase import buscar_membro
from src.permissoes import get_nivel

logger = logging.getLogger(__name__)

# ============================================
# CACHE E CONTROLE DE ESTADO
# ============================================
_last_check_times = {} 
estado_mensagens: Dict[int, dict] = {}

TIPO_MENU = "menu"
TIPO_CONTEXTO = "contexto"
TIPO_RESULTADO = "resultado"


# ============================================
# MENU PRINCIPAL (PAINEL DO OBREIRO)
# ============================================

def menu_principal_teclado(nivel: str) -> InlineKeyboardMarkup:
    """
    Gera o teclado do menu principal baseado no nível de acesso.
    """
    botoes = [
        [InlineKeyboardButton("📅 Ver Sessões Agendadas", callback_data="ver_eventos")],
        [InlineKeyboardButton("✅ Minhas Visitações", callback_data="minhas_confirmacoes")],
        [InlineKeyboardButton("👤 Meu Perfil / Dados", callback_data="meu_cadastro")],
        [InlineKeyboardButton("❓ Ajuda & Orientações", callback_data="menu_ajuda")],
    ]

    # Secretários (Nível 2) e Admins (Nível 3)
    if nivel in ("2", "3"):
        botoes.append([InlineKeyboardButton("📋 Painel do Secretário", callback_data="area_secretario")])

    # Apenas Administradores (Nível 3)
    if nivel == "3":
        botoes.append([InlineKeyboardButton("⚙️ Painel de Administração", callback_data="area_admin")])

    # Opção de limpeza para manter o templo virtual em ordem
    botoes.append([InlineKeyboardButton("🧹 Limpar Rastro de Mensagens", callback_data="limpar_historico")])

    return InlineKeyboardMarkup(botoes)


# ============================================
# UTILITÁRIOS DE COMUNICAÇÃO VISUAL
# ============================================

def _gerar_hash_conteudo(texto: str, teclado) -> str:
    teclado_str = str(teclado.to_dict()) if teclado else ""
    conteudo = f"{texto}|{teclado_str}"
    return hashlib.md5(conteudo.encode()).hexdigest()


async def _responder_callback_seguro(query, texto: Optional[str] = None):
    """Responde callback sem falhar quando a query já expirou no Telegram."""
    if not query:
        return
    try:
        if texto is None:
            await query.answer()
        else:
            await query.answer(texto)
    except BadRequest as e:
        msg = str(e).lower()
        if "query is too old" in msg or "query id is invalid" in msg:
            logger.debug("Callback expirado ignorado: %s", e)
            return
        logger.warning("Falha ao responder callback: %s", e)


async def _verificar_mensagem_existe(context, user_id: int, message_id: int) -> bool:
    now = time.time()
    if user_id in _last_check_times:
        if now - _last_check_times[user_id] < 30:
            return True
    
    try:
        await context.bot.get_chat(user_id)
        _last_check_times[user_id] = now
        return True
    except Exception:
        _last_check_times.pop(user_id, None)
        return False


async def _enviar_ou_editar_mensagem(
    context, 
    user_id: int, 
    tipo: str, 
    texto: str, 
    teclado = None,
    parse_mode: str = "Markdown",
    limpar_conteudo: bool = False
) -> bool:
    global estado_mensagens
    
    if user_id not in estado_mensagens:
        estado_mensagens[user_id] = {}
    
    hash_atual = _gerar_hash_conteudo(texto, teclado)
    dados_anteriores = estado_mensagens[user_id].get(tipo)
    
    if dados_anteriores and not limpar_conteudo:
        mensagem_existe = await _verificar_mensagem_existe(context, user_id, dados_anteriores["message_id"])
        
        if not mensagem_existe:
            estado_mensagens[user_id].pop(tipo, None)
        else:
            if dados_anteriores.get("content_hash") == hash_atual:
                return True
            
            try:
                await context.bot.edit_message_text(
                    chat_id=user_id,
                    message_id=dados_anteriores["message_id"],
                    text=texto,
                    parse_mode=parse_mode,
                    reply_markup=teclado
                )
                estado_mensagens[user_id][tipo]["content_hash"] = hash_atual
                return True
            except Exception as e:
                logger.warning(f"[{tipo}] Falha ao editar para Ir.·. {user_id}: {e}")
                estado_mensagens[user_id].pop(tipo, None)
    
    try:
        msg = await context.bot.send_message(
            chat_id=user_id,
            text=texto,
            parse_mode=parse_mode,
            reply_markup=teclado
        )
        
        if limpar_conteudo and tipo in estado_mensagens[user_id]:
            try:
                await context.bot.delete_message(
                    chat_id=user_id,
                    message_id=estado_mensagens[user_id][tipo]["message_id"]
                )
            except Exception:
                pass
        
        estado_mensagens[user_id][tipo] = {
            "message_id": msg.message_id,
            "content_hash": hash_atual
        }
        return True
    except Exception as e:
        logger.error(f"[{tipo}] Erro de envio para {user_id}: {e}")
        return False


async def _limpar_mensagens_anteriores(context, user_id: int, tipos: list = None):
    global estado_mensagens
    if user_id not in estado_mensagens:
        return
    
    if tipos is None:
        tipos = list(estado_mensagens[user_id].keys())
    
    for tipo in tipos:
        if tipo in estado_mensagens[user_id]:
            try:
                await context.bot.delete_message(
                    chat_id=user_id,
                    message_id=estado_mensagens[user_id][tipo]["message_id"]
                )
            except Exception:
                pass
            estado_mensagens[user_id].pop(tipo, None)


# ============================================
# FLUXO DE NAVEGAÇÃO ENTRE COLUNAS
# ============================================

async def criar_estrutura_inicial(context, user_id: int, membro: dict) -> bool:
    """Inicia a egrégora do bot enviando o menu permanente e contexto inicial."""
    nivel = get_nivel(user_id)
    
    # Menu Fixo (Portal de Entrada)
    texto_menu = f"🐐 *Bode Andarilho*\n\nSaudações, Ir.·. {membro.get('Nome', '')}!"
    sucesso = await _enviar_ou_editar_mensagem(
        context, user_id, TIPO_MENU, texto_menu, menu_principal_teclado(nivel)
    )
    
    if not sucesso:
        return False
    
    # Contexto Inicial
    await _enviar_ou_editar_mensagem(
        context, user_id, TIPO_CONTEXTO, "📍 *Átrio / Menu Principal*"
    )
    
    # Resultado Inicial
    await _enviar_ou_editar_mensagem(
        context, user_id, TIPO_RESULTADO,
        "A conversa seguirá por aqui. Escolha uma ação no painel."
    )
    
    return True


async def navegar_para(
    update: Update, 
    context: ContextTypes.DEFAULT_TYPE,
    caminho: str,
    conteudo: str,
    teclado = None,
    limpar_conteudo: bool = False
) -> bool:
    user_id = update.effective_user.id
    
    if caminho:
        await _enviar_ou_editar_mensagem(
            context, user_id, TIPO_CONTEXTO, f"📍 *{caminho}*"
        )
    
    return await _enviar_ou_editar_mensagem(
        context, user_id, TIPO_RESULTADO, conteudo, teclado, limpar_conteudo=limpar_conteudo
    )


async def voltar_ao_menu_principal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    membro = buscar_membro(user_id)
    
    if not membro:
        return
    
    await _enviar_ou_editar_mensagem(
        context, user_id, TIPO_CONTEXTO, "📍 *Átrio / Menu Principal*"
    )
    
    await _enviar_ou_editar_mensagem(
        context, user_id, TIPO_RESULTADO,
        "Painel restaurado. Como posso ser útil agora, Ir.·.?",
        limpar_conteudo=True
    )


async def limpar_historico(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Remove mensagens antigas para manter a limpeza e a ordem do chat."""
    query = update.callback_query
    await _responder_callback_seguro(query, "Limpando registros...")
    
    user_id = update.effective_user.id
    deletadas = 0
    
    try:
        msg_id = update.callback_query.message.message_id
        for i in range(1, 101):
            try:
                # Não apaga as mensagens do sistema de menu fixo (IDs guardados no estado)
                # O algoritmo tenta apagar as mensagens avulsas (comandos de texto, etc)
                await context.bot.delete_message(chat_id=user_id, message_id=msg_id - i)
                deletadas += 1
            except Exception:
                continue
    except Exception as e:
        logger.debug(f"Aviso de limpeza: {e}")
    
    await _enviar_ou_editar_mensagem(
        context, user_id, TIPO_RESULTADO,
        f"🧹 *Ordem Restaurada!* ({deletadas} mensagens removidas do histórico).",
        limpar_conteudo=True
    )


# ============================================
# COMANDO /START
# ============================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ponto de entrada: verifica se o Ir.·. está regular no sistema."""
    if update.effective_chat and update.effective_chat.type in ["group", "supergroup"]:
        await update.message.reply_text(
            "🔒 *Acesso Restrito!*\n\nPara interagir com o Bode Andarilho, "
            "por favor, procure-me em ambiente privado.\n\n"
            "Toque aqui: @BodeAndarilhoBot e envie /start"
        )
        return

    telegram_id = update.effective_user.id
    payload_start = ""
    if getattr(context, "args", None):
        payload_start = str(context.args[0] or "").strip().lower()

    veio_do_grupo = payload_start in {"cadastro", "grupo", "start"}
    membro = buscar_membro(telegram_id)

    if membro:
        await _limpar_mensagens_anteriores(context, telegram_id)
        await criar_estrutura_inicial(context, telegram_id, membro)
    else:
        from src.cadastro import cadastro_start as iniciar_cadastro
        if veio_do_grupo:
            context.user_data["origem_grupo_cadastro"] = True
        await iniciar_cadastro(update, context)


# ============================================
# GESTOR DE INTERAÇÕES (BOTAO_HANDLER)
# ============================================

async def botao_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return

    data = query.data or ""
    await _responder_callback_seguro(query)

    # Callbacks geridos por fluxos específicos (ConversationHandlers)
    if data in {"admin_promover", "admin_rebaixar", "editar_perfil", "admin_editar_membro"}:
        return
    if data.startswith("confirmar|") or data.startswith("confirmar_agape|"):
        return
    if data in {"iniciar_cadastro", "editar_cadastro", "continuar_cadastro"}:
        return
    if data == "editar_evento_secretario":
        return

    telegram_id = update.effective_user.id
    nivel = get_nivel(telegram_id)

    # Verificação de Permissões de Oficina
    if data == "area_secretario" and nivel not in ["2", "3"]:
        await _enviar_ou_editar_mensagem(
            context, telegram_id, TIPO_RESULTADO,
            "⛔ Este Oriente está restrito aos Secretários da Loja.",
            limpar_conteudo=True
        )
        return
    
    if data == "area_admin" and nivel != "3":
        await _enviar_ou_editar_mensagem(
            context, telegram_id, TIPO_RESULTADO,
            "⛔ Função exclusiva para os Administradores do sistema.",
            limpar_conteudo=True
        )
        return

    # Roteamento de Chamadas
    if data == "menu_principal":
        await voltar_ao_menu_principal(update, context)
    
    elif data == "limpar_historico":
        await limpar_historico(update, context)
    
    # --- Gestão de Eventos e Visitas ---
    elif data in ("ver_eventos", "voltar_eventos"):
        from src.eventos import mostrar_eventos
        await mostrar_eventos(update, context)
    elif data.startswith("data|"):
        from src.eventos import mostrar_eventos_por_data
        await mostrar_eventos_por_data(update, context)
    elif data.startswith("grau|"):
        from src.eventos import mostrar_eventos_por_grau
        await mostrar_eventos_por_grau(update, context)
    elif data.startswith("evento|"):
        from src.eventos import mostrar_detalhes_evento
        await mostrar_detalhes_evento(update, context)
    elif data.startswith("calendario|"):
        from src.eventos import mostrar_calendario
        await mostrar_calendario(update, context)
    
    # --- Painel do Visitante ---
    elif data == "minhas_confirmacoes":
        from src.eventos import minhas_confirmacoes
        await minhas_confirmacoes(update, context)
    elif data == "minhas_confirmacoes_futuro":
        from src.eventos import minhas_confirmacoes_futuro
        await minhas_confirmacoes_futuro(update, context)
    elif data == "minhas_confirmacoes_historico":
        from src.eventos import minhas_confirmacoes_historico
        await minhas_confirmacoes_historico(update, context)
    
    # --- Área Administrativa / Lojas ---
    elif data == "meu_cadastro":
        from src.perfil import mostrar_perfil
        await mostrar_perfil(update, context)
    elif data == "area_secretario":
        from src.eventos_secretario import exibir_menu_secretario
        await exibir_menu_secretario(update, context)
    elif data == "area_admin":
        from src.admin_acoes import exibir_menu_admin
        await exibir_menu_admin(update, context)
    elif data == "cadastrar_evento":
        from src.cadastro_evento import novo_evento_start
        await novo_evento_start(update, context)
    
    # Fallback
    else:
        await _enviar_ou_editar_mensagem(
            context, telegram_id, TIPO_RESULTADO,
            "Esta funcionalidade ainda está em fase de polimento.",
            limpar_conteudo=True
        )


__all__ = [
    'start',
    'botao_handler',
    'menu_principal_teclado',
    'criar_estrutura_inicial',
    'navegar_para',
    'voltar_ao_menu_principal',
    '_enviar_ou_editar_mensagem',
    'TIPO_MENU',
    'TIPO_CONTEXTO',
    'TIPO_RESULTADO',
]