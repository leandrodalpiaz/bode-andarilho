# ============================================
# BODE ANDARILHO - GERENCIADOR DE MENUS E NAVEGAÇÃO
# ============================================
# 
# Este módulo coordena a experiência do Obreiro no bot.
# A navegação privada foi simplificada para um painel ativo único:
# 
# 1. UM PAINEL ATIVO: A tela corrente é sempre editada no lugar quando possível.
# 2. NAVEGAÇÃO GLOBAL: As ações principais permanecem acessíveis por botões e atalhos.
# 3. CONTEXTO VISÍVEL: Cada tela inclui um caminho curto e ações do contexto atual.
# 
# ============================================

from __future__ import annotations

import hashlib
import logging
import os
import re
import unicodedata
from typing import Dict, Optional, Set

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from src.messages import APENAS_ADMIN, APENAS_SECRETARIO
from src.sheets_supabase import buscar_membro, membro_esta_ativo
from src.permissoes import get_nivel

# ID do grupo principal lido em tempo de execução (variável definida no main e aqui como alternativa de ambiente)
_GRUPO_TELEGRAM_ID_STR = os.getenv("GRUPO_PRINCIPAL_ID", "")
_GRUPO_TELEGRAM_ID: Optional[int] = (
    int(_GRUPO_TELEGRAM_ID_STR) if _GRUPO_TELEGRAM_ID_STR.lstrip("-").isdigit() else None
)


async def _verificar_membro_no_grupo(context, user_id: int) -> bool:
    """
    Verifica via getChatMember se o usuário ainda é membro ativo do grupo configurado.
    Retorna True se:
      - GRUPO_TELEGRAM_ID não estiver configurado (verificação desativada).
      - O status retornado pelo Telegram for member/administrator/creator.
    Retorna False se o usuário saiu (left) ou foi banido (kicked).
    """
    if not _GRUPO_TELEGRAM_ID:
        return True  # Verificação desativada enquanto a variável não estiver configurada
    try:
        member = await context.bot.get_chat_member(_GRUPO_TELEGRAM_ID, user_id)
        return member.status in ("member", "administrator", "creator")
    except Exception as e:
        logger.warning("getChatMember falhou para user_id=%s: %s", user_id, e)
        return True  # Em caso de erro de API, não bloqueia o usuário por precaução


estado_mensagens: Dict[int, dict] = {}

TIPO_MENU = "menu"
TIPO_CONTEXTO = "contexto"
TIPO_RESULTADO = "resultado"

ATALHOS_TEXTO_PRIVADO = {
    "menu": "menu_principal",
    "painel": "menu_principal",
    "bode": "menu_principal",
    "inicio": "menu_principal",
    "início": "menu_principal",
    "menu principal": "menu_principal",
    "abrir menu": "menu_principal",
    "voltar menu": "menu_principal",
    "sessoes": "ver_eventos",
    "sessões": "ver_eventos",
    "ver sessoes": "ver_eventos",
    "ver sessões": "ver_eventos",
    "agenda": "ver_eventos",
    "minhas presencas": "minhas_confirmacoes",
    "minhas presenças": "minhas_confirmacoes",
    "presencas": "minhas_confirmacoes",
    "presenças": "minhas_confirmacoes",
    "meu perfil": "meu_cadastro",
    "perfil": "meu_cadastro",
    "cadastro": "meu_cadastro",
    "meus lembretes": "menu_lembretes",
    "lembretes": "menu_lembretes",
    "assistente ia": "abrir_assistente_ia",
    "assistente": "abrir_assistente_ia",
    "ia": "abrir_assistente_ia",
    "ajuda": "menu_ajuda",
    "central de ajuda": "menu_ajuda",
    "organizar conversa": "limpar_historico",
    "limpar conversa": "limpar_historico",
}


# ============================================
# MENU PRINCIPAL (PAINEL DO OBREIRO)
# ============================================

def menu_principal_teclado(nivel: str) -> InlineKeyboardMarkup:
    """
    Gera o teclado do menu principal baseado no nível de acesso.
    """
    botoes = [
        [
            InlineKeyboardButton("📅 Sessões", callback_data="ver_eventos"),
            InlineKeyboardButton("✅ Presenças", callback_data="minhas_confirmacoes"),
        ],
        [
            InlineKeyboardButton("👤 Perfil", callback_data="meu_cadastro"),
            InlineKeyboardButton("❓ Ajuda", callback_data="menu_ajuda"),
        ],
        [
            InlineKeyboardButton("🔔 Lembretes", callback_data="menu_lembretes"),
            InlineKeyboardButton("🤖 Assistente IA", callback_data="abrir_assistente_ia"),
        ],
    ]

    # Secretários (Nível 2) e Admins (Nível 3)
    if nivel in ("2", "3"):
        botoes.append([InlineKeyboardButton("📋 Área do Secretário", callback_data="area_secretario")])

    # Apenas Administradores (Nível 3)
    if nivel == "3":
        botoes.append([InlineKeyboardButton("⚙️ Administração", callback_data="area_admin")])

    botoes.append([InlineKeyboardButton("🧹 Organizar conversa", callback_data="limpar_historico")])

    return InlineKeyboardMarkup(botoes)


def _callbacks_inline(teclado: Optional[InlineKeyboardMarkup]) -> Set[str]:
    callbacks: Set[str] = set()
    if not isinstance(teclado, InlineKeyboardMarkup):
        return callbacks
    for linha in teclado.inline_keyboard:
        for botao in linha:
            callback_data = getattr(botao, "callback_data", None)
            if callback_data:
                callbacks.add(callback_data)
    return callbacks


def _teclado_com_inicio(teclado: Optional[InlineKeyboardMarkup], incluir_rodape_global: bool) -> Optional[InlineKeyboardMarkup]:
    if not incluir_rodape_global:
        return teclado

    if teclado is None:
        return InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Início", callback_data="menu_principal")]])

    if not isinstance(teclado, InlineKeyboardMarkup):
        return teclado

    callbacks = _callbacks_inline(teclado)
    if "menu_principal" in callbacks:
        return teclado

    linhas = [list(linha) for linha in teclado.inline_keyboard]
    linhas.append([InlineKeyboardButton("🏠 Início", callback_data="menu_principal")])
    return InlineKeyboardMarkup(linhas)


def _normalizar_texto_atalho(texto: str) -> str:
    base = unicodedata.normalize("NFKD", str(texto or ""))
    base = "".join(ch for ch in base if not unicodedata.combining(ch))
    base = re.sub(r"\s+", " ", base).strip().lower()
    return base


def _montar_tela_privada(caminho: str, conteudo: str) -> str:
    caminho_txt = str(caminho or "").strip()
    corpo = str(conteudo or "").strip()
    if not caminho_txt:
        return corpo
    if not corpo:
        return f"🧭 {caminho_txt}"
    return f"🧭 {caminho_txt}\n\n{corpo}"


def _texto_painel_inicial(membro: dict, observacao: str = "") -> str:
    nome = str(membro.get("Nome", "") or "").strip()
    linhas = [
        "🐐 *Bode Andarilho*",
        "",
        f"Saudações, Ir.·. {nome}!" if nome else "Saudações fraternas!",
        "",
        "Escolha uma opção abaixo para continuar.",
        "Se limpar a conversa, basta digitar /start para reconstruir este painel.",
    ]
    observacao = str(observacao or "").strip()
    if observacao:
        linhas.extend(["", observacao])
    return "\n".join(linhas)


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


async def _enviar_ou_editar_mensagem(
    context, 
    user_id: int, 
    tipo: str, 
    texto: str, 
    teclado = None,
    parse_mode: str = "Markdown",
    limpar_conteudo: bool = False,
    incluir_rodape_global: bool = True,
) -> bool:
    global estado_mensagens
    
    if user_id not in estado_mensagens:
        estado_mensagens[user_id] = {}

    teclado_final = _teclado_com_inicio(teclado, incluir_rodape_global)
    hash_atual = _gerar_hash_conteudo(texto, teclado_final)
    dados_anteriores = estado_mensagens[user_id].get(tipo)

    if dados_anteriores and dados_anteriores.get("content_hash") == hash_atual:
        return True

    if dados_anteriores:
        try:
            await context.bot.edit_message_text(
                chat_id=user_id,
                message_id=dados_anteriores["message_id"],
                text=texto,
                parse_mode=parse_mode,
                reply_markup=teclado_final
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
            reply_markup=teclado_final
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


async def _executar_limpeza_historico(context, user_id: int, referencia_message_id: Optional[int]) -> int:
    deletadas = 0
    if not referencia_message_id:
        return deletadas

    for i in range(1, 101):
        try:
            await context.bot.delete_message(chat_id=user_id, message_id=referencia_message_id - i)
            deletadas += 1
        except Exception:
            continue
    return deletadas


# ============================================
# FLUXO DE NAVEGAÇÃO ENTRE COLUNAS
# ============================================

async def criar_estrutura_inicial(context, user_id: int, membro: dict) -> bool:
    """Inicia a egrégora do bot enviando o menu permanente e contexto inicial.

    Antes de exibir qualquer menu, verifica se o membro ainda está presente
    no grupo configurado (GRUPO_TELEGRAM_ID). Se não estiver, nega o acesso
    e orienta a retornar ao grupo.
    """
    # ── Verificação de presença no grupo ─────────────────────────────────────────
    esta_no_grupo = await _verificar_membro_no_grupo(context, user_id)
    if not esta_no_grupo:
        await _enviar_ou_editar_mensagem(
            context,
            user_id,
            TIPO_RESULTADO,
            (
                "⛔ *Acesso suspenso.*\n\n"
                "O acesso ao painel requer participação ativa no grupo do Bode Andarilho.\n"
                "Volte ao grupo e tente novamente."
            ),
            limpar_conteudo=True,
        )
        return False

    return await _mostrar_painel_principal(context, user_id, membro)


async def _mostrar_painel_principal(
    context,
    user_id: int,
    membro: dict,
    observacao: str = "",
) -> bool:
    nivel = get_nivel(user_id)

    await _limpar_mensagens_anteriores(context, user_id, [TIPO_MENU, TIPO_CONTEXTO])
    return await _enviar_ou_editar_mensagem(
        context,
        user_id,
        TIPO_RESULTADO,
        _texto_painel_inicial(membro, observacao),
        menu_principal_teclado(nivel),
        limpar_conteudo=True,
        incluir_rodape_global=False,
    )


async def navegar_para(
    update: Update, 
    context: ContextTypes.DEFAULT_TYPE,
    caminho: str,
    conteudo: str,
    teclado = None,
    limpar_conteudo: bool = False
) -> bool:
    user_id = update.effective_user.id
    return await _enviar_ou_editar_mensagem(
        context,
        user_id,
        TIPO_RESULTADO,
        _montar_tela_privada(caminho, conteudo),
        teclado,
        limpar_conteudo=limpar_conteudo,
    )


async def voltar_ao_menu_principal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    membro = buscar_membro(user_id)
    
    if not membro:
        return

    await _mostrar_painel_principal(
        context,
        user_id,
        membro,
        "Painel restaurado. Pode seguir por qualquer uma das opções abaixo.",
    )


async def limpar_historico(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Remove mensagens antigas para manter a limpeza e a ordem do chat."""
    query = update.callback_query
    await _responder_callback_seguro(query, "Limpando registros...")
    
    user_id = update.effective_user.id
    referencia_message_id = None
    try:
        referencia_message_id = update.callback_query.message.message_id
    except Exception as e:
        logger.debug(f"Aviso de limpeza: {e}")

    deletadas = await _executar_limpeza_historico(context, user_id, referencia_message_id)

    membro = buscar_membro(user_id)
    if not membro:
        return

    observacao = f"🧹 Conversa organizada. {deletadas} mensagem(ns) antigas foram removidas."
    await _mostrar_painel_principal(context, user_id, membro, observacao)


# ============================================
# COMANDO /START
# ============================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ponto de entrada: verifica se o Ir.·. está regular no sistema."""
    if update.effective_chat and update.effective_chat.type in ["group", "supergroup"]:
        username = (getattr(context.bot, "username", None) or "BodeAndarilhoBot").lstrip("@")
        link_privado = f"https://t.me/{username}?start=cadastro"
        await update.message.reply_text(
            "📩 Para continuar, fale comigo no privado.\n\n"
            "Toque no botão abaixo para começar.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🚀 Abrir privado do bot", url=link_privado)]]
            ),
        )
        return

    telegram_id = update.effective_user.id
    raw_arg = ""
    payload_start = ""
    if getattr(context, "args", None) and context.args:
        raw_arg = str(context.args[0] or "").strip()
        payload_start = raw_arg.lower()

    if raw_arg.upper().startswith("VOUCHER_"):
        from src.sheets_supabase import verificar_voucher
        try:
            v_data = verificar_voucher(raw_arg)
            if v_data:
                loja = v_data.get("loja_enriquecida") or {}
                context.user_data["cadastro_loja"] = (loja.get("Nome da Loja") or loja.get("nome") or "").strip()
                context.user_data["cadastro_numero_loja"] = str(loja.get("Número") or loja.get("numero") or "0").strip()
                context.user_data["cadastro_oriente"] = (loja.get("Oriente da Loja") or loja.get("oriente") or "").strip()
                context.user_data["cadastro_potencia"] = (loja.get("Potência") or loja.get("potencia") or "").strip()
                context.user_data["cadastro_potencia_complemento"] = ""
                context.user_data["cadastro_voucher"] = raw_arg.strip()
                logger.info("Voucher %s ativado.", raw_arg)
        except Exception as v_err:
            logger.error("Erro voucher: %s", v_err)

    veio_do_grupo = payload_start in {"cadastro", "grupo", "start"}
    membro = buscar_membro(telegram_id)

    if membro and membro_esta_ativo(membro):
        await _limpar_mensagens_anteriores(context, telegram_id)
        await criar_estrutura_inicial(context, telegram_id, membro)
    else:
        from src.cadastro import cadastro_start as iniciar_cadastro
        if membro and not membro_esta_ativo(membro):
            context.user_data["forcar_revalidacao_cadastro"] = True
        if veio_do_grupo:
            context.user_data["origem_grupo_cadastro"] = True
        await iniciar_cadastro(update, context)


async def rotear_atalho_privado(update: Update, context: ContextTypes.DEFAULT_TYPE, texto: str) -> bool:
    texto_normalizado = _normalizar_texto_atalho(texto)
    destino = ATALHOS_TEXTO_PRIVADO.get(texto_normalizado)
    if not destino:
        user_id = update.effective_user.id if update.effective_user else 0
        nivel = get_nivel(user_id) if user_id else "1"

        if nivel in ("2", "3") and texto_normalizado in {"secretario", "area secretario"}:
            destino = "area_secretario"
        elif nivel == "3" and texto_normalizado in {"admin", "administracao", "area admin"}:
            destino = "area_admin"

    if not destino:
        return False

    if destino == "menu_principal":
        await voltar_ao_menu_principal(update, context)
    elif destino == "limpar_historico":
        membro = buscar_membro(update.effective_user.id if update.effective_user else 0)
        if membro:
            deletadas = await _executar_limpeza_historico(
                context,
                update.effective_user.id,
                update.message.message_id if update.message else None,
            )
            await _mostrar_painel_principal(
                context,
                update.effective_user.id,
                membro,
                f"🧹 Conversa organizada. {deletadas} mensagem(ns) antigas foram removidas.",
            )
        else:
            await start(update, context)
    elif destino == "ver_eventos":
        from src.eventos import mostrar_eventos
        await mostrar_eventos(update, context)
    elif destino == "minhas_confirmacoes":
        from src.eventos import minhas_confirmacoes
        await minhas_confirmacoes(update, context)
    elif destino == "meu_cadastro":
        from src.perfil import mostrar_perfil
        await mostrar_perfil(update, context)
    elif destino == "menu_lembretes":
        from src.membro_lembretes import menu_lembretes_membro
        await menu_lembretes_membro(update, context)
    elif destino == "menu_ajuda":
        from src.ajuda.menus import menu_ajuda_principal
        await menu_ajuda_principal(update, context)
    elif destino == "abrir_assistente_ia":
        from src.ia_assistente import abrir_assistente_ia
        await abrir_assistente_ia(update, context)
    elif destino == "area_secretario":
        from src.eventos_secretario import exibir_menu_secretario
        await exibir_menu_secretario(update, context)
    elif destino == "area_admin":
        from src.admin_acoes import exibir_menu_admin
        await exibir_menu_admin(update, context)
    else:
        return False

    return True


async def texto_privado_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if update.effective_chat and update.effective_chat.type != "private":
        return

    texto = (update.message.text or "").strip()
    if not texto:
        return

    if await rotear_atalho_privado(update, context, texto):
        return

    from src.ia_assistente import assistente_ia_texto_livre
    await assistente_ia_texto_livre(update, context)


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
            APENAS_SECRETARIO,
            limpar_conteudo=True
        )
        return
    
    if data == "area_admin" and nivel != "3":
        await _enviar_ou_editar_mensagem(
            context, telegram_id, TIPO_RESULTADO,
            APENAS_ADMIN,
            limpar_conteudo=True
        )
        return

    # Roteamento de Chamadas
    if data == "menu_principal":
        await voltar_ao_menu_principal(update, context)
    
    elif data == "limpar_historico":
        await limpar_historico(update, context)
    elif data == "menu_lembretes":
        from src.membro_lembretes import menu_lembretes_membro
        await menu_lembretes_membro(update, context)
    elif data == "abrir_assistente_ia":
        from src.ia_assistente import abrir_assistente_ia
        await abrir_assistente_ia(update, context)
    elif data == "abrir_assistente_stats":
        from src.ia_assistente import assistente_ia_stats
        await assistente_ia_stats(update, context)
    elif data == "abrir_assistente_relatorio":
        from src.ia_assistente import assistente_ia_relatorio
        await assistente_ia_relatorio(update, context)

    # --- Callbacks IA Multinível (criação de evento por linguagem natural) ---
    elif data == "ia_confirmar_evento":
        from src.ia_assistente import ia_confirmar_evento
        await ia_confirmar_evento(update, context)
    elif data == "ia_forcar_evento":
        from src.ia_assistente import ia_forcar_evento
        await ia_forcar_evento(update, context)
    elif data == "ia_editar_evento":
        from src.ia_assistente import ia_editar_evento
        await ia_editar_evento(update, context)
    elif data == "ia_cancelar_evento":
        from src.ia_assistente import ia_cancelar_evento
        await ia_cancelar_evento(update, context)

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
    elif data.startswith("rito|"):
        from src.eventos import mostrar_eventos_por_rito
        await mostrar_eventos_por_rito(update, context)
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
    elif data == "ev_cancelar":
        from src.cadastro_evento import ev_cancelar
        await ev_cancelar(update, context)
    
    # Alternativa
    else:
        await _enviar_ou_editar_mensagem(
            context, telegram_id, TIPO_RESULTADO,
            "Esta funcionalidade ainda está em fase de polimento.",
            limpar_conteudo=True
        )


__all__ = [
    'start',
    'botao_handler',
    'texto_privado_router',
    'menu_principal_teclado',
    'criar_estrutura_inicial',
    'navegar_para',
    'voltar_ao_menu_principal',
    'rotear_atalho_privado',
    '_enviar_ou_editar_mensagem',
    'TIPO_MENU',
    'TIPO_CONTEXTO',
    'TIPO_RESULTADO',
]
