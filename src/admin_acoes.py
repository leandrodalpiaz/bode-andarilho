# src/admin_acoes.py
# ============================================
# BODE ANDARILHO - AÇÕES ADMINISTRATIVAS
# ============================================
# 
# Este módulo gerencia todas as funcionalidades exclusivas para administradores:
# - Promoção e rebaixamento de membros
# - Edição de membros (qualquer campo)
# - Visualização da lista completa de membros
# - Configuração de notificações
# 
# Todas as funções que exibem resultados utilizam o sistema de
# navegação do bot.py para manter a consistência da interface.
# 
# ============================================

from __future__ import annotations

import logging
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)

from src.sheets_supabase import (
    listar_membros,
    atualizar_membro,
    buscar_membro,
    atualizar_nivel_membro,
    excluir_membro,
    get_notificacao_status,
    set_notificacao_status,
    listar_eventos,
    obter_secretario_responsavel_evento,
    listar_lojas_visiveis,
    listar_membros_por_loja,
)
from src.permissoes import get_nivel
from src.miniapp import WEBAPP_URL_EVENTO

from src.bot import (
    navegar_para,
    _enviar_ou_editar_mensagem,
    TIPO_RESULTADO,
    criar_estrutura_inicial
)

logger = logging.getLogger(__name__)


def _botao_cadastrar_evento() -> InlineKeyboardButton:
    """Retorna botão de cadastro priorizando o Mini App."""
    if WEBAPP_URL_EVENTO:
        return InlineKeyboardButton("📌 Cadastrar evento", web_app=WebAppInfo(url=WEBAPP_URL_EVENTO))
    return InlineKeyboardButton("📌 Cadastrar evento", callback_data="cadastrar_evento")

# ============================================
# CONSTANTES E CONFIGURAÇÕES
# ============================================

# Estados da conversação
SELECIONAR_MEMBRO, SELECIONAR_CAMPO, NOVO_VALOR = range(3)

# Mapeamento de campos editáveis (admin/secretário podem editar tudo exceto Telegram ID)
CAMPOS_EDITAVEIS = {
    "nome": {"nome": "Nome", "chave": "Nome", "nivel_minimo": "2"},
    "loja": {"nome": "Loja", "chave": "Loja", "nivel_minimo": "2"},
    "grau": {"nome": "Grau", "chave": "Grau", "nivel_minimo": "2"},
    "oriente": {"nome": "Oriente", "chave": "Oriente", "nivel_minimo": "2"},
    "potencia": {"nome": "Potência", "chave": "Potência", "nivel_minimo": "2"},
    "data_nasc": {"nome": "Data de nascimento", "chave": "Data de nascimento", "nivel_minimo": "2"},
    "numero_loja": {"nome": "Número da loja", "chave": "Número da loja", "nivel_minimo": "2"},
    "cargo": {"nome": "Cargo", "chave": "Cargo", "nivel_minimo": "2"},
    "veneravel_mestre": {"nome": "Venerável Mestre (Sim/Não)", "chave": "Venerável Mestre", "nivel_minimo": "2"},
    "nivel": {"nome": "Nível (1,2,3)", "chave": "Nivel", "nivel_minimo": "3"},  # Apenas admin pode editar nível
}


# ============================================
# FUNÇÃO AUXILIAR: IDs de membros da loja do secretário
# ============================================

def _obter_ids_membros_da_loja(user_id: int) -> set:
    """Retorna set de Telegram IDs dos membros das lojas do secretário."""
    lojas = listar_lojas_visiveis(user_id, "2")
    ids: set = set()
    for loja in lojas:
        loja_id = loja.get("ID") or loja.get("id")
        nome = loja.get("Nome da Loja") or loja.get("nome_loja") or ""
        numero = loja.get("Número") or loja.get("numero") or ""
        membros_loja = listar_membros_por_loja(
            loja_id=loja_id, nome_loja=nome, numero_loja=numero
        )
        for m in membros_loja:
            tid_raw = m.get("Telegram ID")
            try:
                ids.add(int(float(tid_raw)))
            except (TypeError, ValueError):
                continue
    return ids


# ============================================
# FUNÇÃO AUXILIAR DE CANCELAMENTO
# ============================================

async def cancelar_operacao(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancela a operação como alternativa para ConversationHandlers."""
    if update.message:
        await update.message.reply_text("Operação cancelada.")
    elif update.callback_query:
        await update.callback_query.edit_message_text("Operação cancelada.")
    return ConversationHandler.END


# ============================================
# FUNÇÃO PRINCIPAL DO MENU ADMIN
# ============================================

async def exibir_menu_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Exibe o menu principal da área do administrador.
    Esta função é chamada pelo bot.py quando o usuário acessa a área.
    """
    user_id = update.effective_user.id
    nivel = get_nivel(user_id)
    
    if nivel != "3":
        await _enviar_ou_editar_mensagem(
            context, user_id, TIPO_RESULTADO,
            "⛔ Você não tem permissão para acessar esta área."
        )
        return

    teclado = InlineKeyboardMarkup([
        [_botao_cadastrar_evento()],
        [InlineKeyboardButton("📋 Gerenciar todos os eventos", callback_data="meus_eventos")],
        [InlineKeyboardButton("👥 Ver todos os membros", callback_data="admin_ver_membros")],
        [InlineKeyboardButton("✏️ Editar membro", callback_data="admin_editar_membro")],
        [InlineKeyboardButton("🟢 Promover secretário", callback_data="admin_promover")],
        [InlineKeyboardButton("🔻 Rebaixar secretário", callback_data="admin_rebaixar")],
        [InlineKeyboardButton("🏛️ Gerenciar lojas", callback_data="menu_lojas")],
        [InlineKeyboardButton("🔔 Configurar notificações", callback_data="menu_notificacoes")],
        [InlineKeyboardButton("🔙 Voltar ao menu", callback_data="menu_principal")],
    ])

    await navegar_para(
        update, context,
        "Área do Administrador",
        "⚙️ *Bem-vindo à Área do Administrador*\n\nO que deseja fazer?",
        teclado
    )


# ============================================
# GERENCIAMENTO DE NOTIFICAÇÕES
# ============================================

async def menu_notificacoes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menu para o secretário gerenciar notificações."""
    user_id = update.effective_user.id
    nivel = get_nivel(user_id)
    
    if nivel not in ["2", "3"]:
        await _enviar_ou_editar_mensagem(
            context, user_id, TIPO_RESULTADO,
            "⛔ Apenas secretários e administradores podem acessar esta função."
        )
        return

    ativo = get_notificacao_status(user_id)
    status_texto = "✅ Ativadas" if ativo else "🔕 Desativadas"

    teclado = InlineKeyboardMarkup([
        [InlineKeyboardButton("📥 Ativar notificações", callback_data="notificacoes_ativar")],
        [InlineKeyboardButton("🔕 Desativar notificações", callback_data="notificacoes_desativar")],
        [InlineKeyboardButton("🔙 Voltar", callback_data="area_secretario" if nivel == "2" else "area_admin")],
    ])

    texto = (
        f"🔔 *Configurações de Notificações*\n\n"
        f"Status atual: {status_texto}\n\n"
        f"Quando ativadas, você receberá uma mensagem no privado "
        f"cada vez que alguém confirmar presença em um evento que você criou. "
        f"Esse mesmo ajuste também controla seus lembretes privados do bot.\n\n"
        f"*Nota:* Esta configuração é permanente e ficará salva na planilha."
    )

    await navegar_para(
        update, context,
        "Configurações > Notificações",
        texto,
        teclado
    )


async def notificacoes_ativar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ativa as notificações para o secretário."""
    user_id = update.effective_user.id
    
    if set_notificacao_status(user_id, True):
        await navegar_para(
            update, context,
            "Configurações > Notificações",
            "✅ *Notificações ativadas com sucesso!*\n\n"
            "Agora você receberá alertas de novas confirmações.",
            InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Voltar", callback_data="menu_notificacoes")
            ]])
        )
    else:
        await _enviar_ou_editar_mensagem(
            context, user_id, TIPO_RESULTADO,
            "❌ *Erro ao ativar notificações.*\n\nTente novamente mais tarde."
        )


async def notificacoes_desativar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Desativa as notificações para o secretário."""
    user_id = update.effective_user.id
    
    if set_notificacao_status(user_id, False):
        await navegar_para(
            update, context,
            "Configurações > Notificações",
            "🔕 *Notificações desativadas com sucesso!*\n\n"
            "Você não receberá mais alertas de novas confirmações.",
            InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Voltar", callback_data="menu_notificacoes")
            ]])
        )
    else:
        await _enviar_ou_editar_mensagem(
            context, user_id, TIPO_RESULTADO,
            "❌ *Erro ao desativar notificações.*\n\nTente novamente mais tarde."
        )


# ============================================
# PROMOVER MEMBRO (COMUM -> SECRETÁRIO)
# ============================================

async def promover_inicio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Inicia promoção de membro comum para secretário."""
    user_id = update.effective_user.id
    
    if get_nivel(user_id) != "3":
        await _enviar_ou_editar_mensagem(
            context, user_id, TIPO_RESULTADO,
            "Apenas administradores podem promover membros."
        )
        return ConversationHandler.END

    membros = listar_membros()
    if not membros:
        await _enviar_ou_editar_mensagem(
            context, user_id, TIPO_RESULTADO,
            "Nenhum membro cadastrado."
        )
        return ConversationHandler.END

    botoes = []
    for membro in membros:
        nivel = str(membro.get("Nivel", "1")).strip()
        if nivel == "1":
            nome = membro.get("Nome", "Sem nome")
            telegram_id = membro.get("Telegram ID")
            try:
                tid = int(float(telegram_id))
                botoes.append([InlineKeyboardButton(nome, callback_data=f"promover_{tid}")])
            except:
                continue

    if not botoes:
        await _enviar_ou_editar_mensagem(
            context, user_id, TIPO_RESULTADO,
            "Não há membros comuns para promover."
        )
        return ConversationHandler.END

    botoes.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancelar_promocao")])
    teclado = InlineKeyboardMarkup(botoes)

    await navegar_para(
        update, context,
        "Admin > Promover Secretário",
        "Selecione o membro que deseja promover a **secretário**:",
        teclado
    )
    return 1  # SELECIONAR_MEMBRO


async def selecionar_membro_promover(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Seleciona membro para promoção."""
    query = update.callback_query
    data = query.data
    
    if data == "cancelar_promocao":
        await _enviar_ou_editar_mensagem(
            context, update.effective_user.id, TIPO_RESULTADO,
            "Operação cancelada."
        )
        return ConversationHandler.END

    try:
        telegram_id = int(data.split("_")[1])
    except:
        await _enviar_ou_editar_mensagem(
            context, update.effective_user.id, TIPO_RESULTADO,
            "Erro ao processar seleção."
        )
        return ConversationHandler.END

    context.user_data["promover_telegram_id"] = telegram_id
    membro = buscar_membro(telegram_id)

    if not membro:
        await _enviar_ou_editar_mensagem(
            context, update.effective_user.id, TIPO_RESULTADO,
            "Membro não encontrado."
        )
        return ConversationHandler.END

    teclado = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Sim, promover", callback_data="confirmar_promover")],
        [InlineKeyboardButton("❌ Não, cancelar", callback_data="cancelar_promocao")]
    ])

    await navegar_para(
        update, context,
        "Admin > Promover Secretário > Confirmar",
        f"Confirmar promoção de *{membro.get('Nome')}* para secretário?",
        teclado
    )
    return 2  # CONFIRMAR_PROMOCAO


async def confirmar_promover(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Confirma promoção e atualiza o cargo."""
    query = update.callback_query
    user_id = update.effective_user.id
    
    if query.data == "cancelar_promocao":
        await _enviar_ou_editar_mensagem(
            context, user_id, TIPO_RESULTADO,
            "Operação cancelada."
        )
        return ConversationHandler.END

    telegram_id = context.user_data.get("promover_telegram_id")
    if not telegram_id:
        await _enviar_ou_editar_mensagem(
            context, user_id, TIPO_RESULTADO,
            "Erro: dados não encontrados."
        )
        return ConversationHandler.END

    if atualizar_nivel_membro(telegram_id, "2"):
        atualizar_membro(telegram_id, {"Cargo": "Secretário"}, preservar_nivel=True)
        
        # Atualiza o menu do usuário promovido para refletir a mudança de nível
        membro_promovido = buscar_membro(telegram_id)
        if membro_promovido:
            await criar_estrutura_inicial(context, telegram_id, membro_promovido)
        
        await navegar_para(
            update, context,
            "Admin > Promover Secretário",
            "✅ Membro promovido a secretário com sucesso!",
            InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Voltar", callback_data="area_admin")
            ]])
        )
    else:
        await _enviar_ou_editar_mensagem(
            context, user_id, TIPO_RESULTADO,
            "❌ Erro ao promover membro."
        )

    context.user_data.pop("promover_telegram_id", None)
    return ConversationHandler.END


# ============================================
# REBAIXAR MEMBRO (SECRETÁRIO -> COMUM)
# ============================================

async def rebaixar_inicio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Inicia rebaixamento de secretário para comum."""
    user_id = update.effective_user.id
    
    if get_nivel(user_id) != "3":
        await _enviar_ou_editar_mensagem(
            context, user_id, TIPO_RESULTADO,
            "Apenas administradores podem rebaixar membros."
        )
        return ConversationHandler.END

    membros = listar_membros()
    if not membros:
        await _enviar_ou_editar_mensagem(
            context, user_id, TIPO_RESULTADO,
            "Nenhum membro cadastrado."
        )
        return ConversationHandler.END

    botoes = []
    for membro in membros:
        nivel = str(membro.get("Nivel", "1")).strip()
        if nivel == "2":
            nome = membro.get("Nome", "Sem nome")
            telegram_id = membro.get("Telegram ID")
            try:
                tid = int(float(telegram_id))
                botoes.append([InlineKeyboardButton(nome, callback_data=f"rebaixar_{tid}")])
            except:
                continue

    if not botoes:
        await _enviar_ou_editar_mensagem(
            context, user_id, TIPO_RESULTADO,
            "Não há secretários para rebaixar."
        )
        return ConversationHandler.END

    botoes.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancelar_rebaixamento")])
    teclado = InlineKeyboardMarkup(botoes)

    await navegar_para(
        update, context,
        "Admin > Rebaixar Secretário",
        "Selecione o secretário que deseja rebaixar a **comum**:",
        teclado
    )
    return 1  # SELECIONAR_MEMBRO


async def selecionar_membro_rebaixar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Seleciona membro para rebaixamento."""
    query = update.callback_query
    data = query.data
    
    if data == "cancelar_rebaixamento":
        await _enviar_ou_editar_mensagem(
            context, update.effective_user.id, TIPO_RESULTADO,
            "Operação cancelada."
        )
        return ConversationHandler.END

    try:
        telegram_id = int(data.split("_")[1])
    except:
        await _enviar_ou_editar_mensagem(
            context, update.effective_user.id, TIPO_RESULTADO,
            "Erro ao processar seleção."
        )
        return ConversationHandler.END

    context.user_data["rebaixar_telegram_id"] = telegram_id
    membro = buscar_membro(telegram_id)

    if not membro:
        await _enviar_ou_editar_mensagem(
            context, update.effective_user.id, TIPO_RESULTADO,
            "Membro não encontrado."
        )
        return ConversationHandler.END

    teclado = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Sim, rebaixar", callback_data="confirmar_rebaixar")],
        [InlineKeyboardButton("❌ Não, cancelar", callback_data="cancelar_rebaixamento")]
    ])

    await navegar_para(
        update, context,
        "Admin > Rebaixar Secretário > Confirmar",
        f"Confirmar rebaixamento de *{membro.get('Nome')}* para comum?",
        teclado
    )
    return 2  # CONFIRMAR_REBAIXAMENTO


async def confirmar_rebaixar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Confirma rebaixamento e limpa o cargo."""
    query = update.callback_query
    user_id = update.effective_user.id
    
    if query.data == "cancelar_rebaixamento":
        await _enviar_ou_editar_mensagem(
            context, user_id, TIPO_RESULTADO,
            "Operação cancelada."
        )
        return ConversationHandler.END

    telegram_id = context.user_data.get("rebaixar_telegram_id")
    if not telegram_id:
        await _enviar_ou_editar_mensagem(
            context, user_id, TIPO_RESULTADO,
            "Erro: dados não encontrados."
        )
        return ConversationHandler.END

    if atualizar_nivel_membro(telegram_id, "1"):
        atualizar_membro(telegram_id, {"Cargo": ""}, preservar_nivel=True)
        
        # Atualiza o menu do usuário rebaixado para refletir a mudança de nível
        membro_rebaixado = buscar_membro(telegram_id)
        if membro_rebaixado:
            await criar_estrutura_inicial(context, telegram_id, membro_rebaixado)
        
        await navegar_para(
            update, context,
            "Admin > Rebaixar Secretário",
            "✅ Secretário rebaixado a comum com sucesso!",
            InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Voltar", callback_data="area_admin")
            ]])
        )
    else:
        await _enviar_ou_editar_mensagem(
            context, user_id, TIPO_RESULTADO,
            "❌ Erro ao rebaixar membro."
        )

    context.user_data.pop("rebaixar_telegram_id", None)
    return ConversationHandler.END


# ============================================
# VER TODOS OS MEMBROS
# ============================================

async def ver_todos_membros(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lista todos os membros para o administrador com paginação."""
    user_id = update.effective_user.id
    
    if get_nivel(user_id) != "3":
        await _enviar_ou_editar_mensagem(
            context, user_id, TIPO_RESULTADO,
            "⛔ Apenas administradores podem ver todos os membros."
        )
        return

    membros = listar_membros()
    if not membros:
        await _enviar_ou_editar_mensagem(
            context, user_id, TIPO_RESULTADO,
            "Nenhum membro cadastrado."
        )
        return

    # Paginação: 15 membros por página
    PAGE_SIZE = 15
    page = max(0, context.user_data.get("membros_page", 0))  # Garante que page >= 0
    
    start = page * PAGE_SIZE
    end = (page + 1) * PAGE_SIZE
    
    # Valida se a página tem membros
    if start >= len(membros):
        # Página inválida, volta para página 0
        context.user_data["membros_page"] = 0
        page = 0
        start = 0
        end = PAGE_SIZE
    
    pagina = membros[start:end]
    total_pages = (len(membros) + PAGE_SIZE - 1) // PAGE_SIZE
    
    botoes = []
    for membro in pagina:
        nome = membro.get("Nome", "Sem nome")
        nivel = membro.get("Nivel", "1")
        cargo = membro.get("Cargo", "")
        nivel_texto = {"1": "👤", "2": "🔰", "3": "⚜️"}.get(str(nivel), "👤")

        try:
            tid = int(float(membro.get("Telegram ID")))
        except Exception:
            continue
        
        if cargo:
            texto_botao = f"{nivel_texto} {nome} - {cargo}"
        else:
            texto_botao = f"{nivel_texto} {nome}"
        
        # Limitar tamanho do botão
        if len(texto_botao) > 30:
            texto_botao = texto_botao[:27] + "..."
        
        botoes.append([
            InlineKeyboardButton(
                texto_botao,
                callback_data=f"editar_membro_selecionar|{tid}",
            )
        ])
    
    # Botões de navegação
    botoes_nav = []
    if page > 0:
        botoes_nav.append(InlineKeyboardButton("◀️ Anterior", callback_data="membros_page_prev"))
    if page < total_pages - 1:
        botoes_nav.append(InlineKeyboardButton("Próximo ▶️", callback_data="membros_page_next"))
    
    if botoes_nav:
        botoes.append(botoes_nav)
    
    botoes.append([InlineKeyboardButton("🔙 Voltar", callback_data="area_admin")])
    
    texto = f"*Membros cadastrados (Página {page + 1}/{total_pages}):*\n\nSelecione um membro para editar."

    await navegar_para(
        update, context,
        "Admin > Membros",
        texto,
        InlineKeyboardMarkup(botoes)
    )


# ============================================
# EDIÇÃO DE MEMBRO (CONVERSATION HANDLER)
# ============================================

async def editar_membro_inicio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Inicia o processo de edição de um membro."""
    user_id = update.effective_user.id
    nivel = get_nivel(user_id)

    if nivel not in ["2", "3"]:
        await _enviar_ou_editar_mensagem(
            context, user_id, TIPO_RESULTADO,
            "⛔ Você não tem permissão para editar membros."
        )
        return ConversationHandler.END

    membros = listar_membros()
    if not membros:
        await _enviar_ou_editar_mensagem(
            context, user_id, TIPO_RESULTADO,
            "Nenhum membro cadastrado."
        )
        return ConversationHandler.END

    # Para secretário (nível 2): filtrar apenas membros da própria loja
    membros_da_loja_ids = None
    if nivel == "2":
        membros_da_loja_ids = _obter_ids_membros_da_loja(user_id)

    botoes = []
    for membro in membros:
        membro_id = membro.get("Telegram ID")
        membro_nivel = str(membro.get("Nivel", "1")).strip()
        nome = membro.get("Nome", "Sem nome")
        cargo = membro.get("Cargo", "")

        try:
            tid = int(float(membro_id))
        except:
            continue

        if nivel == "2" and membro_nivel != "1":
            continue

        # Secretário: restringir por escopo de loja
        if nivel == "2" and membros_da_loja_ids is not None:
            if tid not in membros_da_loja_ids:
                continue

        texto_botao = f"{nome} (Nível {membro_nivel})"
        if cargo:
            texto_botao = f"{nome} - {cargo} (Nível {membro_nivel})"

        botoes.append([InlineKeyboardButton(
            texto_botao,
            callback_data=f"editar_membro_selecionar|{tid}"
        )])

    if not botoes:
        await navegar_para(
            update, context,
            "Admin > Editar Membro",
            "Nenhum membro disponível para edição." if nivel == "2" else "Nenhum membro cadastrado.",
            InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Voltar", callback_data="area_admin" if nivel == "3" else "area_secretario")
            ]])
        )
        return ConversationHandler.END

    botoes.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancelar_edicao")])
    teclado = InlineKeyboardMarkup(botoes)

    await navegar_para(
        update, context,
        "Admin > Editar Membro",
        "Selecione o membro que deseja editar:",
        teclado
    )
    return SELECIONAR_MEMBRO


async def selecionar_membro_para_editar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Usuário selecionou um membro para editar."""
    query = update.callback_query
    data = query.data
    
    if data == "cancelar_edicao":
        await _enviar_ou_editar_mensagem(
            context, update.effective_user.id, TIPO_RESULTADO,
            "Operação cancelada."
        )
        return ConversationHandler.END

    try:
        telegram_id = int(data.split("|")[1])
    except:
        await _enviar_ou_editar_mensagem(
            context, update.effective_user.id, TIPO_RESULTADO,
            "Erro ao processar seleção."
        )
        return ConversationHandler.END

    membro = buscar_membro(telegram_id)

    if not membro:
        await _enviar_ou_editar_mensagem(
            context, update.effective_user.id, TIPO_RESULTADO,
            "Membro não encontrado."
        )
        return ConversationHandler.END

    context.user_data["editando_membro_id"] = telegram_id
    context.user_data["editando_membro_dados"] = membro

    nivel_usuario = get_nivel(update.effective_user.id)

    botoes = []
    for campo_id, campo_info in CAMPOS_EDITAVEIS.items():
        if int(nivel_usuario) < int(campo_info["nivel_minimo"]):
            continue

        valor_atual = membro.get(campo_info["chave"], "")
        botoes.append([InlineKeyboardButton(
            f"✏️ {campo_info['nome']}: {str(valor_atual)[:30]}",
            callback_data=f"editar_campo_membro|{campo_id}"
        )])

    if nivel_usuario == "3":
        botoes.append([InlineKeyboardButton(
            "🗑️ Excluir membro",
            callback_data=f"excluir_membro|{telegram_id}"
        )])

    botoes.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancelar_edicao")])
    teclado = InlineKeyboardMarkup(botoes)

    titulo = f"Admin > Editar > {membro.get('Nome')}"
    mensagem = f"Editando *{membro.get('Nome')}*\n\nSelecione o campo que deseja alterar:"

    await navegar_para(
        update, context,
        titulo,
        mensagem,
        teclado
    )
    return SELECIONAR_CAMPO


async def selecionar_campo_membro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Usuário selecionou um campo para editar."""
    query = update.callback_query
    data = query.data
    
    if data == "cancelar_edicao":
        await _enviar_ou_editar_mensagem(
            context, update.effective_user.id, TIPO_RESULTADO,
            "Operação cancelada."
        )
        return ConversationHandler.END

    if data.startswith("excluir_membro|"):
        if get_nivel(update.effective_user.id) != "3":
            await _enviar_ou_editar_mensagem(
                context, update.effective_user.id, TIPO_RESULTADO,
                "⛔ Apenas administradores podem excluir membros."
            )
            return ConversationHandler.END

        try:
            telegram_id = int(data.split("|")[1])
        except Exception:
            await _enviar_ou_editar_mensagem(
                context, update.effective_user.id, TIPO_RESULTADO,
                "Erro ao processar exclusão."
            )
            return ConversationHandler.END

        if telegram_id == update.effective_user.id:
            await _enviar_ou_editar_mensagem(
                context, update.effective_user.id, TIPO_RESULTADO,
                "⛔ Regra de segurança: não é permitido excluir o próprio administrador."
            )
            return SELECIONAR_CAMPO

        membro = buscar_membro(telegram_id)
        if not membro:
            await _enviar_ou_editar_mensagem(
                context, update.effective_user.id, TIPO_RESULTADO,
                "Membro não encontrado para exclusão."
            )
            return ConversationHandler.END

        nome = membro.get("Nome") or "este membro"
        teclado = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Confirmar exclusão", callback_data=f"confirmar_excluir_membro|{telegram_id}")],
            [InlineKeyboardButton("↩️ Voltar", callback_data=f"cancelar_excluir_membro|{telegram_id}")],
        ])
        await navegar_para(
            update, context,
            "Admin > Editar > Excluir",
            (
                f"⚠️ *Confirma a exclusão de {nome}?*\n\n"
                "A exclusão é lógica: o cadastro será marcado como *Inativo*.\n"
                "Se a base não suportar esse campo, o cadastro será removido da tabela."
            ),
            teclado
        )
        return SELECIONAR_CAMPO

    if data.startswith("cancelar_excluir_membro|"):
        membro = context.user_data.get("editando_membro_dados", {})
        nome = membro.get("Nome") or "Membro"
        nivel_usuario = get_nivel(update.effective_user.id)
        telegram_id = context.user_data.get("editando_membro_id")

        botoes = []
        for campo_id, campo_info in CAMPOS_EDITAVEIS.items():
            if int(nivel_usuario) < int(campo_info["nivel_minimo"]):
                continue
            valor_atual = membro.get(campo_info["chave"], "")
            botoes.append([InlineKeyboardButton(
                f"✏️ {campo_info['nome']}: {str(valor_atual)[:30]}",
                callback_data=f"editar_campo_membro|{campo_id}"
            )])

        if nivel_usuario == "3" and telegram_id:
            botoes.append([InlineKeyboardButton(
                "🗑️ Excluir membro",
                callback_data=f"excluir_membro|{telegram_id}"
            )])

        botoes.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancelar_edicao")])

        await navegar_para(
            update, context,
            f"Admin > Editar > {nome}",
            f"Editando *{nome}*\n\nSelecione o campo que deseja alterar:",
            InlineKeyboardMarkup(botoes)
        )
        return SELECIONAR_CAMPO

    if data.startswith("confirmar_excluir_membro|"):
        if get_nivel(update.effective_user.id) != "3":
            await _enviar_ou_editar_mensagem(
                context, update.effective_user.id, TIPO_RESULTADO,
                "⛔ Apenas administradores podem excluir membros."
            )
            return ConversationHandler.END

        try:
            telegram_id = int(data.split("|")[1])
        except Exception:
            await _enviar_ou_editar_mensagem(
                context, update.effective_user.id, TIPO_RESULTADO,
                "Erro ao confirmar exclusão."
            )
            return ConversationHandler.END

        if telegram_id == update.effective_user.id:
            await _enviar_ou_editar_mensagem(
                context, update.effective_user.id, TIPO_RESULTADO,
                "⛔ Regra de segurança: não é permitido excluir o próprio administrador."
            )
            return SELECIONAR_CAMPO

        sucesso = atualizar_membro(telegram_id, {"Status": "Inativo"}, preservar_nivel=True)
        if sucesso:
            await _enviar_ou_editar_mensagem(
                context, update.effective_user.id, TIPO_RESULTADO,
                "✅ Membro excluído com sucesso (status alterado para Inativo)."
            )
        else:
            sucesso_fallback = excluir_membro(telegram_id)
            if sucesso_fallback:
                await _enviar_ou_editar_mensagem(
                    context, update.effective_user.id, TIPO_RESULTADO,
                    "✅ Membro excluído com sucesso (remoção direta aplicada por compatibilidade do banco)."
                )
            else:
                await _enviar_ou_editar_mensagem(
                    context, update.effective_user.id, TIPO_RESULTADO,
                    "❌ Não foi possível excluir o membro no momento."
                )

        context.user_data.pop("editando_membro_id", None)
        context.user_data.pop("editando_membro_dados", None)
        context.user_data.pop("editando_campo", None)
        return ConversationHandler.END

    campo_id = data.split("|")[1]
    campo_info = CAMPOS_EDITAVEIS.get(campo_id)

    if not campo_info:
        await _enviar_ou_editar_mensagem(
            context, update.effective_user.id, TIPO_RESULTADO,
            "Campo inválido."
        )
        return ConversationHandler.END

    context.user_data["editando_campo"] = campo_id
    membro = context.user_data.get("editando_membro_dados", {})
    valor_atual = membro.get(campo_info["chave"], "")

    titulo = f"Admin > Editar > {campo_info['nome']}"
    mensagem = (
        f"✏️ *Editando {campo_info['nome']}*\n\n"
        f"Valor atual: {valor_atual}\n\n"
        f"Digite o novo valor (ou /cancelar para desistir):"
    )

    await navegar_para(
        update, context,
        titulo,
        mensagem,
        None
    )
    return NOVO_VALOR


async def receber_novo_valor_membro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recebe o novo valor e atualiza o membro."""
    novo_valor = update.message.text.strip()
    campo_id = context.user_data.get("editando_campo")
    campo_info = CAMPOS_EDITAVEIS.get(campo_id)
    telegram_id = context.user_data.get("editando_membro_id")

    if not campo_info or not telegram_id:
        await update.message.reply_text("Erro: dados não encontrados. Tente novamente.")
        return ConversationHandler.END

    if campo_id == "nivel" and novo_valor not in ("1", "2", "3"):
        await update.message.reply_text("❌ Nível inválido. Use 1, 2 ou 3.")
        return NOVO_VALOR

    sucesso = atualizar_membro(telegram_id, {campo_info["chave"]: novo_valor}, preservar_nivel=(campo_id != "nivel"))

    if sucesso:
        # Se o campo editado foi o nível, atualiza o menu do usuário afetado
        if campo_id == "nivel":
            membro_editado = buscar_membro(telegram_id)
            if membro_editado:
                await criar_estrutura_inicial(context, telegram_id, membro_editado)
        
        await update.message.reply_text(
            f"✅ {campo_info['nome']} atualizado com sucesso!\n\n"
            f"Use o menu acima para continuar."
        )
    else:
        await update.message.reply_text("❌ Erro ao atualizar o campo. Tente novamente mais tarde.")

    context.user_data.pop("editando_membro_id", None)
    context.user_data.pop("editando_membro_dados", None)
    context.user_data.pop("editando_campo", None)

    return ConversationHandler.END


async def cancelar_edicao_membro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancela o processo de edição."""
    if update.callback_query:
        await update.callback_query.answer()
        await _enviar_ou_editar_mensagem(
            context,
            update.effective_user.id,
            TIPO_RESULTADO,
            "Edição cancelada.",
        )
    elif update.message:
        await update.message.reply_text("Edição cancelada.")

    context.user_data.pop("editando_membro_id", None)
    context.user_data.pop("editando_membro_dados", None)
    context.user_data.pop("editando_campo", None)
    return ConversationHandler.END


# ============================================
# VER CONFIRMADOS POR EVENTO (SECRETÁRIO/ADMIN)
# ============================================

async def ver_confirmados_secretario(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Lista eventos (seu ou todos, conforme nível) e permite
    selecionar um para visualizar a lista de confirmados.
    
    Para secretários (nível 2): mostra apenas seus eventos.
    Para administradores (nível 3): mostra todos os eventos.
    """
    from src.eventos import normalizar_id_evento, _encode_cb, _eventos_ordenados
    from datetime import datetime

    user_id = update.effective_user.id
    nivel = get_nivel(user_id)

    if nivel not in ["2", "3"]:
        await _enviar_ou_editar_mensagem(
            context, user_id, TIPO_RESULTADO,
            "⛔ Apenas secretários e administradores podem acessar esta função."
        )
        return

    eventos = listar_eventos() or []

    if nivel == "3":
        # Admin: todos os eventos ativos
        eventos_filtrados = [ev for ev in eventos if str(ev.get("Status", "")).lower() in ("ativo", "")]
        titulo = "👥 *Confirmados por Evento (Admin)*"
    else:
        # Secretário: apenas seus eventos
        eventos_filtrados = [
            ev for ev in eventos 
            if obter_secretario_responsavel_evento(ev) == int(user_id)
        ]
        titulo = "👥 *Confirmados por Evento*"

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
            [InlineKeyboardButton("🔙 Voltar", callback_data="area_secretario" if nivel == "2" else "area_admin")],
        ])
        await navegar_para(
            update, context,
            "Ver Confirmados",
            f"{titulo}\n\nNenhum evento futuro encontrado.",
            teclado
        )
        return

    # Ordena eventos por data
    eventos_futuros = _eventos_ordenados(eventos_futuros)

    # Monta teclado com botões para cada evento
    botoes = []
    for ev in eventos_futuros[:40]:
        id_evento = normalizar_id_evento(ev)
        nome = ev.get("Nome da loja", "Evento")
        data = ev.get("Data do evento", "")
        hora = ev.get("Hora", "")
        numero = ev.get("Número da loja", "")

        numero_fmt = f" {numero}" if numero else ""
        hora_fmt = f" • {hora}" if hora else ""
        
        label = f"📅 {data}{hora_fmt} • 🏛 {nome}{numero_fmt}"
        botoes.append([InlineKeyboardButton(
            label,
            callback_data=f"ver_confirmados|{_encode_cb(id_evento)}"
        )])

    botoes.append([InlineKeyboardButton(
        "🔙 Voltar",
        callback_data="area_secretario" if nivel == "2" else "area_admin"
    )])

    await navegar_para(
        update, context,
        "Ver Confirmados",
        f"{titulo}\n\nSelecione um evento para ver a lista de irmãos confirmados:",
        InlineKeyboardMarkup(botoes)
    )


async def membros_pagina_anterior(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Vai para a página anterior da lista de membros."""
    page = context.user_data.get("membros_page", 0)
    if page > 0:
        context.user_data["membros_page"] = page - 1
    await ver_todos_membros(update, context)


async def membros_pagina_proxima(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Vai para a próxima página da lista de membros."""
    page = context.user_data.get("membros_page", 0)
    # Incrementa a página sem recalcular total_pages para evitar chamadas desnecessárias
    context.user_data["membros_page"] = page + 1
    # ver_todos_membros fará a validação se a página existe
    await ver_todos_membros(update, context)


# ============================================
# CONVERSATION HANDLERS
# ============================================

promover_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(promover_inicio, pattern="^admin_promover$")],
    states={
        1: [CallbackQueryHandler(selecionar_membro_promover, pattern="^(promover_|cancelar_promocao)")],
        2: [CallbackQueryHandler(confirmar_promover, pattern="^(confirmar_promover|cancelar_promocao)")],
    },
    fallbacks=[CommandHandler("cancelar", cancelar_operacao)],
    name="promover_handler",
    persistent=False,
)

rebaixar_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(rebaixar_inicio, pattern="^admin_rebaixar$")],
    states={
        1: [CallbackQueryHandler(selecionar_membro_rebaixar, pattern="^(rebaixar_|cancelar_rebaixamento)")],
        2: [CallbackQueryHandler(confirmar_rebaixar, pattern="^(confirmar_rebaixar|cancelar_rebaixamento)")],
    },
    fallbacks=[CommandHandler("cancelar", cancelar_operacao)],
    name="rebaixar_handler",
    persistent=False,
)

editar_membro_handler = ConversationHandler(
    entry_points=[
        CallbackQueryHandler(editar_membro_inicio, pattern="^admin_editar_membro$"),
        CallbackQueryHandler(selecionar_membro_para_editar, pattern=r"^editar_membro_selecionar\|"),
    ],
    states={
        SELECIONAR_MEMBRO: [CallbackQueryHandler(selecionar_membro_para_editar, pattern="^(editar_membro_selecionar|cancelar_edicao)")],
        SELECIONAR_CAMPO: [
            CallbackQueryHandler(
                selecionar_campo_membro,
                pattern="^(editar_campo_membro|cancelar_edicao|excluir_membro|confirmar_excluir_membro|cancelar_excluir_membro)",
            )
        ],
        NOVO_VALOR: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_novo_valor_membro)],
    },
    fallbacks=[
        CommandHandler("cancelar", cancelar_edicao_membro),
        CallbackQueryHandler(cancelar_edicao_membro, pattern="^cancelar$"),
    ],
    name="editar_membro_handler",
    persistent=False,
)
