# src/bot.py
# ============================================
# MÓDULO DE MENUS E NAVEGAÇÃO PRINCIPAL
# ============================================
# Gerencia os menus principais do bot e a navegação
# entre as diferentes áreas (comum, secretário, admin).
# Também controla o envio/edição de mensagens para
# evitar duplicação no privado do usuário.
# ============================================

from __future__ import annotations

import logging
import hashlib
from typing import Dict, Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from src.sheets import buscar_membro
from src.cadastro import cadastro_start
from src.perfil import mostrar_perfil
from src.permissoes import get_nivel

logger = logging.getLogger(__name__)

# ============================================
# CONTROLE DE MENSAGENS DUPLICADAS
# ============================================
# Estrutura: {user_id: {
#     "chat_id": id,
#     "message_id": id,
#     "content_hash": str  # Hash do conteúdo para detectar mudanças
# }}
ultima_mensagem_menu: Dict[int, dict] = {}


# ============================================
# MENU PRINCIPAL (BASEADO NO NÍVEL)
# ============================================

def menu_principal_teclado(nivel: str) -> InlineKeyboardMarkup:
    """
    Gera o teclado do menu principal baseado no nível do usuário.
    
    Args:
        nivel (str): Nível do usuário ("1", "2" ou "3")
    
    Returns:
        InlineKeyboardMarkup: Teclado com os botões apropriados
    """
    botoes = [
        [InlineKeyboardButton("📅 Ver eventos", callback_data="ver_eventos")],
        [InlineKeyboardButton("✅ Minhas confirmações", callback_data="minhas_confirmacoes")],
        [InlineKeyboardButton("👤 Meu cadastro", callback_data="meu_cadastro")],
    ]

    # Secretários e admins têm acesso à área do secretário
    if nivel in ("2", "3"):
        botoes.append([InlineKeyboardButton("📋 Área do Secretário", callback_data="area_secretario")])

    # Apenas admins têm acesso à área administrativa
    if nivel == "3":
        botoes.append([InlineKeyboardButton("⚙️ Área do Administrador", callback_data="area_admin")])

    return InlineKeyboardMarkup(botoes)


# ============================================
# UTILITÁRIOS PARA EDIÇÃO DE MENSAGENS
# ============================================

async def _safe_edit(query, text: str, **kwargs):
    """
    Edita uma mensagem de forma segura, ignorando erro "Message not modified".
    
    Args:
        query: CallbackQuery do Telegram
        text (str): Novo texto da mensagem
        **kwargs: Argumentos adicionais para edit_message_text
    """
    try:
        await query.edit_message_text(text, **kwargs)
    except Exception as e:
        if "Message is not modified" not in str(e):
            raise


def _gerar_hash_conteudo(texto: str, teclado) -> str:
    """
    Gera um hash MD5 do conteúdo para verificar se houve mudança.
    
    Args:
        texto (str): Texto da mensagem
        teclado: Teclado inline (ou None)
    
    Returns:
        str: Hash MD5 do conteúdo
    """
    # Converte o teclado para string representativa
    teclado_str = str(teclado.to_dict()) if teclado else ""
    conteudo = f"{texto}|{teclado_str}"
    
    return hashlib.md5(conteudo.encode()).hexdigest()


async def _verificar_mensagem_existe(context, user_id: int, message_id: int) -> bool:
    """
    Verifica se uma mensagem ainda existe no chat do usuário.
    
    Args:
        context: Context do Telegram
        user_id (int): ID do usuário
        message_id (int): ID da mensagem
    
    Returns:
        bool: True se a mensagem existe, False caso contrário
    """
    try:
        await context.bot.get_chat(user_id)
        # Não temos como verificar diretamente se a mensagem existe,
        # então assumimos que se o chat existe, a mensagem pode existir
        return True
    except Exception:
        return False


async def enviar_ou_editar_menu(context, user_id: int, texto: str, teclado) -> bool:
    """
    Envia uma nova mensagem ou edita a última mensagem do menu.
    Mantém apenas UMA mensagem visível no privado do usuário.
    
    Regras:
    - Se não existe mensagem anterior: envia nova
    - Se existe e o conteúdo mudou: tenta editar
    - Se existe e o conteúdo é o mesmo: NÃO FAZ NADA
    - Se a mensagem anterior foi apagada: envia nova
    
    Args:
        context: Context do Telegram
        user_id (int): ID do usuário
        texto (str): Texto da mensagem
        teclado: Teclado inline
    
    Returns:
        bool: True se bem-sucedido
    """
    global ultima_mensagem_menu
    
    # Gera hash do conteúdo atual
    hash_atual = _gerar_hash_conteudo(texto, teclado)
    
    # Verifica se já existe uma mensagem anterior para este usuário
    if user_id in ultima_mensagem_menu:
        dados_anteriores = ultima_mensagem_menu[user_id]
        
        # Verifica se a mensagem anterior ainda existe
        mensagem_existe = await _verificar_mensagem_existe(context, user_id, dados_anteriores["message_id"])
        
        if not mensagem_existe:
            # Mensagem foi apagada - remove registro e envia nova
            logger.info(f"Mensagem anterior do usuário {user_id} foi apagada - enviando nova")
            ultima_mensagem_menu.pop(user_id, None)
        else:
            # Mensagem existe: verifica se o conteúdo mudou
            if dados_anteriores.get("content_hash") == hash_atual:
                logger.info(f"Conteúdo do menu inalterado para usuário {user_id} - mantendo mensagem existente")
                return True
            
            # Conteúdo diferente: tenta editar
            try:
                await context.bot.edit_message_text(
                    chat_id=user_id,
                    message_id=dados_anteriores["message_id"],
                    text=texto,
                    parse_mode="Markdown",
                    reply_markup=teclado
                )
                logger.info(f"Menu editado para usuário {user_id}")
                
                # Atualiza o hash
                ultima_mensagem_menu[user_id]["content_hash"] = hash_atual
                return True
                
            except Exception as e:
                # Se não conseguir editar (mensagem apagada ou erro)
                logger.warning(f"Não foi possível editar mensagem para {user_id}: {e}")
                ultima_mensagem_menu.pop(user_id, None)
    
    # Envia nova mensagem
    try:
        msg = await context.bot.send_message(
            chat_id=user_id,
            text=texto,
            parse_mode="Markdown",
            reply_markup=teclado
        )
        
        # Armazena o ID da nova mensagem e o hash
        ultima_mensagem_menu[user_id] = {
            "chat_id": user_id,
            "message_id": msg.message_id,
            "content_hash": hash_atual
        }
        logger.info(f"Novo menu enviado para usuário {user_id}")
        return True
    except Exception as e:
        logger.error(f"Erro ao enviar menu para {user_id}: {e}")
        return False


# ============================================
# FUNÇÃO PRINCIPAL DE ENVIO DO MENU
# ============================================

async def enviar_menu_principal(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int, membro: dict):
    """
    Função unificada para enviar o menu principal.
    Usa enviar_ou_editar_menu para manter apenas uma mensagem.
    
    Args:
        update: Update do Telegram
        context: Context do Telegram
        user_id (int): ID do usuário
        membro (dict): Dados do membro
    """
    nivel = get_nivel(user_id)
    texto = f"🐐 *Bode Andarilho*\n\nBem-vindo de volta, irmão {membro.get('Nome', '')}!\n\nO que deseja fazer?"
    
    await enviar_ou_editar_menu(
        context,
        user_id,
        texto,
        menu_principal_teclado(nivel)
    )


# ============================================
# HANDLER DO COMANDO /start
# ============================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handler para comando /start.
    
    Fluxo:
    - Em grupo: orienta a usar o privado
    - Em privado: se cadastrado, mostra menu; se não, inicia cadastro
    """
    logger.info(
        "start chamado - chat_type=%s user_id=%s",
        getattr(update.effective_chat, "type", None),
        getattr(update.effective_user, "id", None),
    )

    # Se estiver em grupo, orienta a ir para o privado
    if update.effective_chat and update.effective_chat.type in ["group", "supergroup"]:
        await update.message.reply_text(
            "🔒 Para interagir comigo, fale no privado.\n\n"
            "Clique aqui: @BodeAndarilhoBot e envie /start"
        )
        return

    # Se já está em privado, prossegue normalmente
    telegram_id = update.effective_user.id
    membro = buscar_membro(telegram_id)

    if membro:
        await enviar_menu_principal(update, context, telegram_id, membro)
    else:
        await cadastro_start(update, context)


# ============================================
# HANDLER GENÉRICO DE BOTÕES
# ============================================

async def botao_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handler genérico para botões (deve ser o último).
    Captura qualquer callback não tratado por handlers específicos.
    """
    query = update.callback_query
    if not query:
        return

    data = query.data or ""
    await query.answer()

    # ========================================
    # GUARDRAILS: CALLBACKS DE OUTROS HANDLERS
    # ========================================
    # Estes callbacks são tratados por ConversationHandlers
    # e não devem ser processados aqui
    
    if data in {"admin_promover", "admin_rebaixar", "editar_perfil", "admin_editar_membro"}:
        return

    if data.startswith("confirmar|"):
        return

    if data in {"iniciar_cadastro", "editar_cadastro", "continuar_cadastro"}:
        return

    if data == "editar_evento_secretario":
        return

    telegram_id = update.effective_user.id
    nivel = get_nivel(telegram_id)

    # ========================================
    # VERIFICAÇÃO DE PERMISSÕES
    # ========================================
    
    if data == "area_secretario" and nivel not in ["2", "3"]:
        await _safe_edit(query, "⛔ Você não tem permissão para acessar a Área do Secretário.")
        return
    
    if data == "area_admin" and nivel != "3":
        await _safe_edit(query, "⛔ Você não tem permissão para acessar a Área do Administrador.")
        return

    # ========================================
    # ROTEAMENTO DE CALLBACKS
    # ========================================
    
    # Eventos (com pipe |)
    if data == "ver_eventos":
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
    elif data.startswith("ver_confirmados|"):
        from src.eventos import ver_confirmados
        await ver_confirmados(update, context)
    elif data.startswith("cancelar|") or data.startswith("confirma_cancelar|"):
        from src.eventos import cancelar_presenca
        await cancelar_presenca(update, context)
    elif data == "fechar_mensagem":
        from src.eventos import fechar_mensagem
        await fechar_mensagem(update, context)
    
    # Confirmações do usuário
    elif data == "minhas_confirmacoes":
        from src.eventos import minhas_confirmacoes
        await minhas_confirmacoes(update, context)
    elif data.startswith("detalhes_confirmado|"):
        from src.eventos import detalhes_confirmado
        await detalhes_confirmado(update, context)
    elif data.startswith("detalhes_historico|"):
        from src.eventos import detalhes_historico
        await detalhes_historico(update, context)
    
    # Perfil
    elif data == "meu_cadastro":
        await mostrar_perfil(update, context)

    # Áreas restritas
    elif data == "area_secretario":
        await mostrar_area_secretario(update, context)
    elif data == "area_admin":
        await mostrar_area_admin(update, context)

    # Menu principal
    elif data == "menu_principal":
        membro = buscar_membro(telegram_id)
        if membro:
            await enviar_menu_principal(update, context, telegram_id, membro)

    # ========================================
    # SECRETÁRIO/ADMIN - IMPORTS TARDIOS
    # ========================================
    # Estes imports são feitos aqui para evitar
    # dependências circulares
    
    elif data == "cadastrar_evento":
        from src.cadastro_evento import novo_evento_start
        await novo_evento_start(update, context)
    elif data == "ver_confirmados_secretario":
        from src.admin_acoes import ver_confirmados_secretario
        await ver_confirmados_secretario(update, context)
    elif data == "encerrar_evento":
        from src.admin_acoes import encerrar_evento
        await encerrar_evento(update, context)
    elif data == "meus_eventos":
        from src.eventos_secretario import meus_eventos
        await meus_eventos(update, context)
    elif data.startswith("gerenciar_evento|"):
        from src.eventos_secretario import menu_gerenciar_evento
        await menu_gerenciar_evento(update, context)
    elif data.startswith("confirmar_cancelamento|"):
        from src.eventos_secretario import confirmar_cancelamento
        await confirmar_cancelamento(update, context)
    elif data.startswith("cancelar_evento|"):
        from src.eventos_secretario import executar_cancelamento
        await executar_cancelamento(update, context)
    
    # Admin
    elif data == "admin_ver_membros":
        from src.admin_acoes import ver_todos_membros
        await ver_todos_membros(update, context)
    
    # Lojas
    elif data == "menu_lojas":
        from src.lojas import menu_lojas
        await menu_lojas(update, context)
    elif data == "loja_listar":
        from src.lojas import listar_lojas_handler
        await listar_lojas_handler(update, context)
    
    # Notificações
    elif data == "menu_notificacoes":
        from src.admin_acoes import menu_notificacoes
        await menu_notificacoes(update, context)
    elif data == "notificacoes_ativar":
        from src.admin_acoes import notificacoes_ativar
        await notificacoes_ativar(update, context)
    elif data == "notificacoes_desativar":
        from src.admin_acoes import notificacoes_desativar
        await notificacoes_desativar(update, context)

    # Fallback para callbacks não reconhecidos
    else:
        await _safe_edit(query, "Função em desenvolvimento ou comando não reconhecido.")


# ============================================
# MENU DA ÁREA DO SECRETÁRIO
# ============================================

async def mostrar_area_secretario(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Menu da área do secretário.
    Se acionado em grupo, redireciona para o privado.
    """
    query = update.callback_query
    if not query:
        return
    await query.answer()

    # Redirecionamento do grupo para o privado
    if update.effective_chat.type in ["group", "supergroup"]:
        await _safe_edit(
            query,
            "🔔 A Área do Secretário será aberta no meu chat privado. "
            "Verifique suas mensagens.",
        )
        user_id = update.effective_user.id
        await enviar_ou_editar_menu(
            context,
            user_id,
            "📋 *Área do Secretário*\n\nO que deseja fazer?",
            InlineKeyboardMarkup([
                [InlineKeyboardButton("📌 Cadastrar evento", callback_data="cadastrar_evento")],
                [InlineKeyboardButton("📋 Meus eventos", callback_data="meus_eventos")],
                [InlineKeyboardButton("👥 Ver confirmados por evento", callback_data="ver_confirmados_secretario")],
                [InlineKeyboardButton("🏛️ Minhas lojas", callback_data="menu_lojas")],
                [InlineKeyboardButton("🔔 Configurar notificações", callback_data="menu_notificacoes")],
                [InlineKeyboardButton("⬅️ Voltar ao menu", callback_data="menu_principal")],
            ])
        )
        return

    # Já está no privado
    telegram_id = update.effective_user.id
    nivel = get_nivel(telegram_id)

    if nivel not in ["2", "3"]:
        await _safe_edit(query, "⛔ Você não tem permissão para acessar esta área.")
        return

    teclado = InlineKeyboardMarkup([
        [InlineKeyboardButton("📌 Cadastrar evento", callback_data="cadastrar_evento")],
        [InlineKeyboardButton("📋 Meus eventos", callback_data="meus_eventos")],
        [InlineKeyboardButton("👥 Ver confirmados por evento", callback_data="ver_confirmados_secretario")],
        [InlineKeyboardButton("🏛️ Minhas lojas", callback_data="menu_lojas")],
        [InlineKeyboardButton("🔔 Configurar notificações", callback_data="menu_notificacoes")],
        [InlineKeyboardButton("⬅️ Voltar", callback_data="menu_principal")],
    ])

    await _safe_edit(
        query,
        "📋 *Área do Secretário*\n\nO que deseja fazer?",
        parse_mode="Markdown",
        reply_markup=teclado,
    )


# ============================================
# MENU DA ÁREA DO ADMINISTRADOR
# ============================================

async def mostrar_area_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Menu da área do administrador.
    Se acionado em grupo, redireciona para o privado.
    """
    query = update.callback_query
    if not query:
        return
    await query.answer()

    # Redirecionamento do grupo para o privado
    if update.effective_chat.type in ["group", "supergroup"]:
        await _safe_edit(
            query,
            "🔔 A Área do Administrador será aberta no meu chat privado. "
            "Verifique suas mensagens.",
        )
        user_id = update.effective_user.id
        await enviar_ou_editar_menu(
            context,
            user_id,
            "⚙️ *Área do Administrador*\n\nO que deseja fazer?",
            InlineKeyboardMarkup([
                [InlineKeyboardButton("📌 Cadastrar evento", callback_data="cadastrar_evento")],
                [InlineKeyboardButton("📋 Gerenciar eventos", callback_data="meus_eventos")],
                [InlineKeyboardButton("👥 Ver todos os membros", callback_data="admin_ver_membros")],
                [InlineKeyboardButton("✏️ Editar membro", callback_data="admin_editar_membro")],
                [InlineKeyboardButton("🟢 Promover secretário", callback_data="admin_promover")],
                [InlineKeyboardButton("🔻 Rebaixar secretário", callback_data="admin_rebaixar")],
                [InlineKeyboardButton("🏛️ Minhas lojas", callback_data="menu_lojas")],
                [InlineKeyboardButton("🔔 Configurar notificações", callback_data="menu_notificacoes")],
                [InlineKeyboardButton("⬅️ Voltar ao menu", callback_data="menu_principal")],
            ])
        )
        return

    # Já está no privado
    telegram_id = update.effective_user.id
    nivel = get_nivel(telegram_id)

    if nivel != "3":
        await _safe_edit(query, "⛔ Você não tem permissão para acessar esta área.")
        return

    teclado = InlineKeyboardMarkup([
        [InlineKeyboardButton("📌 Cadastrar evento", callback_data="cadastrar_evento")],
        [InlineKeyboardButton("📋 Gerenciar eventos", callback_data="meus_eventos")],
        [InlineKeyboardButton("👥 Ver todos os membros", callback_data="admin_ver_membros")],
        [InlineKeyboardButton("✏️ Editar membro", callback_data="admin_editar_membro")],
        [InlineKeyboardButton("🟢 Promover secretário", callback_data="admin_promover")],
        [InlineKeyboardButton("🔻 Rebaixar secretário", callback_data="admin_rebaixar")],
        [InlineKeyboardButton("🏛️ Minhas lojas", callback_data="menu_lojas")],
        [InlineKeyboardButton("🔔 Configurar notificações", callback_data="menu_notificacoes")],
        [InlineKeyboardButton("⬅️ Voltar", callback_data="menu_principal")],
    ])

    await _safe_edit(
        query,
        "⚙️ *Área do Administrador*\n\nO que deseja fazer?",
        parse_mode="Markdown",
        reply_markup=teclado,
    )