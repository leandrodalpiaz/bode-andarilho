# src/miniapp.py
# ============================================
# BODE ANDARILHO - TELEGRAM MINI APP
# ============================================
#
# Fornece formulÃ¡rios web para cadastro de membros, eventos e lojas,
# servidos diretamente pelo Starlette no Render.
#
# Rotas Starlette registradas em main.py:
#   GET  /webapp/cadastro_membro  <- get_cadastro_membro()
#   GET  /webapp/cadastro_evento  <- get_cadastro_evento()
#   GET  /webapp/cadastro_loja    <- get_cadastro_loja()
#   POST /api/cadastro_membro     <- api_cadastro_membro()
#   POST /api/cadastro_evento     <- api_cadastro_evento()
#   POST /api/cadastro_loja       <- api_cadastro_loja()
#   POST /api/lojas               <- api_listar_lojas()
#
# SeguranÃ§a:
#   Toda submissÃ£o inclui o initData do Telegram WebApp SDK.
#   O servidor verifica a assinatura HMAC-SHA256 antes de processar.
#   O telegram_id Ã© extraÃ­do **exclusivamente** do initData verificado,
#   nunca do corpo da requisiÃ§Ã£o.
# ============================================

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qsl, unquote

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo, Update

from src.sheets_supabase import (
    buscar_membro,
    cadastrar_membro,
    cadastrar_evento,
    atualizar_evento,
    cadastrar_loja,
    listar_lojas,
    buscar_loja_por_nome_numero,
    listar_secretarios_ativos,
)
from src.permissoes import get_nivel
from src.evento_midia import publicar_evento_no_grupo as publicar_midia_evento_no_grupo
from src.eventos import (
    montar_texto_publicacao_evento,
    montar_teclado_publicacao_evento,
    registrar_post_evento_grupo,
)
from src.potencias import (
    POTENCIAS_PRINCIPAIS,
    formatar_potencia,
    normalizar_potencia,
    potencia_requer_complemento,
    validar_potencia,
)

logger = logging.getLogger(__name__)

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# URLS DOS WEBAPPS (lidas do ambiente em import-time)
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def _webapp_base_url() -> str:
    raw = (os.getenv("RENDER_EXTERNAL_URL", "") or "").strip().rstrip("/")
    lowered = raw.lower()
    if not raw:
        return ""
    if not lowered.startswith("https://"):
        logger.warning("Mini App desativada: RENDER_EXTERNAL_URL precisa usar HTTPS. Valor atual: %s", raw)
        return ""
    if "seu-app.onrender.com" in lowered or "example.com" in lowered:
        logger.warning("Mini App desativada: RENDER_EXTERNAL_URL ainda estÃ¡ com placeholder. Valor atual: %s", raw)
        return ""
    return raw


_RENDER_URL = _webapp_base_url()
WEBAPP_URL_MEMBRO = f"{_RENDER_URL}/webapp/cadastro_membro" if _RENDER_URL else ""
WEBAPP_URL_EVENTO = f"{_RENDER_URL}/webapp/cadastro_evento" if _RENDER_URL else ""
WEBAPP_URL_LOJA   = f"{_RENDER_URL}/webapp/cadastro_loja"   if _RENDER_URL else ""

_GRUPO_PRINCIPAL_ID = os.getenv("GRUPO_PRINCIPAL_ID", "")

_RASCUNHOS_MEMBRO: Dict[int, Dict[str, Any]] = {}
_RASCUNHOS_LOJA: Dict[int, Dict[str, Any]] = {}
_RASCUNHOS_EVENTO: Dict[int, Dict[str, Any]] = {}


def _botao_editar_webapp(texto: str, url: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(texto, web_app=WebAppInfo(url=url))


def _salvar_rascunho(bucket: Dict[int, Dict[str, Any]], telegram_id: int, dados: Dict[str, Any]) -> None:
    payload = dict(dados)
    payload["_saved_at"] = datetime.now().isoformat(timespec="seconds")
    bucket[int(telegram_id)] = payload


def _obter_rascunho(bucket: Dict[int, Dict[str, Any]], telegram_id: int) -> Dict[str, Any]:
    return dict(bucket.get(int(telegram_id), {}))


def _limpar_rascunho(bucket: Dict[int, Dict[str, Any]], telegram_id: int) -> None:
    bucket.pop(int(telegram_id), None)


def _normalizar_dados_potencia(dados: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(dados)
    principal, complemento = normalizar_potencia(
        payload.get("potencia"),
        payload.get("potencia_complemento") or payload.get("potencia_outra"),
    )
    payload["potencia"] = principal
    payload["potencia_complemento"] = complemento
    payload["potencia_outra"] = complemento
    return payload


def _potencia_resumo(dados: Dict[str, Any]) -> str:
    return formatar_potencia(
        dados.get("potencia"),
        dados.get("potencia_complemento") or dados.get("potencia_outra"),
    )


def _resumo_membro_md(dados: Dict[str, Any]) -> str:
    numero_loja = _norm_text(dados.get("numero_loja") or "0")
    numero_fmt = f" - NÂº {_escape_md(numero_loja)}" if numero_loja and numero_loja != "0" else ""
    potencia = _potencia_resumo(dados)
    return (
        "ðŸ§¾ *Confirme seu cadastro*\n\n"
        f"*Nome:* {_escape_md(dados.get('nome', ''))}\n"
        f"*Data de nascimento:* {_escape_md(dados.get('data_nasc', ''))}\n"
        f"*Grau:* {_escape_md(dados.get('grau', ''))}\n"
        f"*Mestre Instalado:* {_escape_md(dados.get('mi', 'NÃ£o'))}\n"
        f"*VenerÃ¡vel Mestre:* {_escape_md(dados.get('vm', ''))}\n"
        f"*Loja:* {_escape_md(dados.get('loja', ''))}{numero_fmt}\n"
        f"*Oriente:* {_escape_md(dados.get('oriente', ''))}\n"
        f"*PotÃªncia:* {_escape_md(potencia or '')}\n"
    )



def _teclado_rascunho_membro() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("âœ… Confirmar cadastro", callback_data="draft_membro_confirmar")],
        [_botao_editar_webapp("âœï¸ Editar dados", WEBAPP_URL_MEMBRO)],
        [InlineKeyboardButton("âŒ Cancelar", callback_data="draft_membro_cancelar")],
    ])


def _resumo_loja_md(dados: Dict[str, Any]) -> str:
    responsavel = _norm_text(dados.get("secretario_responsavel_nome") or dados.get("secretario_responsavel_id"))
    linha_responsavel = f"*SecretÃ¡rio responsÃ¡vel:* {_escape_md(responsavel)}\n" if responsavel else ""
    return (
        "ðŸ›ï¸ *Confirme os dados da loja*\n\n"
        f"*Nome:* {_escape_md(dados.get('nome', ''))}\n"
        f"*NÃºmero:* {_escape_md(dados.get('numero', '0'))}\n"
        f"*Oriente:* {_escape_md(dados.get('oriente', ''))}\n"
        f"*Rito:* {_escape_md(dados.get('rito', ''))}\n"
        f"*PotÃªncia:* {_escape_md(_potencia_resumo(dados))}\n"
        f"*EndereÃ§o:* {_escape_md(dados.get('endereco', ''))}\n"
        f"{linha_responsavel}"
    )



def _teclado_rascunho_loja(dados: Dict[str, Any], nivel: str) -> InlineKeyboardMarkup:
    linhas: List[List[InlineKeyboardButton]] = []
    if str(nivel) == "3" and not _norm_text(dados.get("secretario_responsavel_id")):
        linhas.append([InlineKeyboardButton("ðŸ‘¤ Definir secretÃ¡rio responsÃ¡vel", callback_data="draft_loja_escolher_secretario")])
    else:
        linhas.append([InlineKeyboardButton("âœ… Confirmar loja", callback_data="draft_loja_confirmar")])
    linhas.append([_botao_editar_webapp("âœï¸ Editar loja", WEBAPP_URL_LOJA)])
    linhas.append([InlineKeyboardButton("âŒ Cancelar", callback_data="draft_loja_cancelar")])
    return InlineKeyboardMarkup(linhas)


def _teclado_template_loja_pos_cadastro(loja_id: str = "") -> InlineKeyboardMarkup:
    cb_upload = f"loja_template_pos|{loja_id}" if loja_id else "loja_template_menu"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("ðŸ–¼ Enviar template agora", callback_data=cb_upload)],
        [InlineKeyboardButton("â­ Usar padrÃ£o por enquanto", callback_data="loja_template_pular")],
        [InlineKeyboardButton("ðŸ›ï¸ Gerenciar lojas", callback_data="menu_lojas")],
    ])


def _json_error(mensagem: str, status_code: int = 400) -> JSONResponse:
    return JSONResponse({"ok": False, "error": mensagem}, status_code=status_code)


async def _usuario_esta_no_grupo(bot, telegram_id: int) -> bool:
    """Verifica se o usuÃ¡rio ainda participa do grupo principal configurado."""
    grupo_id = str(_GRUPO_PRINCIPAL_ID or "").strip()
    if not grupo_id or not grupo_id.lstrip("-").isdigit():
        return True
    try:
        member = await bot.get_chat_member(int(grupo_id), int(telegram_id))
        return member.status in ("member", "administrator", "creator")
    except Exception as e:
        logger.warning("Falha ao verificar membro %s no grupo principal: %s", telegram_id, e)
        return True


async def _validar_requisicao_webapp(request: Request) -> tuple[Optional[dict], Optional[int], Optional[JSONResponse]]:
    bot_token: str = request.app.state.bot_token
    try:
        body: dict = await request.json()
    except Exception:
        return None, None, _json_error("JSON invÃ¡lido.", 400)

    init_data = (body.get("init_data") or "").strip()
    user = verify_telegram_webapp_data(init_data, bot_token)
    if not user:
        return None, None, _json_error("NÃ£o autorizado.", 403)

    telegram_id = user.get("id")
    if not telegram_id:
        return None, None, _json_error("UsuÃ¡rio nÃ£o identificado.", 403)

    return body, int(telegram_id), None


def _extrair_dados_membro(body: Dict[str, Any]) -> Dict[str, Any]:
    return _normalizar_dados_potencia({
        "loja_id": _norm_text(body.get("loja_id"))[:80],
        "nome": _norm_text(body.get("nome"))[:200],
        "data_nasc": _norm_text(body.get("data_nasc"))[:10],
        "grau": _norm_text(body.get("grau"))[:50],
        "mi": _norm_text(body.get("mi") or "NÃ£o")[:10],
        "vm": _norm_text(body.get("vm"))[:10],
        "loja": _norm_text(body.get("loja"))[:200],
        "numero_loja": _norm_text(body.get("numero_loja") or "0")[:10],
        "oriente": _norm_text(body.get("oriente"))[:200],
        "potencia": _norm_text(body.get("potencia"))[:200],
        "potencia_outra": _norm_text(body.get("potencia_outra") or body.get("potencia_complemento"))[:200],
    })


def _validar_dados_membro(dados: Dict[str, Any]) -> Optional[str]:
    if not all([dados["nome"], dados["data_nasc"], dados["grau"], dados["mi"], dados["vm"], dados["loja"], dados["oriente"], dados["potencia"]]):
        return "Preencha todos os campos obrigatÃ³rios."
    try:
        datetime.strptime(dados["data_nasc"], "%d/%m/%Y")
    except ValueError:
        return "Data de nascimento invÃ¡lida. Use DD/MM/AAAA."
    if dados["grau"] not in {"Aprendiz", "Companheiro", "Mestre"}:
        return "Grau invÃ¡lido."
    if dados["mi"] not in {"Sim", "NÃ£o"}:
        return "Informe se o irmÃ£o Ã© Mestre Instalado."
    if dados["vm"] not in {"Sim", "NÃ£o"}:
        return "Informe se o irmÃ£o Ã© VenerÃ¡vel Mestre."
    if not validar_potencia(dados["potencia"], dados.get("potencia_complemento")):
        return "Informe a potÃªncia principal e o complemento."
    return None


def _payload_membro(telegram_id: int, dados: Dict[str, Any]) -> Dict[str, Any]:
    potencia, potencia_complemento = normalizar_potencia(dados.get("potencia"), dados.get("potencia_complemento"))
    return {
        "Telegram ID": str(telegram_id),
        "ID da loja": dados.get("loja_id", ""),
        "Nome": dados["nome"],
        "Data de nascimento": dados["data_nasc"],
        "Grau": dados["grau"],
        "VenerÃ¡vel Mestre": dados["vm"],
        "Mestre Instalado": dados.get("mi", "NÃ£o"),
        "Loja": dados["loja"],
        "NÃºmero da loja": dados["numero_loja"],
        "Oriente": dados["oriente"],
        "PotÃªncia": potencia,
        "PotÃªncia complemento": potencia_complemento,
        "Status": "Ativo",
        "Nivel": "1",
    }


async def api_rascunho_membro(request: Request) -> JSONResponse:
    body, telegram_id, erro = await _validar_requisicao_webapp(request)
    if erro:
        return erro
    if not await _usuario_esta_no_grupo(request.app.state.telegram_app.bot, telegram_id):
        return _json_error(
            "Seu cadastro sÃ³ pode ser concluÃ­do por quem estÃ¡ participando do grupo do Bode Andarilho no momento.",
            403,
        )
    if _norm_text((body or {}).get("action")).lower() == "get":
        return JSONResponse({"ok": True, "draft": _obter_rascunho(_RASCUNHOS_MEMBRO, telegram_id)})
    dados = _extrair_dados_membro(body or {})
    mensagem = _validar_dados_membro(dados)
    if mensagem:
        return _json_error(mensagem, 400)
    _salvar_rascunho(_RASCUNHOS_MEMBRO, telegram_id, dados)
    try:
        await _enviar_resumo_rascunho_membro(request.app.state.telegram_app.bot, telegram_id)
    except Exception as e:
        logger.warning("Falha ao enviar resumo do rascunho de membro para %s: %s", telegram_id, e)
    return JSONResponse({"ok": True, "message": "Rascunho salvo com sucesso."})


async def draft_membro_confirmar(update: Update, context) -> None:
    query = update.callback_query
    await query.answer()
    telegram_id = int(update.effective_user.id)
    if not await _usuario_esta_no_grupo(context.bot, telegram_id):
        await query.answer("O cadastro sÃ³ pode ser concluÃ­do por quem estÃ¡ no grupo no momento.", show_alert=True)
        return
    dados = _obter_rascunho(_RASCUNHOS_MEMBRO, telegram_id)
    if not dados:
        await query.answer("NÃ£o encontrei um rascunho para confirmar.", show_alert=True)
        return
    ja_existe = buscar_membro(telegram_id)
    ok = cadastrar_membro(_payload_membro(telegram_id, dados))
    if not ok:
        await query.answer("NÃ£o consegui concluir o cadastro agora.", show_alert=True)
        return
    _limpar_rascunho(_RASCUNHOS_MEMBRO, telegram_id)
    nome_esc = _escape_md(dados.get("nome", ""))
    if ja_existe:
        texto = f"âœ… *Cadastro atualizado\\!*\n\nSaudaÃ§Ãµes, Ir\\.Â·\\. {nome_esc}\\. Seus dados foram atualizados\\."
    else:
        texto = (
            f"âœ… *Cadastro realizado a contento\\!*\n\n"
            f"Bem\\-vindo ao Bode Andarilho, Ir\\.Â·\\. {nome_esc}\\!\n"
            "Use /start para acessar o Painel do Obreiro\\."
        )
    await query.edit_message_text(text=texto, parse_mode="MarkdownV2")


async def draft_membro_cancelar(update: Update, context) -> None:
    query = update.callback_query
    await query.answer()
    telegram_id = int(update.effective_user.id)
    _limpar_rascunho(_RASCUNHOS_MEMBRO, telegram_id)
    await query.edit_message_text("Tudo certo. O rascunho do cadastro foi cancelado.")


def _extrair_dados_loja(body: Dict[str, Any]) -> Dict[str, Any]:
    return _normalizar_dados_potencia({
        "nome": _norm_text(body.get("nome"))[:200],
        "numero": _norm_text(body.get("numero") or "0")[:10],
        "oriente": _norm_text(body.get("oriente"))[:200],
        "rito": _norm_text(body.get("rito"))[:200],
        "potencia": _norm_text(body.get("potencia"))[:200],
        "potencia_outra": _norm_text(body.get("potencia_outra") or body.get("potencia_complemento"))[:200],
        "endereco": _norm_text(body.get("endereco"))[:400],
    })



def _validar_dados_loja(dados: Dict[str, Any]) -> Optional[str]:
    if not all([dados["nome"], dados["oriente"], dados["rito"], dados["potencia"], dados["endereco"]]):
        return "Preencha todos os campos obrigatÃ³rios."
    if not validar_potencia(dados["potencia"], dados.get("potencia_complemento")):
        return "Informe a potÃªncia principal e o complemento."
    return None


def _payload_loja(dados: Dict[str, Any], executor_id: int) -> Dict[str, Any]:
    return {
        "nome": dados["nome"],
        "numero": dados["numero"],
        "oriente": dados["oriente"],
        "rito": dados["rito"],
        "potencia": dados["potencia"],
        "potencia_complemento": dados.get("potencia_complemento", ""),
        "endereco": dados["endereco"],
        "secretario_responsavel_id": _norm_text(dados.get("secretario_responsavel_id")) or str(executor_id),
        "secretario_responsavel_nome": _norm_text(dados.get("secretario_responsavel_nome")),
        "vinculo_atualizado_por_id": str(executor_id),
    }


async def api_rascunho_loja(request: Request) -> JSONResponse:
    body, telegram_id, erro = await _validar_requisicao_webapp(request)
    if erro:
        return erro
    if _norm_text((body or {}).get("action")).lower() == "get":
        return JSONResponse({"ok": True, "draft": _obter_rascunho(_RASCUNHOS_LOJA, telegram_id)})
    dados = _extrair_dados_loja(body or {})
    mensagem = _validar_dados_loja(dados)
    if mensagem:
        return _json_error(mensagem, 400)
    _salvar_rascunho(_RASCUNHOS_LOJA, telegram_id, dados)
    try:
        await _enviar_resumo_rascunho_loja(request.app.state.telegram_app.bot, telegram_id)
    except Exception as e:
        logger.warning("Falha ao enviar resumo do rascunho de loja para %s: %s", telegram_id, e)
    return JSONResponse({"ok": True, "message": "Rascunho salvo com sucesso."})


async def draft_loja_escolher_secretario(update: Update, context) -> None:
    query = update.callback_query
    await query.answer()
    telegram_id = int(update.effective_user.id)
    dados = _obter_rascunho(_RASCUNHOS_LOJA, telegram_id)
    if not dados:
        await query.answer("NÃ£o encontrei um rascunho de loja.", show_alert=True)
        return
    secretarios = listar_secretarios_ativos() or []
    if not secretarios:
        await query.answer("Nenhum secretÃ¡rio ativo foi encontrado.", show_alert=True)
        return
    await query.edit_message_text(
        "Escolha o secretÃ¡rio responsÃ¡vel por esta loja:",
        reply_markup=_teclado_secretarios("draft_loja_set_secretario", secretarios),
    )


async def draft_loja_set_secretario(update: Update, context) -> None:
    query = update.callback_query
    await query.answer()
    telegram_id = int(update.effective_user.id)
    dados = _obter_rascunho(_RASCUNHOS_LOJA, telegram_id)
    if not dados:
        await query.answer("NÃ£o encontrei um rascunho de loja.", show_alert=True)
        return
    _, secretario_id = (query.data or "").split("|", 1)
    secretario = next((sec for sec in (listar_secretarios_ativos() or []) if _norm_text(sec.get("telegram_id")) == secretario_id), None)
    dados["secretario_responsavel_id"] = secretario_id
    dados["secretario_responsavel_nome"] = _norm_text((secretario or {}).get("nome")) or secretario_id
    _salvar_rascunho(_RASCUNHOS_LOJA, telegram_id, dados)
    nivel = str(get_nivel(telegram_id))
    await query.edit_message_text(
        text=_resumo_loja_md(dados),
        parse_mode="MarkdownV2",
        reply_markup=_teclado_rascunho_loja(dados, nivel),
    )


async def draft_loja_set_secretario_cancelar(update: Update, context) -> None:
    query = update.callback_query
    await query.answer()
    telegram_id = int(update.effective_user.id)
    dados = _obter_rascunho(_RASCUNHOS_LOJA, telegram_id)
    if not dados:
        await query.edit_message_text("Tudo certo. A seleÃ§Ã£o do secretÃ¡rio foi cancelada.")
        return
    nivel = str(get_nivel(telegram_id))
    await query.edit_message_text(
        text=_resumo_loja_md(dados),
        parse_mode="MarkdownV2",
        reply_markup=_teclado_rascunho_loja(dados, nivel),
    )


async def draft_loja_confirmar(update: Update, context) -> None:
    query = update.callback_query
    await query.answer()
    telegram_id = int(update.effective_user.id)
    dados = _obter_rascunho(_RASCUNHOS_LOJA, telegram_id)
    if not dados:
        await query.answer("NÃ£o encontrei um rascunho de loja.", show_alert=True)
        return
    nivel = str(get_nivel(telegram_id))
    if nivel == "3" and not _norm_text(dados.get("secretario_responsavel_id")):
        await query.answer("Defina primeiro o secretÃ¡rio responsÃ¡vel.", show_alert=True)
        return
    ok = cadastrar_loja(telegram_id, _payload_loja(dados, telegram_id))
    if not ok:
        await query.answer("NÃ£o consegui registrar a loja agora.", show_alert=True)
        return
    _limpar_rascunho(_RASCUNHOS_LOJA, telegram_id)
    loja = buscar_loja_por_nome_numero(dados.get("nome", ""), dados.get("numero", ""))
    loja_id = _norm_text((loja or {}).get("ID") or (loja or {}).get("id"))
    nome_esc = _escape_md(dados.get("nome", ""))
    await query.edit_message_text(
        text=(
            f"? *Loja cadastrada\\!*\n\n"
            f"?? *{nome_esc}* foi registrada com sucesso e j? pode ser usada nos pr?ximos eventos\\.\n\n"
            "Deseja enviar o template visual oficial desta Loja agora?"
        ),
        parse_mode="MarkdownV2",
        reply_markup=_teclado_template_loja_pos_cadastro(loja_id),
    )


async def draft_loja_cancelar(update: Update, context) -> None:
    query = update.callback_query
    await query.answer()
    telegram_id = int(update.effective_user.id)
    _limpar_rascunho(_RASCUNHOS_LOJA, telegram_id)
    await query.edit_message_text("Tudo certo. O rascunho da loja foi cancelado.")


def _extrair_dados_evento(body: Dict[str, Any]) -> Dict[str, Any]:
    return _normalizar_dados_potencia({
        "loja_id": _norm_text(body.get("loja_id"))[:80],
        "data": _norm_text(body.get("data"))[:10],
        "horario": _norm_text(body.get("horario"))[:5],
        "grau": _norm_text(body.get("grau"))[:50],
        "grau_outro": _norm_text(body.get("grau_outro"))[:100],
        "tipo_sessao": _norm_text(body.get("tipo_sessao"))[:200],
        "traje": _norm_text(body.get("traje"))[:200],
        "traje_outro": _norm_text(body.get("traje_outro"))[:200],
        "agape": _norm_text(body.get("agape"))[:50],
        "observacoes": _norm_text(body.get("observacoes"))[:500],
        "nome_loja": _norm_text(body.get("nome_loja"))[:200],
        "numero_loja": _norm_text(body.get("numero_loja") or "0")[:10],
        "oriente": _norm_text(body.get("oriente"))[:200],
        "rito": _norm_text(body.get("rito"))[:200],
        "rito_outro": _norm_text(body.get("rito_outro"))[:200],
        "potencia": _norm_text(body.get("potencia"))[:200],
        "potencia_outra": _norm_text(body.get("potencia_outra") or body.get("potencia_complemento"))[:200],
        "endereco": _norm_text(body.get("endereco"))[:400],
    })



def _validar_dados_evento(dados: Dict[str, Any]) -> Optional[str]:
    obrigatorios = [
        dados["data"], dados["horario"], dados["grau"], dados["tipo_sessao"],
        dados["traje"], dados["agape"], dados["nome_loja"], dados["oriente"],
        dados["rito"], dados["potencia"], dados["endereco"],
    ]
    if not all(obrigatorios):
        return "Preencha todos os campos obrigatÃ³rios."
    dt = _parse_data_ddmmyyyy(dados["data"])
    if not dt:
        return "Data invÃ¡lida. Use DD/MM/AAAA."
    if dt < datetime.now().replace(hour=0, minute=0, second=0, microsecond=0):
        return "A data nÃ£o pode ser no passado."
    if dados["grau"] not in {"Aprendiz", "Companheiro", "Mestre", "Outro"}:
        return "Grau da sessÃ£o invÃ¡lido."
    if dados["grau"] == "Outro" and not dados["grau_outro"]:
        return "Informe o grau da sessÃ£o quando selecionar 'Outro'."
    if dados["traje"] not in {"Traje maÃ§Ã´nico", "Livre", "Outro"}:
        return "Traje invÃ¡lido."
    if dados["traje"] == "Outro" and not dados["traje_outro"]:
        return "Informe o traje quando selecionar 'Outro'."
    if dados["rito"] not in {"REAA", "Schroeder", "Adonhiramita", "Brasileiro", "York", "Moderno", "EscocÃªs Retificado", "Memphis-Misraim", "Outro"}:
        return "Rito invÃ¡lido."
    if dados["rito"] == "Outro" and not dados["rito_outro"]:
        return "Informe o rito quando selecionar 'Outro'."
    if not validar_potencia(dados["potencia"], dados.get("potencia_complemento")):
        return "Informe a potÃªncia principal e o complemento."
    return None


def _payload_evento(dados: Dict[str, Any], secretario_id: str) -> Dict[str, Any]:
    dt = _parse_data_ddmmyyyy(dados["data"])
    grau = dados["grau_outro"] if dados.get("grau") == "Outro" else dados["grau"]
    traje = dados["traje_outro"] if dados.get("traje") == "Outro" else dados["traje"]
    rito = dados["rito_outro"] if dados.get("rito") == "Outro" else dados["rito"]
    potencia, potencia_complemento = normalizar_potencia(dados.get("potencia"), dados.get("potencia_complemento"))
    return {
        "ID da loja": dados.get("loja_id", ""),
        "Data do evento": dados["data"],
        "Dia da semana": dt.strftime("%A") if dt else "",
        "Hora": dados["horario"],
        "Nome da loja": dados["nome_loja"],
        "NÃºmero da loja": dados["numero_loja"],
        "Oriente": dados["oriente"],
        "Grau": grau,
        "Tipo de sessÃ£o": dados["tipo_sessao"],
        "Rito": rito,
        "PotÃªncia": potencia,
        "PotÃªncia complemento": potencia_complemento,
        "Traje obrigatÃ³rio": traje,
        "Ãgape": dados["agape"],
        "ObservaÃ§Ãµes": dados["observacoes"],
        "Telegram ID do grupo": _GRUPO_PRINCIPAL_ID,
        "Telegram ID do secretÃ¡rio": secretario_id,
        "Status": "Ativo",
        "EndereÃ§o da sessÃ£o": dados["endereco"],
        "Modo visual": "template_loja",
        "Card especial URL": "",
        "Card renderizado URL": "",
        "Card file_id Telegram": "",
        "Telegram tipo mensagem grupo": "",
    }


def _texto_publicacao_evento(dados: Dict[str, Any]) -> str:
    dt = _parse_data_ddmmyyyy(dados.get("data", ""))
    dia_semana = {
        "Monday": "segunda",
        "Tuesday": "terÃ§a",
        "Wednesday": "quarta",
        "Thursday": "quinta",
        "Friday": "sexta",
        "Saturday": "sÃ¡bado",
        "Sunday": "domingo",
    }.get(dt.strftime("%A"), "") if dt else ""
    numero_loja = _norm_text(dados.get("numero_loja") or "0")
    numero_fmt = f" {numero_loja}" if numero_loja and numero_loja != "0" else ""
    return "\n".join([
        "NOVA SESSÃƒO",
        "",
        f"{dados.get('data', '')} ({dia_semana}) â€¢ {dados.get('horario', '')}" if dia_semana else f"{dados.get('data', '')} â€¢ {dados.get('horario', '')}",
        f"Grau: {dados.get('grau', '')}",
        "",
        "LOJA",
        f"{dados.get('nome_loja', '')}{numero_fmt}",
        f"{dados.get('oriente', '')} - {dados.get('potencia', '')}",
        "",
        "SESSÃƒO",
        f"Tipo: {dados.get('tipo_sessao', '')}",
        f"Rito: {dados.get('rito', '')}",
        f"Traje: {dados.get('traje', '')}",
        f"Ãgape: {dados.get('agape', '')}",
        "",
        "ORDEM DO DIA / OBSERVAÃ‡Ã•ES",
        dados.get("observacoes") or "-",
        "",
        f"Local: {dados.get('endereco', '')}",
    ])


async def _publicar_evento_no_grupo(context, id_evento: str, evento: Dict[str, Any]) -> None:
    evento["ID Evento"] = id_evento
    msg, tipo_msg = await publicar_midia_evento_no_grupo(
        context,
        int(_GRUPO_PRINCIPAL_ID),
        evento,
        montar_texto_publicacao_evento(evento),
        montar_teclado_publicacao_evento(evento),
    )
    registrar_post_evento_grupo(id_evento, int(_GRUPO_PRINCIPAL_ID), msg.message_id)
    atualizar_evento(0, {
        "ID Evento": id_evento,
        "Telegram Message ID do grupo": str(msg.message_id),
        "Telegram tipo mensagem grupo": tipo_msg,
    })

async def api_rascunho_evento(request: Request) -> JSONResponse:
    body, telegram_id, erro = await _validar_requisicao_webapp(request)
    if erro:
        return erro
    if _norm_text((body or {}).get("action")).lower() == "get":
        return JSONResponse({"ok": True, "draft": _obter_rascunho(_RASCUNHOS_EVENTO, telegram_id)})
    dados = _extrair_dados_evento(body or {})
    mensagem = _validar_dados_evento(dados)
    if mensagem:
        return _json_error(mensagem, 400)
    _salvar_rascunho(_RASCUNHOS_EVENTO, telegram_id, dados)
    try:
        await _enviar_resumo_rascunho_evento(request.app.state.telegram_app.bot, telegram_id)
    except Exception as e:
        logger.warning("Falha ao enviar resumo do rascunho de evento para %s: %s", telegram_id, e)
    return JSONResponse({"ok": True, "message": "Rascunho salvo com sucesso."})


async def draft_evento_escolher_secretario(update: Update, context) -> None:
    query = update.callback_query
    await query.answer()
    telegram_id = int(update.effective_user.id)
    dados = _obter_rascunho(_RASCUNHOS_EVENTO, telegram_id)
    if not dados:
        await query.answer("NÃ£o encontrei um rascunho de evento.", show_alert=True)
        return
    secretarios = listar_secretarios_ativos() or []
    if not secretarios:
        await query.answer("Nenhum secretÃ¡rio ativo foi encontrado.", show_alert=True)
        return
    await query.edit_message_text(
        "Escolha o secretÃ¡rio responsÃ¡vel por esta sessÃ£o:",
        reply_markup=_teclado_secretarios("draft_evento_set_secretario", secretarios),
    )


async def draft_evento_set_secretario(update: Update, context) -> None:
    query = update.callback_query
    await query.answer()
    telegram_id = int(update.effective_user.id)
    dados = _obter_rascunho(_RASCUNHOS_EVENTO, telegram_id)
    if not dados:
        await query.answer("NÃ£o encontrei um rascunho de evento.", show_alert=True)
        return
    _, secretario_id = (query.data or "").split("|", 1)
    secretario = next((sec for sec in (listar_secretarios_ativos() or []) if _norm_text(sec.get("telegram_id")) == secretario_id), None)
    dados["secretario_responsavel_id"] = secretario_id
    dados["secretario_responsavel_nome"] = _norm_text((secretario or {}).get("nome")) or secretario_id
    _salvar_rascunho(_RASCUNHOS_EVENTO, telegram_id, dados)
    nivel = str(get_nivel(telegram_id))
    lojas_existentes = listar_lojas(telegram_id, include_todas=(nivel == "3")) or []
    await query.edit_message_text(
        text=_resumo_evento_md(dados),
        parse_mode="MarkdownV2",
        reply_markup=_teclado_rascunho_evento(dados, nivel, lojas_existentes),
    )


async def draft_evento_set_secretario_cancelar(update: Update, context) -> None:
    query = update.callback_query
    await query.answer()
    telegram_id = int(update.effective_user.id)
    dados = _obter_rascunho(_RASCUNHOS_EVENTO, telegram_id)
    if not dados:
        await query.edit_message_text("Tudo certo. A escolha do secretÃ¡rio foi cancelada.")
        return
    nivel = str(get_nivel(telegram_id))
    lojas_existentes = listar_lojas(telegram_id, include_todas=(nivel == "3")) or []
    await query.edit_message_text(
        text=_resumo_evento_md(dados),
        parse_mode="MarkdownV2",
        reply_markup=_teclado_rascunho_evento(dados, nivel, lojas_existentes),
    )


async def _confirmar_evento(update: Update, context, salvar_loja: bool) -> None:
    query = update.callback_query
    telegram_id = int(update.effective_user.id)
    dados = _obter_rascunho(_RASCUNHOS_EVENTO, telegram_id)
    if not dados:
        await query.answer("NÃ£o encontrei um rascunho de evento.", show_alert=True)
        return
    nivel = str(get_nivel(telegram_id))
    secretario_id = _norm_text(dados.get("secretario_responsavel_id")) or str(telegram_id)
    if nivel == "3" and not _norm_text(dados.get("secretario_responsavel_id")):
        await query.answer("Defina primeiro o secretÃ¡rio responsÃ¡vel.", show_alert=True)
        return
    lojas_existentes = listar_lojas(telegram_id, include_todas=(nivel == "3")) or []
    if salvar_loja and _evento_tem_loja_nova(dados, lojas_existentes):
        ok_loja = cadastrar_loja(
            telegram_id,
            {
                "nome": dados.get("nome_loja"),
                "numero": dados.get("numero_loja"),
                "oriente": dados.get("oriente"),
                "rito": dados.get("rito"),
                "potencia": dados.get("potencia"),
                "endereco": dados.get("endereco"),
                "secretario_responsavel_id": secretario_id,
                "secretario_responsavel_nome": _norm_text(dados.get("secretario_responsavel_nome")),
                "vinculo_atualizado_por_id": str(telegram_id),
            },
        )
        if not ok_loja:
            await query.answer("NÃ£o consegui salvar a loja vinculada a esta sessÃ£o.", show_alert=True)
            return
    evento = _payload_evento(dados, secretario_id)
    id_evento = cadastrar_evento(evento)
    if not id_evento:
        await query.answer("NÃ£o consegui registrar a sessÃ£o agora.", show_alert=True)
        return
    try:
        await _publicar_evento_no_grupo(context, id_evento, evento)
    except Exception as e:
        logger.warning("Falha ao publicar evento %s no grupo: %s", id_evento, e)
        await query.answer("A sessÃ£o foi salva, mas nÃ£o consegui publicar no grupo.", show_alert=True)
        return
    _limpar_rascunho(_RASCUNHOS_EVENTO, telegram_id)
    await query.edit_message_text("âœ… SessÃ£o publicada com sucesso no grupo.")


async def draft_evento_confirmar_com_loja(update: Update, context) -> None:
    query = update.callback_query
    await query.answer()
    await _confirmar_evento(update, context, salvar_loja=True)


async def draft_evento_confirmar_sem_loja(update: Update, context) -> None:
    query = update.callback_query
    await query.answer()
    await _confirmar_evento(update, context, salvar_loja=False)


async def draft_evento_cancelar(update: Update, context) -> None:
    query = update.callback_query
    await query.answer()
    telegram_id = int(update.effective_user.id)
    _limpar_rascunho(_RASCUNHOS_EVENTO, telegram_id)
    await query.edit_message_text("Tudo certo. O rascunho da sessÃ£o foi cancelado.")


def _teclado_secretarios(prefixo: str, secretarios: List[Dict[str, Any]]) -> InlineKeyboardMarkup:
    linhas: List[List[InlineKeyboardButton]] = []
    for sec in secretarios[:30]:
        sid = _norm_text(sec.get("telegram_id"))
        nome = _norm_text(sec.get("nome") or sid)
        if sid:
            linhas.append([InlineKeyboardButton(f"ðŸ‘¤ {nome}", callback_data=f"{prefixo}|{sid}")])
    linhas.append([InlineKeyboardButton("âŒ Cancelar", callback_data=f"{prefixo}_cancelar")])
    return InlineKeyboardMarkup(linhas)


def _evento_tem_loja_nova(dados: Dict[str, Any], lojas_existentes: List[Dict[str, Any]]) -> bool:
    nome = _norm_text(dados.get("nome_loja"))
    numero = _norm_text(dados.get("numero_loja") or "0")
    rito = _norm_text(dados.get("rito"))
    if not nome:
        return False
    for loja in lojas_existentes:
        if (
            _norm_text(loja.get("Nome da Loja")) == nome
            and _norm_text(loja.get("NÃºmero") or "0") == numero
            and _norm_text(loja.get("Rito")) == rito
        ):
            return False
    return True


def _resumo_evento_md(dados: Dict[str, Any]) -> str:
    numero_loja = _norm_text(dados.get("numero_loja") or "0")
    numero_fmt = f" {_escape_md(numero_loja)}" if numero_loja and numero_loja != "0" else ""
    responsavel = _norm_text(dados.get("secretario_responsavel_nome") or dados.get("secretario_responsavel_id"))
    linha_resp = f"*SecretÃ¡rio responsÃ¡vel:* {_escape_md(responsavel)}\n" if responsavel else ""
    obs = _norm_text(dados.get("observacoes"))
    linha_obs = f"*Ordem do dia / observaÃ§Ãµes:* {_escape_md(obs)}\n" if obs else ""
    grau = dados.get("grau_outro") if _norm_text(dados.get("grau")) == "Outro" else dados.get("grau", "")
    traje = dados.get("traje_outro") if _norm_text(dados.get("traje")) == "Outro" else dados.get("traje", "")
    rito = dados.get("rito_outro") if _norm_text(dados.get("rito")) == "Outro" else dados.get("rito", "")
    potencia = _potencia_resumo(dados)
    return (
        "ðŸ“‹ *Confirme a sessÃ£o antes de publicar*\n\n"
        f"*Data:* {_escape_md(dados.get('data', ''))}\n"
        f"*HorÃ¡rio:* {_escape_md(dados.get('horario', ''))}\n"
        f"*Grau da sessÃ£o:* {_escape_md(grau or '')}\n"
        f"*Tipo de sessÃ£o:* {_escape_md(dados.get('tipo_sessao', ''))}\n"
        f"*Traje:* {_escape_md(traje or '')}\n"
        f"*Ãgape:* {_escape_md(dados.get('agape', ''))}\n"
        f"{linha_obs}"
        f"*Loja:* {_escape_md(dados.get('nome_loja', ''))}{numero_fmt}\n"
        f"*Oriente:* {_escape_md(dados.get('oriente', ''))}\n"
        f"*Rito:* {_escape_md(rito or '')}\n"
        f"*PotÃªncia:* {_escape_md(potencia or '')}\n"
        f"*EndereÃ§o:* {_escape_md(dados.get('endereco', ''))}\n"
        f"{linha_resp}"
    )



def _teclado_rascunho_evento(dados: Dict[str, Any], nivel: str, lojas_existentes: List[Dict[str, Any]]) -> InlineKeyboardMarkup:
    linhas: List[List[InlineKeyboardButton]] = []
    if str(nivel) == "3" and not _norm_text(dados.get("secretario_responsavel_id")):
        linhas.append([InlineKeyboardButton("ðŸ‘¤ Definir secretÃ¡rio responsÃ¡vel", callback_data="draft_evento_escolher_secretario")])
    else:
        if _evento_tem_loja_nova(dados, lojas_existentes):
            linhas.append([InlineKeyboardButton("âœ… Publicar e salvar loja", callback_data="draft_evento_confirmar_com_loja")])
            linhas.append([InlineKeyboardButton("âœ… Publicar sem salvar loja", callback_data="draft_evento_confirmar_sem_loja")])
        else:
            linhas.append([InlineKeyboardButton("âœ… Publicar no grupo", callback_data="draft_evento_confirmar_sem_loja")])
    linhas.append([_botao_editar_webapp("âœï¸ Editar formulÃ¡rio", WEBAPP_URL_EVENTO)])
    linhas.append([InlineKeyboardButton("âŒ Cancelar", callback_data="draft_evento_cancelar")])
    return InlineKeyboardMarkup(linhas)


async def _enviar_resumo_rascunho_membro(bot, telegram_id: int) -> None:
    dados = _obter_rascunho(_RASCUNHOS_MEMBRO, telegram_id)
    if not dados:
        return
    await bot.send_message(
        chat_id=telegram_id,
        text=_resumo_membro_md(dados),
        parse_mode="MarkdownV2",
        reply_markup=_teclado_rascunho_membro(),
    )


async def _enviar_resumo_rascunho_loja(bot, telegram_id: int) -> None:
    dados = _obter_rascunho(_RASCUNHOS_LOJA, telegram_id)
    if not dados:
        return
    nivel = str(get_nivel(telegram_id))
    await bot.send_message(
        chat_id=telegram_id,
        text=_resumo_loja_md(dados),
        parse_mode="MarkdownV2",
        reply_markup=_teclado_rascunho_loja(dados, nivel),
    )


async def _enviar_resumo_rascunho_evento(bot, telegram_id: int) -> None:
    dados = _obter_rascunho(_RASCUNHOS_EVENTO, telegram_id)
    if not dados:
        return
    nivel = str(get_nivel(telegram_id))
    lojas_existentes = listar_lojas(int(telegram_id), include_todas=(nivel == "3")) or []
    await bot.send_message(
        chat_id=telegram_id,
        text=_resumo_evento_md(dados),
        parse_mode="MarkdownV2",
        reply_markup=_teclado_rascunho_evento(dados, nivel, lojas_existentes),
    )


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# VERIFICAÃ‡ÃƒO DE SEGURANÃ‡A (HMAC-SHA256 â€” padrÃ£o Telegram Mini App)
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def verify_telegram_webapp_data(init_data: str, bot_token: str) -> Optional[dict]:
    """
    Verifica a assinatura do initData conforme:
    https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app

    Retorna o dict do usuÃ¡rio Telegram se vÃ¡lido; None caso contrÃ¡rio.
    Rejeita tokens com mais de 24 h (proteÃ§Ã£o contra replay attacks).
    """
    if not init_data or not bot_token:
        return None
    try:
        # parse_qsl URL-decodifica os valores automaticamente â€” obrigatÃ³rio para
        # que o data_check_string bata com o que o Telegram assinou.
        params: Dict[str, str] = dict(parse_qsl(init_data, strict_parsing=False))

        hash_value = params.pop("hash", "")
        if not hash_value:
            return None

        # auth_date nÃ£o pode ser muito antigo (24 h)
        auth_date = int(params.get("auth_date", 0))
        if time.time() - auth_date > 86400:
            logger.warning("initData expirado (auth_date=%s)", auth_date)
            return None

        # String de verificaÃ§Ã£o: pares chave=valor ordenados por chave, separados por \n
        data_check = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))

        # Chave secreta: HMAC-SHA256("WebAppData", bot_token)
        secret = hmac.new(b"WebAppData", bot_token.encode("utf-8"), digestmod=hashlib.sha256).digest()
        expected = hmac.new(secret, data_check.encode("utf-8"), digestmod=hashlib.sha256).hexdigest()

        if not hmac.compare_digest(expected, hash_value):
            logger.warning("Assinatura initData invÃ¡lida.")
            return None

        # parse_qsl jÃ¡ decodificou o valor de "user"; sÃ³ precisa fazer o parse JSON
        return json.loads(params.get("user", "{}"))

    except Exception as e:
        logger.warning("Erro na verificaÃ§Ã£o initData: %s", e)
        return None


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# FUN??ES AUXILIARES INTERNAS
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _parse_data_ddmmyyyy(texto: str) -> Optional[datetime]:
    try:
        return datetime.strptime(texto.strip(), "%d/%m/%Y")
    except Exception:
        return None


def _norm_text(valor: Any) -> str:
    if valor is None:
        return ""
    return str(valor).strip()


def _escape_md(s: str) -> str:
    for ch in r"\_*[]()~`>#+-=|{}.!":
        s = (s or "").replace(ch, f"\\{ch}")
    return s


def _teclado_pos_publicacao(id_evento: str, agape_str: str) -> InlineKeyboardMarkup:
    """Teclado de confirmaÃ§Ã£o de presenÃ§a publicado no grupo (mesmo padrÃ£o do fluxo conversacional)."""
    tipo = (agape_str or "").lower()
    linhas: List[List[InlineKeyboardButton]] = []
    if "gratuito" in tipo:
        linhas.append([InlineKeyboardButton("ðŸ½ Participar com Ã¡gape (gratuito)", callback_data=f"confirmar|{id_evento}|gratuito")])
        linhas.append([InlineKeyboardButton("ðŸš« Participar sem Ã¡gape", callback_data=f"confirmar|{id_evento}|sem")])
    elif "pago" in tipo:
        linhas.append([InlineKeyboardButton("ðŸ½ Participar com Ã¡gape (pago)", callback_data=f"confirmar|{id_evento}|pago")])
        linhas.append([InlineKeyboardButton("ðŸš« Participar sem Ã¡gape", callback_data=f"confirmar|{id_evento}|sem")])
    else:
        linhas.append([InlineKeyboardButton("âœ… Confirmar presenÃ§a", callback_data=f"confirmar|{id_evento}|sem")])
    linhas.append([InlineKeyboardButton("ðŸ‘¥ Ver confirmados", callback_data=f"ver_confirmados|{id_evento}")])
    return InlineKeyboardMarkup(linhas)


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# ESTILOS E JS BASE COMPARTILHADOS
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

_CSS = """
:root{
  --bg:var(--tg-theme-bg-color,#fff);
  --text:var(--tg-theme-text-color,#000);
  --hint:var(--tg-theme-hint-color,#888);
  --link:var(--tg-theme-link-color,#2481cc);
  --btn:var(--tg-theme-button-color,#2481cc);
  --btn-text:var(--tg-theme-button-text-color,#fff);
  --sec:var(--tg-theme-secondary-bg-color,#f1f1f1);
  --border:rgba(128,128,128,.2);
  --select-bg:var(--tg-theme-secondary-bg-color,#f1f1f1);
  --select-text:var(--tg-theme-text-color,#000);
}
*{box-sizing:border-box;margin:0;padding:0}
body{
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
  background:var(--bg);color:var(--text);
  color-scheme:light dark;
  min-height:100vh;padding:12px 12px 84px;
}
h1{font-size:17px;font-weight:700;margin-bottom:14px}
.card{background:var(--sec);border-radius:12px;padding:12px 14px;margin-bottom:12px}
.card-title{font-size:12px;font-weight:600;color:var(--hint);
  text-transform:uppercase;letter-spacing:.6px;margin-bottom:12px}
.field{margin-bottom:14px}
.field:last-child{margin-bottom:0}
label{display:block;font-size:13px;color:var(--hint);margin-bottom:3px;font-weight:500}
input,textarea{
  width:100%;background:transparent;border:none;
  border-bottom:1px solid var(--border);padding:6px 0;
  font-size:16px;color:var(--text);outline:none;font-family:inherit;
  -webkit-appearance:none;appearance:none;
}
select{
  width:100%;background-color:var(--select-bg);border:none;
  border-bottom:1px solid var(--border);padding:6px 0;
  font-size:16px;color:var(--select-text);outline:none;font-family:inherit;
  -webkit-appearance:none;appearance:none;
}
select{
  background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 10 6'%3E%3Cpath fill='%23888' d='M5 6L0 0h10z'/%3E%3C/svg%3E");
  background-repeat:no-repeat;background-position:right 2px center;
  background-size:10px 6px;padding-right:20px;
}
option{background-color:var(--bg);color:var(--text)}
select:focus{border-bottom:1px solid var(--btn)}
textarea{
  border:1px solid var(--border);border-radius:8px;
  padding:8px;resize:none;min-height:64px;
}
input::placeholder,textarea::placeholder{color:var(--hint)}
.err{color:#ff3b30;font-size:12px;margin-top:3px;display:none}
.err.on{display:block}
.toast{
  position:fixed;bottom:76px;left:50%;transform:translateX(-50%);
  background:rgba(0,0,0,.75);color:#fff;padding:8px 18px;
  border-radius:20px;font-size:14px;display:none;z-index:99;
  white-space:nowrap;max-width:80vw;overflow:hidden;text-overflow:ellipsis;
}
.toast.on{display:block}
.info{font-size:12px;color:var(--hint);margin-top:3px}
.actions{position:sticky;bottom:0;background:linear-gradient(to top,var(--bg) 75%,rgba(255,255,255,0));padding:12px 0 20px;margin-top:8px}
.actions-stack{display:flex;flex-direction:column;gap:10px}
.btn-primary{
  width:100%;background:var(--btn);color:var(--btn-text);border:none;border-radius:12px;
  padding:14px 16px;font-size:16px;font-weight:700;box-shadow:0 8px 22px rgba(0,0,0,.12)
}
.btn-primary:disabled{opacity:.65}
.btn-secondary{
  width:100%;background:var(--sec);color:var(--text);border:1px solid var(--border);border-radius:12px;
  padding:13px 16px;font-size:15px;font-weight:600
}
"""

_JS_BASE = """
const tg=(window.Telegram&&window.Telegram.WebApp)?window.Telegram.WebApp:null;
if(tg){
  try{tg.ready();}catch(e){}
  try{tg.expand();}catch(e){}
}
function setPrimaryLoading(isLoading){
  const btn=document.getElementById('btn_publicar_evento');
  if(btn){
    btn.disabled=!!isLoading;
    btn.textContent=isLoading?'Enviando...':'Continuar para revisÃ£o';
  }
}
function hideMainButtonSafe(){
  if(tg && tg.MainButton){
    try{ tg.MainButton.hideProgress(); }catch(e){}
    try{ tg.MainButton.disable(); }catch(e){}
    try{ tg.MainButton.hide(); }catch(e){}
  }
}
function closeMiniAppSafe(){
  if(tg && typeof tg.close==='function'){
    try{ tg.close(); return; }catch(e){}
  }
  try{ window.close(); }catch(e){}
}
function tgInitData(){
  return (tg && tg.initData) ? tg.initData : '';
}
function showToast(msg,dur){
  const t=document.getElementById('toast');
  t.textContent=msg;t.classList.add('on');
  clearTimeout(t._tid);
  t._tid=setTimeout(()=>t.classList.remove('on'),dur||3000);
}
function setErr(id,msg){
  const e=document.getElementById(id+'_err');
  if(e){e.textContent=msg;e.classList.add('on');}
}
function clearErr(id){
  const e=document.getElementById(id+'_err');
  if(e) e.classList.remove('on');
}
function val(id){return((document.getElementById(id)||{}).value||'').trim();}
function req(id,label){
  const v=val(id);
  if(!v){setErr(id,label+' Ã© obrigatÃ³rio.');return false;}
  clearErr(id);return true;
}
function maskDate(el){
  if(!el)return;
  el.addEventListener('input',function(){
    let s=this.value.replace(/\\D/g,'');
    if(s.length<=2)this.value=s;
    else if(s.length<=4)this.value=s.slice(0,2)+'/'+s.slice(2);
    else this.value=s.slice(0,2)+'/'+s.slice(2,4)+'/'+s.slice(4,8);
  });
}
function parseDateBR(texto){
  const m=(texto||'').match(/^(\\d{2})\\/(\\d{2})\\/(\\d{4})$/);
  if(!m)return null;
  const dia=Number(m[1]), mes=Number(m[2]), ano=Number(m[3]);
  const d=new Date(ano,mes-1,dia);
  if(d.getFullYear()!==ano || d.getMonth()!==mes-1 || d.getDate()!==dia)return null;
  d.setHours(0,0,0,0);
  return d;
}
"""

def _html_wrap(title: str, body: str, script: str) -> str:
    return (
        f'<!DOCTYPE html><html lang="pt-BR">'
        f'<head><meta charset="UTF-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">'
        f'<title>{title} â€” Bode Andarilho</title>'
        f'<script src="https://telegram.org/js/telegram-web-app.js"></script>'
        f'<style>{_CSS}</style></head>'
        f'<body><h1>ðŸ {title}</h1>'
        f'{body}'
        f'<div id="toast" class="toast"></div>'
        f'<script>{_JS_BASE}{script}</script>'
        f'</body></html>'
    )


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# HTML â€” CADASTRO DE MEMBRO
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def html_cadastro_membro() -> str:
    body = """
<div class="card">
  <div class="info">ApÃ³s preencher, o bot enviarÃ¡ um resumo no chat para confirmaÃ§Ã£o final. O template visual Ã© opcional e poderÃ¡ ser enviado depois.</div>
</div>
<div id="lojas_membro_card" class="card" style="display:none">
  <div class="card-title">Sua Loja</div>
  <div class="field">
    <label for="loja_sel_membro">Selecione sua loja cadastrada</label>
    <select id="loja_sel_membro">
      <option value="">Preencher manualmente...</option>
    </select>
    <div class="info">Se preferir, vocÃª pode seguir com o preenchimento manual logo abaixo.</div>
  </div>
</div>
<div class="card">
  <div class="card-title">IdentificaÃ§Ã£o</div>
  <div class="field">
    <label for="nome">Nome completo *</label>
    <input id="nome" type="text" placeholder="Como consta no quadro da loja" autocomplete="name">
    <div id="nome_err" class="err"></div>
  </div>
  <div class="field">
    <label for="data_nasc">Data de nascimento * <span class="info">(DD/MM/AAAA)</span></label>
    <input id="data_nasc" type="text" placeholder="25/03/1985" maxlength="10" inputmode="numeric">
    <div id="data_nasc_err" class="err"></div>
  </div>
  <div class="field">
    <label for="grau">Grau *</label>
    <select id="grau">
      <option value="">Selecione...</option>
      <option>Aprendiz</option>
      <option>Companheiro</option>
      <option>Mestre</option>
    </select>
    <div id="grau_err" class="err"></div>
  </div>
  <div class="field">
    <label for="mi">Mestre Instalado? *</label>
    <select id="mi">
      <option value="">Selecione...</option>
      <option value="Sim">Sim</option>
      <option value="NÃ£o">NÃ£o</option>
    </select>
    <div id="mi_err" class="err"></div>
  </div>
  <div class="field">
    <label for="vm">VenerÃ¡vel Mestre? *</label>
    <select id="vm">
      <option value="">Selecione...</option>
      <option value="Sim">Sim</option>
      <option value="NÃ£o">NÃ£o</option>
    </select>
    <div id="vm_err" class="err"></div>
  </div>
</div>
<div class="card">
  <div class="card-title">Sua Loja</div>
  <div class="field">
    <label for="loja">Nome da loja *</label>
    <input id="loja" type="text" placeholder="Ex.: Luz da Fraternidade">
    <div id="loja_err" class="err"></div>
  </div>
  <div class="field">
    <label for="numero_loja">NÃºmero <span class="info">(0 se nÃ£o houver)</span></label>
    <input id="numero_loja" type="text" value="0" inputmode="numeric" maxlength="8">
  </div>
  <div class="field">
    <label for="oriente">Oriente *</label>
    <input id="oriente" type="text" placeholder="Ex.: SÃ£o Paulo / SP">
    <div id="oriente_err" class="err"></div>
  </div>
  <div class="field">
    <label for="potencia">PotÃªncia *</label>
    <select id="potencia">
      <option value="">Selecione...</option>
      <option value="GOB">GOB</option>
      <option value="CMSB">CMSB</option>
      <option value="COMAB">COMAB</option>
    </select>
    <div id="potencia_err" class="err"></div>
  </div>
  <div class="field" id="potencia_outra_wrap" style="display:none">
    <label for="potencia_outra">Complemento da potÃªncia *</label>
    <input id="potencia_outra" type="text" placeholder="Ex.: GOB-RS, GLMERGS, GORGS">
    <div id="potencia_outra_err" class="err"></div>
  </div>
</div>
"""
    script = """
maskDate(document.getElementById('data_nasc'));
let lojasMembroCarregadas=[];
let lojaMembroSelecionada=false;
let lojaMembroId='';

function syncPotenciaOutra(){
  const wrap=document.getElementById('potencia_outra_wrap');
  if(!wrap)return;
  wrap.style.display=['GOB','CMSB','COMAB'].includes(val('potencia'))?'block':'none';
  if(!['GOB','CMSB','COMAB'].includes(val('potencia')))clearErr('potencia_outra');
}
function definirLojaManual(){
  lojaMembroSelecionada=false;
  lojaMembroId='';
  const sel=document.getElementById('loja_sel_membro');
  if(sel && sel.value)sel.value='';
}
function aplicarLojaMembro(loja){
  if(!loja)return;
  lojaMembroSelecionada=true;
  lojaMembroId=(loja.id||'').toString();
  if(loja.nome)document.getElementById('loja').value=loja.nome;
  if(loja.numero)document.getElementById('numero_loja').value=loja.numero;
  if(loja.oriente)document.getElementById('oriente').value=loja.oriente;
  if(loja.potencia){
    const select=document.getElementById('potencia');
    const existe=Array.from(select.options).some(o=>o.value===loja.potencia);
    select.value=existe?loja.potencia:'';
    document.getElementById('potencia_outra').value=loja.potencia_complemento||'';
    syncPotenciaOutra();
  }
}
function validate(){
  let ok=true;
  ok=req('nome','Nome')&&ok;
  const dn=val('data_nasc');
  if(!parseDateBR(dn)){
    setErr('data_nasc','Use uma data vÃ¡lida no formato DD/MM/AAAA.');ok=false;
  }else clearErr('data_nasc');
  ok=req('grau','Grau')&&ok;
  ok=req('mi','Mestre Instalado')&&ok;
  ok=req('vm','VenerÃ¡vel Mestre')&&ok;
  ok=req('loja','Nome da loja')&&ok;
  ok=req('oriente','Oriente')&&ok;
  ok=req('potencia','PotÃªncia')&&ok;
  ok=req('potencia_outra','Complemento da potÃªncia')&&ok;
  return ok;
}
document.getElementById('potencia').addEventListener('change',syncPotenciaOutra);
syncPotenciaOutra();
['loja','numero_loja','oriente','potencia','potencia_outra'].forEach((id)=>{
  const el=document.getElementById(id);
  if(!el)return;
  el.addEventListener('input',()=>{ if(lojaMembroSelecionada)definirLojaManual(); });
  el.addEventListener('change',()=>{ if(lojaMembroSelecionada)definirLojaManual(); });
});
document.getElementById('loja_sel_membro').addEventListener('change',function(){
  if(!this.value){
    definirLojaManual();
    return;
  }
  const loja=lojasMembroCarregadas[Number(this.value)];
  aplicarLojaMembro(loja);
});
if(tg && tg.MainButton){
  tg.MainButton.setText('Continuar para revisÃ£o');
  tg.MainButton.show();
  tg.MainButton.onClick(async()=>{
    if(!validate())return;
    try{
      const r=await fetch('/api/rascunho_membro',{
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({
          init_data:tgInitData(),
          loja_id:lojaMembroId,
          nome:val('nome'),
          data_nasc:val('data_nasc'),
          grau:val('grau'),
          mi:val('mi'),
          vm:val('vm'),
          loja:val('loja'),
          numero_loja:val('numero_loja')||'0',
          oriente:val('oriente'),
          potencia:val('potencia'),
          potencia_outra:val('potencia_outra')
        })
      });
      const j=await r.json();
      if(j.ok){closeMiniAppSafe();}
      else{showToast(j.error||'Erro. Tente novamente.');tg.MainButton.hideProgress();tg.MainButton.enable();}
    }catch{showToast('Falha de conexÃ£o. Tente novamente.');tg.MainButton.hideProgress();tg.MainButton.enable();}
  });
}
(async()=>{
  try{
    const rLojas=await fetch('/api/lojas',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({init_data:tgInitData()})
    });
    const jLojas=await rLojas.json();
    if(jLojas.ok&&jLojas.lojas&&jLojas.lojas.length>0){
      lojasMembroCarregadas=jLojas.lojas;
      const sel=document.getElementById('loja_sel_membro');
      jLojas.lojas.forEach((l,i)=>{
        const o=document.createElement('option');
        o.value=i;
        o.textContent=l.nome+(l.numero&&l.numero!=='0'?' '+l.numero:'');
        sel.appendChild(o);
      });
      document.getElementById('lojas_membro_card').style.display='block';
    }
  }catch(e){}
  try{
    const r=await fetch('/api/rascunho_membro',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({init_data:tgInitData(),action:'get'})
    });
    const j=await r.json();
    if(j.ok&&j.draft){
      if(j.draft.loja_id)lojaMembroId=j.draft.loja_id;
      if(j.draft.nome)document.getElementById('nome').value=j.draft.nome;
      if(j.draft.data_nasc)document.getElementById('data_nasc').value=j.draft.data_nasc;
      if(j.draft.grau)document.getElementById('grau').value=j.draft.grau;
      if(j.draft.mi)document.getElementById('mi').value=j.draft.mi;
      if(j.draft.vm)document.getElementById('vm').value=j.draft.vm;
      if(j.draft.loja)document.getElementById('loja').value=j.draft.loja;
      if(j.draft.numero_loja)document.getElementById('numero_loja').value=j.draft.numero_loja;
      if(j.draft.oriente)document.getElementById('oriente').value=j.draft.oriente;
      if(j.draft.potencia)document.getElementById('potencia').value=j.draft.potencia;
      if(j.draft.potencia_complemento||j.draft.potencia_outra)document.getElementById('potencia_outra').value=j.draft.potencia_complemento||j.draft.potencia_outra;
      if(j.draft.loja_id && lojasMembroCarregadas.length){
        const idx=lojasMembroCarregadas.findIndex((l)=>(l.id||'').toString()===j.draft.loja_id.toString());
        if(idx>=0){
          document.getElementById('loja_sel_membro').value=String(idx);
          aplicarLojaMembro(lojasMembroCarregadas[idx]);
        }
      }
      syncPotenciaOutra();
    }
  }catch(e){}
})();
"""
    return _html_wrap("Cadastro de Membro", body, script)



def html_cadastro_loja() -> str:
    body = """
<div class="card">
  <div class="info">ApÃ³s preencher, o bot enviarÃ¡ um resumo no chat para confirmaÃ§Ã£o final.</div>
</div>
<div class="card">
  <div class="card-title">Dados da Loja</div>
  <div class="field">
    <label for="nome_loja">Nome da loja *</label>
    <input id="nome_loja" type="text" placeholder="Ex.: Luz da Fraternidade">
    <div id="nome_loja_err" class="err"></div>
  </div>
  <div class="field">
    <label for="numero">NÃºmero <span class="info">(0 se nÃ£o houver)</span></label>
    <input id="numero" type="text" value="0" inputmode="numeric" maxlength="8">
  </div>
  <div class="field">
    <label for="oriente">Oriente *</label>
    <input id="oriente" type="text" placeholder="Ex.: SÃ£o Paulo / SP">
    <div id="oriente_err" class="err"></div>
  </div>
  <div class="field">
    <label for="rito">Rito *</label>
    <input id="rito" type="text" placeholder="Ex.: Brasileiro / EscocÃªs / York">
    <div id="rito_err" class="err"></div>
  </div>
  <div class="field">
    <label for="potencia">PotÃªncia *</label>
    <select id="potencia">
      <option value="">Selecione...</option>
      <option value="GOB">GOB</option>
      <option value="CMSB">CMSB</option>
      <option value="COMAB">COMAB</option>
    </select>
    <div id="potencia_err" class="err"></div>
  </div>
  <div class="field" id="potencia_outra_wrap" style="display:none">
    <label for="potencia_outra">Complemento da potÃªncia *</label>
    <input id="potencia_outra" type="text" placeholder="Ex.: GOB-RS, GLMERGS, GORGS">
    <div id="potencia_outra_err" class="err"></div>
  </div>
  <div class="field">
    <label for="endereco">EndereÃ§o da loja ou link do Google Maps *</label>
    <input id="endereco" type="text" placeholder="Ex.: https://maps.app.goo.gl/... ou Rua X, 123 - Centro">
    <div id="endereco_err" class="err"></div>
    <div class="info">Preferencialmente, cole o link do Google Maps para facilitar a localizaÃ§Ã£o exata.</div>
  </div>
</div>
"""
    script = """
function validate(){
  let ok=true;
  ok=req('nome_loja','Nome da loja')&&ok;
  ok=req('oriente','Oriente')&&ok;
  ok=req('rito','Rito')&&ok;
  ok=req('potencia','PotÃªncia')&&ok;
  ok=req('potencia_outra','Complemento da potÃªncia')&&ok;
  ok=req('endereco','EndereÃ§o')&&ok;
  return ok;
}
function syncPotenciaComplemento(){
  const wrap=document.getElementById('potencia_outra_wrap');
  if(wrap)wrap.style.display=val('potencia')?'block':'none';
}
document.getElementById('potencia').addEventListener('change',syncPotenciaComplemento);
syncPotenciaComplemento();
if(tg && tg.MainButton){
tg.MainButton.setText('Continuar para revisÃ£o');
tg.MainButton.show();
tg.MainButton.onClick(async()=>{
  if(!validate())return;
  try{
    const r=await fetch('/api/rascunho_loja',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({
        init_data:tgInitData(),
        nome:val('nome_loja'),
        numero:val('numero')||'0',
        oriente:val('oriente'),
        rito:val('rito'),
        potencia:val('potencia'),
        potencia_outra:val('potencia_outra'),
        endereco:val('endereco')
      })
    });
    const j=await r.json();
    if(j.ok){closeMiniAppSafe();}
    else{showToast(j.error||'Erro. Tente novamente.');tg.MainButton.hideProgress();tg.MainButton.enable();}
  }catch{showToast('Falha de conexÃ£o. Tente novamente.');tg.MainButton.hideProgress();tg.MainButton.enable();}
});
}

(async()=>{
  try{
    const r=await fetch('/api/rascunho_loja',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({init_data:tgInitData(),action:'get'})
    });
    const j=await r.json();
    if(j.ok&&j.draft){
      if(j.draft.nome)document.getElementById('nome_loja').value=j.draft.nome;
      if(j.draft.numero)document.getElementById('numero').value=j.draft.numero;
      if(j.draft.oriente)document.getElementById('oriente').value=j.draft.oriente;
      if(j.draft.rito)document.getElementById('rito').value=j.draft.rito;
      if(j.draft.potencia)document.getElementById('potencia').value=j.draft.potencia;
      if(j.draft.endereco)document.getElementById('endereco').value=j.draft.endereco;
    }
  }catch(e){}
})();
"""
    return _html_wrap("Cadastro de Loja", body, script)


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# HTML â€” CADASTRO DE EVENTO
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def html_cadastro_evento() -> str:
    body = """
<div class="card">
  <div class="info">Preencha os dados e continue. A publicaÃ§Ã£o final serÃ¡ confirmada no chat do bot.</div>
</div>
<div id="lojas_card" class="card" style="display:none">
  <div class="card-title">Atalho - Lojas cadastradas</div>
  <div class="field">
    <label for="loja_sel">Selecione para auto-preencher</label>
    <select id="loja_sel">
      <option value="">Preencher manualmente...</option>
    </select>
  </div>
</div>

<div class="card">
  <div class="card-title">A sessÃ£o</div>
  <div class="field">
    <label for="data_ev">Data * <span class="info">(DD/MM/AAAA)</span></label>
    <input id="data_ev" type="text" placeholder="25/03/2026" maxlength="10" inputmode="numeric">
    <div id="data_ev_err" class="err"></div>
  </div>
  <div class="field">
    <label for="horario">HorÃ¡rio *</label>
    <input id="horario" type="time" value="19:30">
    <div id="horario_err" class="err"></div>
  </div>
  <div class="field">
    <label for="grau">Grau da sessÃ£o *</label>
    <select id="grau">
      <option value="">Selecione...</option>
      <option>Aprendiz</option>
      <option>Companheiro</option>
      <option>Mestre</option>
      <option>Outro</option>
    </select>
    <div id="grau_err" class="err"></div>
  </div>
  <div class="field" id="grau_outro_wrap" style="display:none">
    <label for="grau_outro">Informe o grau da sessÃ£o *</label>
    <input id="grau_outro" type="text" placeholder="Ex.: CÃ¢mara do Meio">
    <div id="grau_outro_err" class="err"></div>
  </div>
  <div class="field">
    <label for="tipo_sessao">Tipo de sessÃ£o *</label>
    <input id="tipo_sessao" type="text" placeholder="Ex.: OrdinÃ¡ria, Magna, IniciaÃ§Ã£o">
    <div id="tipo_sessao_err" class="err"></div>
  </div>
  <div class="field">
    <label for="traje">Traje *</label>
    <select id="traje">
      <option value="">Selecione...</option>
      <option value="Traje maÃ§Ã´nico">Traje maÃ§Ã´nico</option>
      <option value="Livre">Livre</option>
      <option value="Outro">Outro</option>
    </select>
    <div id="traje_err" class="err"></div>
  </div>
  <div class="field" id="traje_outro_wrap" style="display:none">
    <label for="traje_outro">Informe o traje *</label>
    <input id="traje_outro" type="text" placeholder="Ex.: Social completo">
    <div id="traje_outro_err" class="err"></div>
  </div>
  <div class="field">
    <label for="agape">Ãgape *</label>
    <select id="agape">
      <option value="">Selecione...</option>
      <option value="Nao">NÃ£o haverÃ¡ Ã¡gape</option>
      <option value="Sim (Gratuito)">Sim - Gratuito</option>
      <option value="Sim (Pago)">Sim - Pago (dividido)</option>
    </select>
    <div id="agape_err" class="err"></div>
  </div>
  <div class="field">
    <label for="observacoes">Ordem do dia / observaÃ§Ãµes <span class="info">(opcional)</span></label>
    <textarea id="observacoes" placeholder="InformaÃ§Ãµes adicionais da sessÃ£o..."></textarea>
  </div>
</div>

<div class="card">
  <div class="card-title">Dados da Loja</div>
  <div class="field">
    <label for="nome_loja">Nome da loja *</label>
    <input id="nome_loja" type="text" placeholder="Ex.: Luz da Fraternidade">
    <div id="nome_loja_err" class="err"></div>
  </div>
  <div class="field">
    <label for="numero_loja">NÃºmero <span class="info">(0 se nÃ£o houver)</span></label>
    <input id="numero_loja" type="text" value="0" inputmode="numeric" maxlength="8">
  </div>
  <div class="field">
    <label for="oriente">Oriente *</label>
    <input id="oriente" type="text" placeholder="Ex.: SÃ£o Paulo / SP">
    <div id="oriente_err" class="err"></div>
  </div>
  <div class="field">
    <label for="rito">Rito *</label>
    <select id="rito">
      <option value="">Selecione...</option>
      <option value="REAA">REAA</option>
      <option value="Schroeder">Schroeder</option>
      <option value="Adonhiramita">Adonhiramita</option>
      <option value="Brasileiro">Brasileiro</option>
      <option value="York">York</option>
      <option value="Moderno">Moderno</option>
      <option value="EscocÃªs Retificado">EscocÃªs Retificado</option>
      <option value="Memphis-Misraim">Memphis-Misraim</option>
      <option value="Outro">Outro</option>
    </select>
    <div id="rito_err" class="err"></div>
  </div>
  <div class="field" id="rito_outro_wrap" style="display:none">
    <label for="rito_outro">Informe o rito *</label>
    <input id="rito_outro" type="text" placeholder="Ex.: Rito Moderno">
    <div id="rito_outro_err" class="err"></div>
  </div>
  <div class="field">
    <label for="potencia">PotÃªncia *</label>
    <select id="potencia">
      <option value="">Selecione...</option>
      <option value="GOB">GOB</option>
      <option value="CMSB">CMSB</option>
      <option value="COMAB">COMAB</option>
    </select>
    <div id="potencia_err" class="err"></div>
  </div>
  <div class="field" id="potencia_outra_wrap" style="display:none">
    <label for="potencia_outra">Complemento da potÃªncia *</label>
    <input id="potencia_outra" type="text" placeholder="Ex.: GOB-RS, GLMERGS, GORGS">
    <div id="potencia_outra_err" class="err"></div>
  </div>
  <div class="field">
    <label for="endereco">EndereÃ§o da sessÃ£o ou link do Google Maps *</label>
    <input id="endereco" type="text" placeholder="Ex.: https://maps.app.goo.gl/... ou Rua X, 123 - Centro">
    <div id="endereco_err" class="err"></div>
    <div class="info">Preferencialmente, cole o link do Google Maps para que o bot gere o atalho de mapa.</div>
  </div>
</div>

<div id="acoes_publicacao" class="actions">
  <div class="actions-stack">
    <button id="btn_publicar_evento" type="button" class="btn-primary" onclick="publicarEvento()">Continuar para revisÃ£o</button>
    <button id="btn_cancelar_evento" type="button" class="btn-secondary" onclick="closeMiniAppSafe()">Fechar</button>
  </div>
</div>
"""
    script = r"""
maskDate(document.getElementById('data_ev'));
let lojasCarregadas=[];
let lojaSelecionadaViaAtalho=false;
let enviandoEvento=false;

function syncOutro(selectId, wrapId, inputId, valorOutro){
  const wrap=document.getElementById(wrapId);
  if(!wrap)return;
  const ativo=valorOutro==='' ? !!val(selectId) : val(selectId)===valorOutro;
  wrap.style.display=ativo?'block':'none';
  if(!ativo)clearErr(inputId);
}

function aplicarValorComOutro(selectId, inputId, wrapId, valor, valorOutro){
  const select=document.getElementById(selectId);
  if(!select)return;
  const texto=(valor||'').toString().trim();
  if(!texto){
    select.value='';
    if(document.getElementById(inputId))document.getElementById(inputId).value='';
    syncOutro(selectId, wrapId, inputId, valorOutro);
    return;
  }
  const existe=Array.from(select.options).some(o=>o.value===texto || o.text===texto);
  if(existe){
    select.value=texto;
    if(document.getElementById(inputId))document.getElementById(inputId).value='';
  }else{
    select.value=valorOutro;
    if(document.getElementById(inputId))document.getElementById(inputId).value=texto;
  }
  syncOutro(selectId, wrapId, inputId, valorOutro);
}

function norm(v){
  return (v||'').toString().trim().toLowerCase();
}

(async()=>{
  try{
    const r=await fetch('/api/lojas',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({init_data:tgInitData()})
    });
    const j=await r.json();
    if(j.ok&&j.lojas&&j.lojas.length>0){
      lojasCarregadas=j.lojas;
      const sel=document.getElementById('loja_sel');
      j.lojas.forEach((l,i)=>{
        const o=document.createElement('option');
        o.value=i;
        o.textContent=l.nome+(l.numero&&l.numero!=='0'?' '+l.numero:'');
        o.dataset.loja=JSON.stringify(l);
        sel.appendChild(o);
      });
      document.getElementById('lojas_card').style.display='block';
    }
  }catch(e){}
  try{
    const rDraft=await fetch('/api/rascunho_evento',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({init_data:tgInitData(),action:'get'})
    });
    const jDraft=await rDraft.json();
    if(jDraft.ok&&jDraft.draft){
      if(jDraft.draft.data)document.getElementById('data_ev').value=jDraft.draft.data;
      if(jDraft.draft.horario)document.getElementById('horario').value=jDraft.draft.horario;
      if(jDraft.draft.grau)aplicarValorComOutro('grau','grau_outro','grau_outro_wrap',jDraft.draft.grau_outro||jDraft.draft.grau,'Outro');
      if(jDraft.draft.tipo_sessao)document.getElementById('tipo_sessao').value=jDraft.draft.tipo_sessao;
      if(jDraft.draft.traje)aplicarValorComOutro('traje','traje_outro','traje_outro_wrap',jDraft.draft.traje_outro||jDraft.draft.traje,'Outro');
      if(jDraft.draft.agape)document.getElementById('agape').value=jDraft.draft.agape;
      if(jDraft.draft.observacoes)document.getElementById('observacoes').value=jDraft.draft.observacoes;
      if(jDraft.draft.nome_loja)document.getElementById('nome_loja').value=jDraft.draft.nome_loja;
      if(jDraft.draft.numero_loja)document.getElementById('numero_loja').value=jDraft.draft.numero_loja;
      if(jDraft.draft.oriente)document.getElementById('oriente').value=jDraft.draft.oriente;
      if(jDraft.draft.rito)aplicarValorComOutro('rito','rito_outro','rito_outro_wrap',jDraft.draft.rito_outro||jDraft.draft.rito,'Outro');
      if(jDraft.draft.potencia)document.getElementById('potencia').value=jDraft.draft.potencia;
      if(jDraft.draft.potencia_complemento||jDraft.draft.potencia_outra)document.getElementById('potencia_outra').value=jDraft.draft.potencia_complemento||jDraft.draft.potencia_outra;
      if(jDraft.draft.endereco)document.getElementById('endereco').value=jDraft.draft.endereco;
    }
  }catch(e){}
})();

document.getElementById('loja_sel').addEventListener('change',function(){
  if(!this.value){
    lojaSelecionadaViaAtalho=false;
    return;
  }
  lojaSelecionadaViaAtalho=true;
  const o=this.options[this.selectedIndex];
  const l=JSON.parse(o.dataset.loja||'{}');
  if(l.nome)document.getElementById('nome_loja').value=l.nome;
  if(l.numero)document.getElementById('numero_loja').value=l.numero;
  if(l.oriente)document.getElementById('oriente').value=l.oriente;
  if(l.rito)aplicarValorComOutro('rito','rito_outro','rito_outro_wrap',l.rito,'Outro');
  if(l.potencia)document.getElementById('potencia').value=l.potencia;
  document.getElementById('potencia_outra').value=l.potencia_complemento||'';
  if(l.endereco)document.getElementById('endereco').value=l.endereco;
});

document.getElementById('grau').addEventListener('change',()=>syncOutro('grau','grau_outro_wrap','grau_outro','Outro'));
document.getElementById('traje').addEventListener('change',()=>syncOutro('traje','traje_outro_wrap','traje_outro','Outro'));
document.getElementById('rito').addEventListener('change',()=>syncOutro('rito','rito_outro_wrap','rito_outro','Outro'));
document.getElementById('potencia').addEventListener('change',()=>syncOutro('potencia','potencia_outra_wrap','potencia_outra',''));
syncOutro('grau','grau_outro_wrap','grau_outro','Outro');
syncOutro('traje','traje_outro_wrap','traje_outro','Outro');
syncOutro('rito','rito_outro_wrap','rito_outro','Outro');
syncOutro('potencia','potencia_outra_wrap','potencia_outra','');

function validate(){
  let ok=true;
  const dv=val('data_ev');
  const dataEvento=parseDateBR(dv);
  if(!dataEvento){
    setErr('data_ev','Use uma data vÃ¡lida no formato DD/MM/AAAA.');ok=false;
  }else{
    const hoje=new Date();
    hoje.setHours(0,0,0,0);
    if(dataEvento<hoje){
      setErr('data_ev','A data da sessÃ£o nÃ£o pode estar no passado.');ok=false;
    }else{
      clearErr('data_ev');
    }
  }
  ok=req('horario','HorÃ¡rio')&&ok;
  ok=req('grau','Grau da sessÃ£o')&&ok;
  if(val('grau')==='Outro') ok=req('grau_outro','Grau da sessÃ£o')&&ok;
  ok=req('tipo_sessao','Tipo de sessÃ£o')&&ok;
  ok=req('traje','Traje')&&ok;
  if(val('traje')==='Outro') ok=req('traje_outro','Traje')&&ok;
  ok=req('agape','Ãgape')&&ok;
  ok=req('nome_loja','Nome da loja')&&ok;
  ok=req('oriente','Oriente')&&ok;
  ok=req('rito','Rito')&&ok;
  if(val('rito')==='Outro') ok=req('rito_outro','Rito')&&ok;
  ok=req('potencia','PotÃªncia')&&ok;
  ok=req('potencia_outra','Complemento da potÃªncia')&&ok;
  ok=req('endereco','EndereÃ§o')&&ok;
  return ok;
}

async function publicarEvento(){
  if(enviandoEvento)return;
  if(!validate())return;
  enviandoEvento=true;
  setPrimaryLoading(true);
  try{
    const r=await fetch('/api/rascunho_evento',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({
        init_data:tgInitData(),
        data:val('data_ev'),
        horario:val('horario'),
        grau:val('grau'),
        grau_outro:val('grau_outro'),
        tipo_sessao:val('tipo_sessao'),
        traje:val('traje'),
        traje_outro:val('traje_outro'),
        agape:val('agape'),
        observacoes:(document.getElementById('observacoes').value||'').trim(),
        nome_loja:val('nome_loja'),
        numero_loja:val('numero_loja')||'0',
        oriente:val('oriente'),
        rito:val('rito'),
        rito_outro:val('rito_outro'),
        potencia:val('potencia'),
        potencia_outra:val('potencia_outra'),
        endereco:val('endereco'),
        loja_id:(lojasCarregadas[Number(document.getElementById('loja_sel').value)]||{}).id||''
      })
    });
    const j=await r.json();
    if(j.ok){
      closeMiniAppSafe();
    }
    else{
      showToast(j.error||'Erro. Tente novamente.');
      setPrimaryLoading(false);
      enviandoEvento=false;
    }
  }catch{
    showToast('Falha de conexÃ£o. Tente novamente.');
    setPrimaryLoading(false);
    enviandoEvento=false;
  }
}

hideMainButtonSafe();
const btnPublicar=document.getElementById('btn_publicar_evento');
if(btnPublicar){
  btnPublicar.addEventListener('click',publicarEvento);
}
const btnCancelar=document.getElementById('btn_cancelar_evento');
if(btnCancelar){
  btnCancelar.addEventListener('click',()=>closeMiniAppSafe());
}
"""
    return _html_wrap("Cadastro de Evento", body, script)



# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# HANDLERS GET (servem os HTMLs)
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

async def get_cadastro_membro(request: Request) -> HTMLResponse:
    return HTMLResponse(html_cadastro_membro())


async def get_cadastro_evento(request: Request) -> HTMLResponse:
    return HTMLResponse(html_cadastro_evento())


async def get_cadastro_loja(request: Request) -> HTMLResponse:
    return HTMLResponse(html_cadastro_loja())


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# API â€” LISTAR LOJAS (para o form de evento)
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

async def api_listar_lojas(request: Request) -> JSONResponse:
    bot_token: str = request.app.state.bot_token
    try:
        body: dict = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "lojas": []}, status_code=400)

    init_data = (body.get("init_data") or "").strip()
    user = verify_telegram_webapp_data(init_data, bot_token)
    if not user:
        return JSONResponse({"ok": False, "lojas": []}, status_code=403)

    telegram_id = user.get("id")
    if not telegram_id:
        return JSONResponse({"ok": False, "lojas": []}, status_code=403)

    lojas = listar_lojas(int(telegram_id)) or []
    result = []
    for lj in lojas:
        result.append({
            "id":       str(lj.get("ID") or lj.get("id") or ""),
            "nome":     lj.get("Nome da Loja", ""),
            "numero":   str(lj.get("NÃºmero") or "0"),
            "oriente":  lj.get("Oriente da Loja") or lj.get("Oriente", ""),
            "rito":     lj.get("Rito", ""),
            "potencia": lj.get("PotÃªncia", ""),
            "potencia_complemento": lj.get("PotÃªncia complemento", ""),
            "endereco": lj.get("EndereÃ§o", ""),
        })
    return JSONResponse({"ok": True, "lojas": result})


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# API â€” CADASTRO DE MEMBRO
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

async def api_cadastro_membro(request: Request) -> JSONResponse:
    bot_token: str = request.app.state.bot_token
    try:
        body: dict = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "JSON invÃ¡lido."}, status_code=400)

    init_data = (body.get("init_data") or "").strip()
    user = verify_telegram_webapp_data(init_data, bot_token)
    if not user:
        return JSONResponse({"ok": False, "error": "NÃ£o autorizado."}, status_code=403)

    telegram_id = user.get("id")
    if not telegram_id:
        return JSONResponse({"ok": False, "error": "UsuÃ¡rio nÃ£o identificado."}, status_code=403)
    if not await _usuario_esta_no_grupo(request.app.state.telegram_app.bot, int(telegram_id)):
        return JSONResponse(
            {
                "ok": False,
                "error": "Seu cadastro sÃ³ pode ser concluÃ­do por quem estÃ¡ participando do grupo do Bode Andarilho no momento.",
            },
            status_code=403,
        )

    # Sanitizar e validar campos
    nome       = (body.get("nome")       or "").strip()[:200]
    data_nasc  = (body.get("data_nasc")  or "").strip()[:10]
    grau       = (body.get("grau")       or "").strip()[:50]
    vm         = (body.get("vm")         or "").strip()[:10]
    loja       = (body.get("loja")       or "").strip()[:200]
    numero_loja= (body.get("numero_loja")or "0").strip()[:10]
    oriente    = (body.get("oriente")    or "").strip()[:200]
    potencia, potencia_complemento = normalizar_potencia(
        (body.get("potencia") or "").strip()[:200],
        (body.get("potencia_outra") or body.get("potencia_complemento") or "").strip()[:200],
    )

    if not all([nome, data_nasc, grau, vm, loja, oriente, potencia]):
        return JSONResponse({"ok": False, "error": "Preencha todos os campos obrigatÃ³rios."}, status_code=400)
    if not validar_potencia(potencia, potencia_complemento):
        return JSONResponse({"ok": False, "error": "Informe a potência principal e o complemento."}, status_code=400)

    try:
        datetime.strptime(data_nasc, "%d/%m/%Y")
    except ValueError:
        return JSONResponse({"ok": False, "error": "Data de nascimento invÃ¡lida (DD/MM/AAAA)."}, status_code=400)

    graus_validos = {"Aprendiz", "Companheiro", "Mestre", "Mestre Instalado"}
    if grau not in graus_validos:
        return JSONResponse({"ok": False, "error": "Grau invÃ¡lido."}, status_code=400)

    ja_existe = buscar_membro(int(telegram_id))

    dados: Dict[str, Any] = {
        "Telegram ID":        str(telegram_id),
        "Nome":               nome,
        "Data de nascimento": data_nasc,
        "Grau":               grau,
        "VenerÃ¡vel Mestre":   vm,
        "Loja":               loja,
        "NÃºmero da loja":     numero_loja,
        "Oriente":            oriente,
        "PotÃªncia":           potencia,
        "PotÃªncia complemento": potencia_complemento,
        "Status":             "Ativo",
        "Nivel":              "1",
    }

    ok = cadastrar_membro(dados)
    if not ok:
        return JSONResponse({"ok": False, "error": "Falha ao salvar. Tente novamente."}, status_code=500)

    try:
        bot = request.app.state.telegram_app.bot
        nome_esc = _escape_md(nome)
        if ja_existe:
            msg = f"âœ… *Cadastro atualizado\\!*\n\nSaudaÃ§Ãµes, Ir\\.Â·\\. {nome_esc}\\. Seus dados foram atualizados\\."
        else:
            msg = (
                f"âœ… *Cadastro realizado a contento\\!*\n\n"
                f"Bem\\-vindo ao Bode Andarilho, Ir\\.Â·\\. {nome_esc}\\!\n"
                f"Use /start para acessar o Painel do Obreiro\\."
            )
        await bot.send_message(chat_id=telegram_id, text=msg, parse_mode="MarkdownV2")
    except Exception as e:
        logger.warning("Falha ao enviar confirmaÃ§Ã£o de cadastro para %s: %s", telegram_id, e)

    return JSONResponse({"ok": True})


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# API â€” CADASTRO DE LOJA
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

async def api_cadastro_loja(request: Request) -> JSONResponse:
    bot_token: str = request.app.state.bot_token
    try:
        body: dict = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "JSON invÃ¡lido."}, status_code=400)

    init_data = (body.get("init_data") or "").strip()
    user = verify_telegram_webapp_data(init_data, bot_token)
    if not user:
        return JSONResponse({"ok": False, "error": "NÃ£o autorizado."}, status_code=403)

    telegram_id = user.get("id")
    if not telegram_id:
        return JSONResponse({"ok": False, "error": "UsuÃ¡rio nÃ£o identificado."}, status_code=403)

    nome     = (body.get("nome")     or "").strip()[:200]
    numero   = (body.get("numero")   or "0").strip()[:10]
    oriente  = (body.get("oriente")  or "").strip()[:200]
    rito     = (body.get("rito")     or "").strip()[:200]
    potencia, potencia_complemento = normalizar_potencia(
        (body.get("potencia") or "").strip()[:200],
        (body.get("potencia_outra") or body.get("potencia_complemento") or "").strip()[:200],
    )
    endereco = (body.get("endereco") or "").strip()[:400]

    if not all([nome, oriente, rito, potencia, endereco]):
        return JSONResponse({"ok": False, "error": "Preencha todos os campos obrigatÃ³rios."}, status_code=400)
    if not validar_potencia(potencia, potencia_complemento):
        return JSONResponse({"ok": False, "error": "Informe a potência principal e o complemento."}, status_code=400)

    dados_loja: Dict[str, Any] = {
        "nome":     nome,
        "numero":   numero,
        "oriente":  oriente,
        "rito":     rito,
        "potencia": potencia,
        "potencia_complemento": potencia_complemento,
        "endereco": endereco,
    }

    ok = cadastrar_loja(int(telegram_id), dados_loja)
    if not ok:
        return JSONResponse({"ok": False, "error": "Falha ao salvar a loja. Tente novamente."}, status_code=500)

    try:
        bot = request.app.state.telegram_app.bot
        nome_esc = _escape_md(nome)
        await bot.send_message(
            chat_id=telegram_id,
            text=f"âœ… *Loja cadastrada\\!*\n\nðŸ› *{nome_esc}* registrada com sucesso\\.\nEla estarÃ¡ disponÃ­vel como atalho no cadastro de eventos\\.",
            parse_mode="MarkdownV2",
        )
    except Exception as e:
        logger.warning("Falha ao confirmar cadastro de loja para %s: %s", telegram_id, e)

    return JSONResponse({"ok": True})


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# API â€” CADASTRO DE EVENTO
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

async def api_cadastro_evento(request: Request) -> JSONResponse:
    bot_token: str = request.app.state.bot_token
    try:
        body: dict = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "JSON invÃ¡lido."}, status_code=400)

    init_data = (body.get("init_data") or "").strip()
    user = verify_telegram_webapp_data(init_data, bot_token)
    if not user:
        return JSONResponse({"ok": False, "error": "NÃ£o autorizado."}, status_code=403)

    telegram_id = user.get("id")
    if not telegram_id:
        return JSONResponse({"ok": False, "error": "UsuÃ¡rio nÃ£o identificado."}, status_code=403)

    # Sanitizar campos
    data_str    = (body.get("data")       or "").strip()[:10]
    horario     = (body.get("horario")    or "").strip()[:5]
    grau        = (body.get("grau")       or "").strip()[:50]
    tipo_sessao = (body.get("tipo_sessao")or "").strip()[:200]
    traje       = (body.get("traje")      or "").strip()[:200]
    agape       = (body.get("agape")      or "").strip()[:50]
    observacoes = (body.get("observacoes")or "").strip()[:500]
    nome_loja   = (body.get("nome_loja")  or "").strip()[:200]
    numero_loja = (body.get("numero_loja")or "0").strip()[:10]
    oriente     = (body.get("oriente")    or "").strip()[:200]
    rito        = (body.get("rito")       or "").strip()[:200]
    potencia, potencia_complemento = normalizar_potencia(
        (body.get("potencia") or "").strip()[:200],
        (body.get("potencia_outra") or body.get("potencia_complemento") or "").strip()[:200],
    )
    endereco    = (body.get("endereco")   or "").strip()[:400]

    if not all([data_str, horario, grau, tipo_sessao, traje, agape, nome_loja, oriente, rito, potencia, endereco]):
        return JSONResponse({"ok": False, "error": "Preencha todos os campos obrigatÃ³rios."}, status_code=400)
    if not validar_potencia(potencia, potencia_complemento):
        return JSONResponse({"ok": False, "error": "Informe a potência principal e o complemento."}, status_code=400)

    dt = _parse_data_ddmmyyyy(data_str)
    if not dt:
        return JSONResponse({"ok": False, "error": "Data invÃ¡lida. Use DD/MM/AAAA."}, status_code=400)

    hoje = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    if dt < hoje:
        return JSONResponse({"ok": False, "error": "A data nÃ£o pode ser no passado."}, status_code=400)

    dia_semana = dt.strftime("%A")

    evento: Dict[str, Any] = {
        "Data do evento":              data_str,
        "Dia da semana":               dia_semana,
        "Hora":                        horario,
        "Nome da loja":                nome_loja,
        "NÃºmero da loja":              numero_loja,
        "Oriente":                     oriente,
        "Grau":                        grau,
        "Tipo de sessÃ£o":              tipo_sessao,
        "Rito":                        rito,
        "PotÃªncia":                    potencia,
        "PotÃªncia complemento":        potencia_complemento,
        "Traje obrigatÃ³rio":           traje,
        "Ãgape":                       agape,
        "ObservaÃ§Ãµes":                 observacoes,
        "Telegram ID do grupo":        _GRUPO_PRINCIPAL_ID,
        "Telegram ID do secretÃ¡rio":   str(telegram_id),
        "Status":                      "Ativo",
        "EndereÃ§o da sessÃ£o":          endereco,
    }

    id_evento = cadastrar_evento(evento)
    if not id_evento:
        return JSONResponse({"ok": False, "error": "Falha ao salvar o evento. Tente novamente."}, status_code=500)

    # Publicar no grupo e notificar secretÃ¡rio
    try:
        bot = request.app.state.telegram_app.bot

        dia_semana_pt = {
            "Monday": "segunda",
          "Tuesday": "terÃ§a",
            "Wednesday": "quarta",
            "Thursday": "quinta",
            "Friday": "sexta",
          "Saturday": "sÃ¡bado",
            "Sunday": "domingo",
        }.get(dia_semana, "")

        data_hora = f"{_escape_md(data_str)} ({_escape_md(dia_semana_pt)}) â€¢ {_escape_md(horario)}" if dia_semana_pt else f"{_escape_md(data_str)} â€¢ {_escape_md(horario)}"
        nome_esc   = _escape_md(nome_loja)
        num_fmt    = f" {_escape_md(numero_loja)}" if numero_loja and numero_loja != "0" else ""
        endereco_raw = (endereco or "").strip()
        endereco_url = endereco_raw if endereco_raw.startswith(("http://", "https://")) else ""
        texto_grupo = (
            "NOVA SESSÃƒO\n\n"
            f"{data_hora}\n"
            f"Grau: {_escape_md(grau)}\n\n"
            "LOJA\n"
            f"{nome_esc}{num_fmt}\n"
            f"{_escape_md(oriente)} - {_escape_md(potencia)}\n\n"
            "SESSÃƒO\n"
            f"Tipo: {_escape_md(tipo_sessao)}\n"
            f"Rito: {_escape_md(rito)}\n"
            f"Traje: {_escape_md(traje)}\n"
            f"Ãgape: {_escape_md(agape)}\n\n"
            "ORDEM DO DIA / OBSERVAÃ‡Ã•ES\n"
            f"{_escape_md(observacoes) or '-'}\n\n"
        )

        if endereco_url:
            texto_grupo += f"Local: [Abrir no mapa]({endereco_url})"
        else:
            texto_grupo += f"Local: {_escape_md(endereco)}"

        try:
            grupo_id_int = int(_GRUPO_PRINCIPAL_ID)
            await bot.send_message(
                chat_id=grupo_id_int,
                text=texto_grupo,
                parse_mode="Markdown",
                reply_markup=_teclado_pos_publicacao(id_evento, agape),
            )
        except Exception as eg:
            logger.warning("Falha ao publicar evento no grupo: %s", eg)

        await bot.send_message(
            chat_id=telegram_id,
            text="âœ… *Evento cadastrado e publicado no grupo\\!*",
            parse_mode="MarkdownV2",
        )
    except Exception as e:
        logger.warning("Falha ao confirmar evento para %s: %s", telegram_id, e)

    return JSONResponse({"ok": True})

