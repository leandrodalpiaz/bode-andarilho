# src/bot.py
# ============================================
# BODE ANDARILHO - GERENCIADOR DE MENUS E NAVEGAÇÃO
# ============================================
# 
# Este módulo é o coração da experiência do usuário no bot.
# Implementa o sistema de "menu fixo" + duas mensagens dinâmicas:
# 
# 1. MENU FIXO: Mensagem permanente no topo do chat
#    - Nunca é apagada ou editada
#    - Contém os botões principais do menu
#    - Baseado no nível do usuário (comum, secretário, admin)
# 
# 2. MENSAGEM DE CONTEXTO: Mostra onde o usuário está
#    - Editada a cada navegação
#    - Exibe o caminho percorrido (ex: "Ver Eventos > Esta semana")
# 
# 3. MENSAGEM DE RESULTADO: Mostra o conteúdo/opções atuais
#    - Editada a cada ação
#    - Contém os botões específicos da função atual
# 
# ============================================

from __future__ import annotations

import logging
import hashlib
from typing import Dict, Optional, Tuple

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from src.sheets import buscar_membro
from src.cadastro import cadastro_start
from src.perfil import mostrar_perfil
from src.permissoes import get_nivel

logger = logging.getLogger(__name__)

# ============================================
# CONTROLE DE ESTADO DAS MENSAGENS
# ============================================
# Estrutura: {user_id: {
#     "menu": {"message_id": id, "content_hash": str},
#     "contexto": {"message_id": id, "content_hash": str},
#     "resultado": {"message_id": id, "content_hash": str}
# }}
estado_mensagens: Dict[int, dict] = {}

# Constantes para identificar os tipos de mensagem
TIPO_MENU = "menu"
TIPO_CONTEXTO = "contexto"
TIPO_RESULTADO = "resultado"


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

def _gerar_hash_conteudo(texto: str, teclado) -> str:
    """
    Gera um hash MD5 do conteúdo para verificar se houve mudança.
    
    Args:
        texto (str): Texto da mensagem
        teclado: Teclado inline (ou None)
    
    Returns:
        str: Hash MD5 do conteúdo
    """
    teclado_str = str(teclado.to_dict()) if teclado else ""
    conteudo = f"{texto}|{teclado_str}"
    return hashlib.md5(conteudo.encode()).hexdigest()


async def _enviar_ou_editar_mensagem(
    context, 
    user_id: int, 
    tipo: str, 
    texto: str, 
    teclado = None,
    parse_mode: str = "Markdown"
) -> bool:
    """
    Gerencia o envio/edição de mensagens do sistema de menu fixo.
    
    Args:
        context: Context do Telegram
        user_id (int): ID do usuário
        tipo (str): Tipo da mensagem (TIPO_MENU, TIPO_CONTEXTO, TIPO_RESULTADO)
        texto (str): Texto da mensagem
        teclado: Teclado inline (opcional)
        parse_mode (str): Modo de formatação do texto
    
    Returns:
        bool: True se bem-sucedido
    """
    global estado_mensagens
    
    # Garante que o usuário tem entrada no dicionário
    if user_id not in estado_mensagens:
        estado_mensagens[user_id] = {}
    
    hash_atual = _gerar_hash_conteudo(texto, teclado)
    dados_anteriores = estado_mensagens[user_id].get(tipo)
    
    # Se já existe uma mensagem deste tipo
    if dados_anteriores:
        # Verifica se o conteúdo mudou
        if dados_anteriores.get("content_hash") == hash_atual:
            logger.info(f"[{tipo}] Conteúdo inalterado para usuário {user_id}")
            return True
        
        # Tenta editar a mensagem existente
        try:
            await context.bot.edit_message_text(
                chat_id=user_id,
                message_id=dados_anteriores["message_id"],
                text=texto,
                parse_mode=parse_mode,
                reply_markup=teclado
            )
            logger.info(f"[{tipo}] Mensagem editada para usuário {user_id}")
            
            # Atualiza o hash
            estado_mensagens[user_id][tipo]["content_hash"] = hash_atual
            return True
            
        except Exception as e:
            # Se não conseguir editar, remove o registro e envia nova
            logger.warning(f"[{tipo}] Erro ao editar para {user_id}: {e}")
            estado_mensagens[user_id].pop(tipo, None)
    
    # Envia nova mensagem
    try:
        msg = await context.bot.send_message(
            chat_id=user_id,
            text=texto,
            parse_mode=parse_mode,
            reply_markup=teclado
        )
        
        estado_mensagens[user_id][tipo] = {
            "message_id": msg.message_id,
            "content_hash": hash_atual
        }
        logger.info(f"[{tipo}] Nova mensagem enviada para usuário {user_id}")
        return True
        
    except Exception as e:
        logger.error(f"[{tipo}] Erro ao enviar para {user_id}: {e}")
        return False


async def _limpar_mensagens_anteriores(context, user_id: int, tipos: list = None):
    """
    Remove mensagens antigas do usuário (útil para limpeza).
    
    Args:
        context: Context do Telegram
        user_id (int): ID do usuário
        tipos (list): Lista de tipos a remover (None = todos)
    """
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
                logger.info(f"[{tipo}] Mensagem deletada para usuário {user_id}")
            except Exception:
                pass  # Ignora erros ao deletar
            estado_mensagens[user_id].pop(tipo, None)


# ============================================
# FUNÇÕES PRINCIPAIS DE NAVEGAÇÃO
# ============================================

async def criar_estrutura_inicial(context, user_id: int, membro: dict) -> bool:
    """
    Cria a estrutura inicial de mensagens para um usuário.
    Envia o menu fixo e as mensagens de contexto/resultado iniciais.
    
    Args:
        context: Context do Telegram
        user_id (int): ID do usuário
        membro (dict): Dados do membro
    
    Returns:
        bool: True se bem-sucedido
    """
    nivel = get_nivel(user_id)
    
    # 1. Menu fixo (nunca é editado)
    texto_menu = f"🐐 *Bode Andarilho*\n\nBem-vindo, irmão {membro.get('Nome', '')}!"
    sucesso = await _enviar_ou_editar_mensagem(
        context, user_id, TIPO_MENU, texto_menu, menu_principal_teclado(nivel)
    )
    
    if not sucesso:
        return False
    
    # 2. Mensagem de contexto inicial
    await _enviar_ou_editar_mensagem(
        context, user_id, TIPO_CONTEXTO, "📍 *Menu Principal*"
    )
    
    # 3. Mensagem de resultado inicial
    await _enviar_ou_editar_mensagem(
        context, user_id, TIPO_RESULTADO,
        "Escolha uma opção no menu acima para começar."
    )
    
    return True


async def navegar_para(
    update: Update, 
    context: ContextTypes.DEFAULT_TYPE,
    caminho: str,
    conteudo: str,
    teclado = None
) -> bool:
    """
    Função auxiliar para navegação entre telas.
    Atualiza a mensagem de contexto e a mensagem de resultado.
    
    Args:
        update: Update do Telegram
        context: Context do Telegram
        caminho (str): Caminho atual (ex: "Ver Eventos > Esta semana")
        conteudo (str): Conteúdo a ser exibido
        teclado: Teclado para a mensagem de resultado
    
    Returns:
        bool: True se bem-sucedido
    """
    user_id = update.effective_user.id
    
    # Atualiza mensagem de contexto
    await _enviar_ou_editar_mensagem(
        context, user_id, TIPO_CONTEXTO, f"📍 *{caminho}*"
    )
    
    # Atualiza mensagem de resultado
    return await _enviar_ou_editar_mensagem(
        context, user_id, TIPO_RESULTADO, conteudo, teclado
    )


async def voltar_ao_menu_principal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Retorna o usuário ao menu principal.
    Atualiza contexto e resultado para o estado inicial.
    """
    user_id = update.effective_user.id
    membro = buscar_membro(user_id)
    
    if not membro:
        return
    
    # Atualiza contexto
    await _enviar_ou_editar_mensagem(
        context, user_id, TIPO_CONTEXTO, "📍 *Menu Principal*"
    )
    
    # Atualiza resultado
    await _enviar_ou_editar_mensagem(
        context, user_id, TIPO_RESULTADO,
        "Escolha uma opção no menu acima para começar."
    )


# ============================================
# HANDLER DO COMANDO /start
# ============================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handler para comando /start.
    
    Fluxo:
    - Em grupo: orienta a usar o privado
    - Em privado: se cadastrado, cria estrutura de menu; se não, inicia cadastro
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
        # Limpa mensagens anteriores (se houver) e cria nova estrutura
        await _limpar_mensagens_anteriores(context, telegram_id)
        await criar_estrutura_inicial(context, telegram_id, membro)
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
        await _enviar_ou_editar_mensagem(
            context, telegram_id, TIPO_RESULTADO,
            "⛔ Você não tem permissão para acessar a Área do Secretário."
        )
        return
    
    if data == "area_admin" and nivel != "3":
        await _enviar_ou_editar_mensagem(
            context, telegram_id, TIPO_RESULTADO,
            "⛔ Você não tem permissão para acessar a Área do Administrador."
        )
        return

    # ========================================
    # ROTEAMENTO DE CALLBACKS
    # ========================================
    
    # Voltar ao menu principal
    if data == "menu_principal":
        await voltar_ao_menu_principal(update, context)
    
    # Eventos
    elif data == "ver_eventos":
        from src.eventos import mostrar_eventos
        await mostrar_eventos(update, context)
    
    # Confirmações do usuário
    elif data == "minhas_confirmacoes":
        from src.eventos import minhas_confirmacoes
        await minhas_confirmacoes(update, context)
    
    # Perfil
    elif data == "meu_cadastro":
        await mostrar_perfil(update, context)

    # Áreas restritas
    elif data == "area_secretario":
        from src.bot import mostrar_area_secretario
        await mostrar_area_secretario(update, context)
    elif data == "area_admin":
        from src.bot import mostrar_area_admin
        await mostrar_area_admin(update, context)

    # Outros callbacks são passados para seus respectivos handlers
    else:
        # Os handlers específicos (eventos_por_data, grau, etc.) serão chamados
        # por seus próprios módulos, mas precisamos garantir que eles usem
        # o sistema de navegação
        pass


# ============================================
# FUNÇÕES AUXILIARES PARA OUTROS MÓDULOS
# ============================================

async def mostrar_area_secretario(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menu da área do secretário."""
    from src.eventos_secretario import exibir_menu_secretario
    await exibir_menu_secretario(update, context)


async def mostrar_area_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menu da área do administrador."""
    from src.admin_acoes import exibir_menu_admin
    await exibir_menu_admin(update, context)


# ============================================
# EXPORTAÇÃO DAS FUNÇÕES NECESSÁRIAS
# ============================================

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