# src/perfil.py
from __future__ import annotations

import logging
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from src.sheets import buscar_membro

logger = logging.getLogger(__name__)


async def _safe_edit(query, text: str, **kwargs):
    try:
        await query.edit_message_text(text, **kwargs)
    except Exception as e:
        if "Message is not modified" not in str(e):
            raise


def _formatar_data_nasc(data_str: str) -> str:
    """Tenta formatar data de nascimento de forma amigável."""
    if not data_str:
        return "Não informada"
    
    # Tenta vários formatos comuns
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            dt = datetime.strptime(data_str.strip(), fmt)
            return dt.strftime("%d/%m/%Y")
        except:
            pass
    
    # Se não conseguir formatar, retorna o original
    return data_str


async def mostrar_perfil(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Exibe o perfil do usuário com opção de editar."""
    query = update.callback_query
    if not query:
        return
    await query.answer()

    user_id = update.effective_user.id
    membro = buscar_membro(user_id)

    if not membro:
        teclado = InlineKeyboardMarkup([
            [InlineKeyboardButton("📝 Fazer cadastro", callback_data="iniciar_cadastro")],
            [InlineKeyboardButton("⬅️ Voltar ao menu", callback_data="menu_principal")],
        ])
        await _safe_edit(
            query,
            "👤 *Meu cadastro*\n\nVocê ainda não possui cadastro.\nClique abaixo para iniciar:",
            parse_mode="Markdown",
            reply_markup=teclado,
        )
        return

    # Extrai dados com fallbacks para diferentes nomes de coluna
    nome = membro.get("Nome") or membro.get("nome") or "Não informado"
    data_nasc = _formatar_data_nasc(membro.get("Data de nascimento") or membro.get("data_nasc") or "")
    grau = membro.get("Grau") or membro.get("grau") or "Não informado"
    loja = membro.get("Loja") or membro.get("loja") or "Não informado"
    numero_loja = membro.get("Número da loja") or membro.get("numero_loja") or ""
    oriente = membro.get("Oriente") or membro.get("oriente") or "Não informado"
    potencia = membro.get("Potência") or membro.get("potencia") or "Não informado"
    vm = membro.get("Venerável Mestre") or membro.get("veneravel_mestre") or membro.get("vm") or "Não"
    nivel = membro.get("Nivel") or "1"

    # Mapeia nível para texto
    nivel_texto = {
        "1": "Membro",
        "2": "Secretário",
        "3": "Administrador",
    }.get(nivel, "Membro")

    # Formata número da loja
    numero_fmt = f" - Nº {numero_loja}" if numero_loja and numero_loja not in ("0", "Não informado") else ""

    texto = (
        f"👤 *Meu Perfil*\n\n"
        f"*Nome:* {nome}\n"
        f"*Data de nascimento:* {data_nasc}\n"
        f"*Grau:* {grau}\n"
        f"*Loja:* {loja}{numero_fmt}\n"
        f"*Oriente:* {oriente}\n"
        f"*Potência:* {potencia}\n"
        f"*Venerável Mestre:* {vm}\n"
        f"*Nível:* {nivel_texto}\n"
    )

    teclado = InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Editar perfil", callback_data="editar_perfil")],
        [InlineKeyboardButton("⬅️ Voltar ao menu", callback_data="menu_principal")],
    ])

    await _safe_edit(query, texto, parse_mode="Markdown", reply_markup=teclado)