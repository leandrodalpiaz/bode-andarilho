# ============================================
# BODE ANDARILHO - PERFIL DO USUÁRIO
# ============================================
# 
# Este módulo gerencia a exibição do perfil do usuário
# e oferece acesso à edição do próprio cadastro.
# 
# Funcionalidades:
# - Exibição dos dados cadastrais do membro
# - Botão para acessar a edição do perfil
# - Formatação amigável das informações
# 
# ============================================

from __future__ import annotations

import logging
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from src.sheets_supabase import buscar_membro
from src.ajuda.conquistas import calcular_conquistas_membro
from src.bot import (
    navegar_para,
    _enviar_ou_editar_mensagem,
    TIPO_RESULTADO
)

logger = logging.getLogger(__name__)


# ============================================
# FUNÇÕES AUXILIARES
# ============================================

def _formatar_data_nasc(data_str: str) -> str:
    """
    Tenta formatar data de nascimento de forma amigável (DD/MM/AAAA).
    """
    if not data_str:
        return "Não informada"
    
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            dt = datetime.strptime(data_str.strip(), fmt)
            return dt.strftime("%d/%m/%Y")
        except:
            pass
    
    return data_str


# ============================================
# EXIBIÇÃO DO PERFIL
# ============================================

async def mostrar_perfil(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Exibe o perfil do usuário com opção de editar.
    
    Fluxo:
    - Se usuário não tem cadastro: oferece para iniciar cadastro
    - Se tem cadastro: mostra todos os dados formatados
    """
    user_id = update.effective_user.id
    membro = buscar_membro(user_id)

    if not membro:
        # Usuário não tem cadastro
        teclado = InlineKeyboardMarkup([
            [InlineKeyboardButton("📝 Fazer cadastro", callback_data="iniciar_cadastro")],
            [InlineKeyboardButton("🔙 Voltar ao menu", callback_data="menu_principal")],
        ])
        
        await navegar_para(
            update, context,
            "Meu Perfil",
            "👤 *Meu cadastro*\n\nVocê ainda não possui um registro ativo.\nSeus dados permanecem sempre *acobertos* por segurança.\n\nClique abaixo para iniciar:",
            teclado
        )
        return

    # Extração de dados com suporte a diferentes nomes de colunas
    nome = membro.get("Nome") or membro.get("nome") or "Não informado"
    data_nasc = _formatar_data_nasc(membro.get("Data de nascimento") or membro.get("data_nasc") or "")
    grau = membro.get("Grau") or membro.get("grau") or "Não informado"
    loja = membro.get("Loja") or membro.get("loja") or "Não informado"
    numero_loja = membro.get("Número da loja") or membro.get("numero_loja") or ""
    oriente = membro.get("Oriente") or membro.get("oriente") or "Não informado"
    potencia = membro.get("Potência") or membro.get("potencia") or "Não informado"
    vm = membro.get("Venerável Mestre") or membro.get("veneravel_mestre") or membro.get("vm") or "Não"
    nivel = str(membro.get("Nivel") or "1")

    # Texto amigável para o nível de permissão
    niveis = {"1": "Membro", "2": "Secretário", "3": "Administrador"}
    nivel_texto = niveis.get(nivel, "Membro")

    # Formatação do número da loja se existir
    numero_fmt = f" - Nº {numero_loja}" if numero_loja and str(numero_loja) not in ("0", "Não informado") else ""

    texto = (
        f"👤 *Meu Perfil*\n\n"
        f"*Nome:* {nome}\n"
        f"*Data de nascimento:* {data_nasc}\n"
        f"*Grau:* {grau}\n"
        f"*Loja:* {loja}{numero_fmt}\n"
        f"*Oriente:* {oriente}\n"
        f"*Potência:* {potencia}\n"
        f"*Venerável Mestre:* {vm}\n"
        f"*Nível de acesso:* {nivel_texto}\n"
        f"*Permissões:* consultar sessões, confirmar presença e editar seus dados.\n"
    )

    conquistas = await calcular_conquistas_membro(user_id)
    if conquistas:
        texto += "\n*🏆 Minhas Conquistas:*\n"
        texto += "\n".join(conquistas)
    else:
        texto += "\n_Você ainda não possui títulos de Andarilho._"

    teclado = InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Editar perfil", callback_data="editar_perfil")],
        [InlineKeyboardButton("🏆 Ver minhas conquistas", callback_data="mostrar_conquistas_membro")],
        [InlineKeyboardButton("🔙 Voltar ao menu", callback_data="menu_principal")],
    ])

    await navegar_para(
        update, context,
        "Meu Perfil",
        texto,
        teclado
    )
