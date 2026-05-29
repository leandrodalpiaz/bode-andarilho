# src/miniapp.py
# ============================================
# BODE ANDARILHO - TELEGRAM MINI APP
# ============================================
#
# Fornece formulários web para cadastro de membros, eventos e lojas,
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
# Segurança:
#   Toda submissão inclui o initData do Telegram WebApp SDK.
#   O servidor verifica a assinatura HMAC-SHA256 antes de processar.
#   O telegram_id é extraído **exclusivamente** do initData verificado,
#   nunca do corpo da requisição.
# ============================================

from __future__ import annotations

import hashlib
import hmac
import json
import asyncio
import base64
import logging
import mimetypes
import os
import time
from io import BytesIO
from datetime import datetime
from typing import Any, Dict, List, Optional, Set
from urllib.parse import parse_qsl, unquote

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo, Update
from PIL import Image

from src.sheets_supabase import (
    buscar_membro,
    cadastrar_membro,
    cadastrar_evento,
    atualizar_evento,
    cadastrar_loja,
    listar_lojas,
    buscar_loja_por_nome_numero,
    listar_secretarios_ativos,
    upload_storage_publico,
    supabase,
)
from src.permissoes import get_nivel
from src.evento_midia import BUCKET_EVENT_CARDS, publicar_evento_no_grupo as publicar_midia_evento_no_grupo
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
from src.ritos import normalizar_rito

logger = logging.getLogger(__name__)

DIAS_SEMANA_PT_BR = {
    "Monday": "segunda-feira",
    "Tuesday": "terça-feira",
    "Wednesday": "quarta-feira",
    "Thursday": "quinta-feira",
    "Friday": "sexta-feira",
    "Saturday": "sábado",
    "Sunday": "domingo",
}


def _dia_semana_pt_br(dt: Optional[datetime]) -> str:
    return DIAS_SEMANA_PT_BR.get(dt.strftime("%A"), "") if dt else ""

# ─────────────────────────────────────────────────────────────────────────────
# URLS DOS WEBAPPS (lidas do ambiente em import-time)
# ─────────────────────────────────────────────────────────────────────────────
def _webapp_base_url() -> str:
    raw = (os.getenv("RENDER_EXTERNAL_URL", "") or "").strip().rstrip("/")
    lowered = raw.lower()
    if not raw:
        return ""
    if not lowered.startswith("https://"):
        logger.warning("Mini App desativada: RENDER_EXTERNAL_URL precisa usar HTTPS. Valor atual: %s", raw)
        return ""
    if "seu-app.onrender.com" in lowered or "example.com" in lowered:
        logger.warning("Mini App desativada: RENDER_EXTERNAL_URL ainda está com placeholder. Valor atual: %s", raw)
        return ""
    return raw


_RENDER_URL = _webapp_base_url()
WEBAPP_URL_MEMBRO = f"{_RENDER_URL}/webapp/cadastro_membro" if _RENDER_URL else ""
WEBAPP_URL_EVENTO = f"{_RENDER_URL}/webapp/cadastro_evento" if _RENDER_URL else ""
WEBAPP_URL_LOJA   = f"{_RENDER_URL}/webapp/cadastro_loja"   if _RENDER_URL else ""
WEBAPP_URL_APOIOS = f"{_RENDER_URL}/webapp/apoios" if _RENDER_URL else ""

BUCKET_APOIOS_PUBLICIDADE = os.getenv("SUPABASE_APOIOS_BUCKET", "apoios-publicidade")

_GRUPO_PRINCIPAL_ID = os.getenv("GRUPO_PRINCIPAL_ID", "")

_RASCUNHOS_MEMBRO: Dict[int, Dict[str, Any]] = {}
_RASCUNHOS_LOJA: Dict[int, Dict[str, Any]] = {}
_RASCUNHOS_EVENTO: Dict[int, Dict[str, Any]] = {}
_BACKGROUND_TASKS: Set[asyncio.Task] = set()


def _botao_editar_webapp(texto: str, url: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(texto, web_app=WebAppInfo(url=url))


def _limpar_rascunhos_antigos(bucket: Dict[int, Dict[str, Any]], max_age_seconds: int = 3600) -> None:
    now = datetime.now()
    to_remove = []
    for tid, payload in list(bucket.items()):
        saved_at_str = payload.get("_saved_at")
        if saved_at_str:
            try:
                saved_at = datetime.fromisoformat(saved_at_str)
                if (now - saved_at).total_seconds() > max_age_seconds:
                    to_remove.append(tid)
            except Exception:
                to_remove.append(tid)
        else:
            to_remove.append(tid)
    for tid in to_remove:
        bucket.pop(tid, None)


def _salvar_rascunho(bucket: Dict[int, Dict[str, Any]], telegram_id: int, dados: Dict[str, Any]) -> None:
    try:
        _limpar_rascunhos_antigos(bucket, max_age_seconds=3600)
    except Exception:
        pass
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
    numero_fmt = f" - Nº {_escape_md(numero_loja)}" if numero_loja and numero_loja != "0" else ""
    potencia = _potencia_resumo(dados)
    return (
        "🧾 *Confirme seu cadastro*\n\n"
        f"*Nome:* {_escape_md(dados.get('nome', ''))}\n"
        f"*Data de nascimento:* {_escape_md(dados.get('data_nasc', ''))}\n"
        f"*Grau:* {_escape_md(dados.get('grau', ''))}\n"
        f"*Mestre Instalado:* {_escape_md(dados.get('mi', 'Não'))}\n"
        f"*Venerável Mestre:* {_escape_md(dados.get('vm', ''))}\n"
        f"*Loja:* {_escape_md(dados.get('loja', ''))}{numero_fmt}\n"
        f"*Oriente:* {_escape_md(dados.get('oriente', ''))}\n"
        f"*Potência local:* {_escape_md(potencia or '')}\n"
    )



def _teclado_rascunho_membro(readonly_loja: bool = False) -> InlineKeyboardMarkup:
    cb_confirmar = "draft_membro_confirmar" if readonly_loja else "iniciar_foto_cim_pwa"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Confirmar cadastro", callback_data=cb_confirmar)],
        [_botao_editar_webapp("✏️ Editar dados", WEBAPP_URL_MEMBRO)],
        [InlineKeyboardButton("❌ Cancelar", callback_data="draft_membro_cancelar")],
    ])


def _resumo_loja_md(dados: Dict[str, Any]) -> str:
    responsavel = _norm_text(dados.get("secretario_responsavel_nome") or dados.get("secretario_responsavel_id"))
    linha_responsavel = f"*Secretário responsável:* {_escape_md(responsavel)}\n" if responsavel else ""
    return (
        "🏛️ *Confirme os dados da loja*\n\n"
        f"*Nome:* {_escape_md(dados.get('nome', ''))}\n"
        f"*Número:* {_escape_md(dados.get('numero', '0'))}\n"
        f"*Oriente:* {_escape_md(dados.get('oriente', ''))}\n"
        f"*Rito:* {_escape_md(dados.get('rito', ''))}\n"
        f"*Potência local:* {_escape_md(_potencia_resumo(dados))}\n"
        f"*Endereço:* {_escape_md(dados.get('endereco', ''))}\n"
        f"{linha_responsavel}"
    )



def _teclado_rascunho_loja(dados: Dict[str, Any], nivel: str) -> InlineKeyboardMarkup:
    linhas: List[List[InlineKeyboardButton]] = []
    if str(nivel) == "3" and not _norm_text(dados.get("secretario_responsavel_id")):
        linhas.append([InlineKeyboardButton("👤 Definir secretário responsável", callback_data="draft_loja_escolher_secretario")])
    else:
        linhas.append([InlineKeyboardButton("✅ Confirmar loja", callback_data="draft_loja_confirmar")])
    linhas.append([_botao_editar_webapp("✏️ Editar loja", WEBAPP_URL_LOJA)])
    linhas.append([InlineKeyboardButton("❌ Cancelar", callback_data="draft_loja_cancelar")])
    return InlineKeyboardMarkup(linhas)


def _teclado_template_loja_pos_cadastro(loja_id: str = "") -> InlineKeyboardMarkup:
    cb_upload = f"loja_template_pos|{loja_id}" if loja_id else "loja_template_menu"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🖼 Enviar template agora", callback_data=cb_upload)],
        [InlineKeyboardButton("⏭ Usar padrão por enquanto", callback_data="loja_template_pular")],
        [InlineKeyboardButton("🏛️ Gerenciar lojas", callback_data="menu_lojas")],
    ])


def _json_error(mensagem: str, status_code: int = 400) -> JSONResponse:
    return JSONResponse({"ok": False, "error": mensagem}, status_code=status_code)


async def _usuario_esta_no_grupo(bot, telegram_id: int) -> bool:
    """Verifica se o usuário ainda participa do grupo principal configurado."""
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
        return None, None, _json_error("JSON inválido.", 400)

    init_data = (body.get("init_data") or "").strip()
    user = verify_telegram_webapp_data(init_data, bot_token)
    if not user:
        return None, None, _json_error("Não autorizado.", 403)

    telegram_id = user.get("id")
    if not telegram_id:
        return None, None, _json_error("Usuário não identificado.", 403)

    return body, int(telegram_id), None


def _extrair_dados_membro(body: Dict[str, Any]) -> Dict[str, Any]:
    return _normalizar_dados_potencia({
        "loja_id": _norm_text(body.get("loja_id"))[:80],
        "nome": _norm_text(body.get("nome"))[:200],
        "data_nasc": _norm_text(body.get("data_nasc"))[:10],
        "grau": _norm_text(body.get("grau"))[:50],
        "mi": _norm_text(body.get("mi") or "Não")[:10],
        "vm": _norm_text(body.get("vm"))[:10],
        "loja": limpar_nome_loja(_norm_text(body.get("loja"))[:200]),
        "numero_loja": _norm_text(body.get("numero_loja") or "0")[:10],
        "oriente": _norm_text(body.get("oriente"))[:200],
        "potencia": _norm_text(body.get("potencia"))[:200],
        "potencia_outra": _norm_text(body.get("potencia_outra") or body.get("potencia_complemento"))[:200],
    })


def _validar_dados_membro(dados: Dict[str, Any]) -> Optional[str]:
    if not all([dados["nome"], dados["data_nasc"], dados["grau"], dados["mi"], dados["vm"], dados["loja"], dados["oriente"], dados["potencia"]]):
        return "Preencha todos os campos obrigatórios."
    try:
        datetime.strptime(dados["data_nasc"], "%d/%m/%Y")
    except ValueError:
        return "Data de nascimento inválida. Use DD/MM/AAAA."
    if dados["grau"] not in {"Aprendiz", "Companheiro", "Mestre"}:
        return "Grau inválido."
    if dados["mi"] not in {"Sim", "Não"}:
        return "Informe se o irmão é Mestre Instalado."
    if dados["vm"] not in {"Sim", "Não"}:
        return "Informe se o irmão é Venerável Mestre."
    if not validar_potencia(dados["potencia"], dados.get("potencia_complemento")):
        return "Informe a potência principal e a potência local."
    return None


def _payload_membro(telegram_id: int, dados: Dict[str, Any], app = None) -> Dict[str, Any]:
    potencia, potencia_complemento = normalizar_potencia(dados.get("potencia"), dados.get("potencia_complemento"))
    
    status = "Pendente"
    nivel = "0"
    status_auditoria = ""
    
    if app:
        user_data = app.user_data.get(telegram_id) or {}
        if user_data.get("token_cadastro_secretario"):
            status_auditoria = "Pendente_Secretario"
        elif user_data.get("cadastro_voucher"):
            status = "Ativo"
            nivel = "1"
            
    return {
        "Telegram ID": str(telegram_id),
        "ID da loja": dados.get("loja_id", ""),
        "Nome": dados["nome"],
        "Data de nascimento": dados["data_nasc"],
        "Grau": dados["grau"],
        "Venerável Mestre": dados["vm"],
        "Mestre Instalado": dados.get("mi", "Não"),
        "Loja": dados["loja"],
        "Número da loja": dados["numero_loja"],
        "Oriente": dados["oriente"],
        "Potência": potencia,
        "Potência complemento": potencia_complemento,
        "Status": status,
        "Nivel": nivel,
        "Status Auditoria": status_auditoria,
    }


async def api_rascunho_membro(request: Request) -> JSONResponse:
    body, telegram_id, erro = await _validar_requisicao_webapp(request)
    if erro:
        return erro
    if not await _usuario_esta_no_grupo(request.app.state.telegram_app.bot, telegram_id):
        return _json_error(
            "Seu cadastro só pode ser concluído por quem está participando do grupo do Bode Andarilho no momento.",
            403,
        )
    if _norm_text((body or {}).get("action")).lower() == "get":
        draft = _obter_rascunho(_RASCUNHOS_MEMBRO, telegram_id)
        app = request.app.state.telegram_app
        user_data = app.user_data.get(telegram_id) or {}
        
        if user_data.get("cadastro_readonly_loja"):
            draft["loja"] = user_data.get("cadastro_loja", "")
            draft["numero_loja"] = user_data.get("cadastro_numero_loja", "0")
            draft["potencia"] = user_data.get("cadastro_potencia", "")
            draft["potencia_complemento"] = user_data.get("cadastro_potencia_complemento", "-")
            draft["readonly_loja"] = True
        elif user_data.get("cadastro_voucher") and not draft.get("loja"):
            draft["loja"] = user_data.get("cadastro_loja", "")
            draft["numero_loja"] = user_data.get("cadastro_numero_loja", "0")
            draft["oriente"] = user_data.get("cadastro_oriente", "")
            draft["potencia"] = user_data.get("cadastro_potencia", "")
            draft["potencia_complemento"] = user_data.get("cadastro_potencia_complemento", "")
            
        return JSONResponse({"ok": True, "draft": draft})
    dados = _extrair_dados_membro(body or {})
    mensagem = _validar_dados_membro(dados)
    if mensagem:
        return _json_error(mensagem, 400)
    _salvar_rascunho(_RASCUNHOS_MEMBRO, telegram_id, dados)
    try:
        await _enviar_resumo_rascunho_membro(request.app.state.telegram_app, telegram_id)
    except Exception as e:
        logger.warning("Falha ao enviar resumo do rascunho de membro para %s: %s", telegram_id, e)
    return JSONResponse({"ok": True, "message": "Rascunho salvo com sucesso."})


async def draft_membro_confirmar(update: Update, context) -> None:
    query = update.callback_query
    await query.answer()
    telegram_id = int(update.effective_user.id)
    if not await _usuario_esta_no_grupo(context.bot, telegram_id):
        await query.answer("O cadastro só pode ser concluído por quem está no grupo no momento.", show_alert=True)
        return
    dados = _obter_rascunho(_RASCUNHOS_MEMBRO, telegram_id)
    if not dados:
        await query.answer("Não encontrei um rascunho para confirmar.", show_alert=True)
        return
    ja_existe = buscar_membro(telegram_id)
    
    # GOVERNANÇA: Detecta se houve alteração em dados sensíveis de Loja
    mudou_loja = False
    if ja_existe:
        def _val_diff(v1, v2):
            return str(v1 or "").strip().lower() != str(v2 or "").strip().lower()
        
        novo_loja = dados.get("loja")
        novo_num = dados.get("numero_loja")
        
        exist_loja = ja_existe.get("Loja") or ja_existe.get("loja")
        exist_num = ja_existe.get("Número da loja") or ja_existe.get("numero_loja")
        
        if _val_diff(novo_loja, exist_loja) or _val_diff(novo_num, exist_num):
            mudou_loja = True

    user_data = context.application.user_data.get(telegram_id) or {}
    is_sec = user_data.get("token_cadastro_secretario")

    ok = cadastrar_membro(_payload_membro(telegram_id, dados, context.application))
    if not ok:
        await query.answer("Não consegui concluir o cadastro agora.", show_alert=True)
        return

    # Se alterou a Loja, notifica o Secretário responsável (Câmara de Reflexão)
    if is_sec:
        try:
            from src.cadastro import notificar_secretario_pendente_adm
            membro_novo = buscar_membro(telegram_id)
            if membro_novo:
                await notificar_secretario_pendente_adm(context, membro_novo)
        except Exception as e_notif:
            logger.warning("Erro ao notificar admin de secretario pendente via Mini App: %s", e_notif)
    elif mudou_loja:
        try:
            from src.cadastro import notificar_validacao_pendente
            membro_novo = buscar_membro(telegram_id)
            if membro_novo:
                await notificar_validacao_pendente(context, membro_novo, mudanca_loja=True)
        except Exception as e_notif:
            logger.warning("Erro ao notificar governanca via Mini App: %s", e_notif)

    _limpar_rascunho(_RASCUNHOS_MEMBRO, telegram_id)
    nome_esc = _escape_md(dados.get("nome", ""))
    if is_sec:
        texto = (
            f"✅ *Cadastro realizado com sucesso\\!*\n\n"
            f"Prezado Ir\\.·\\. {nome_esc}, seu cadastro de Secretário foi encaminhado para a aprovação da Administração Geral\\.\n\n"
            f"Você será notificado aqui assim que as suas credenciais forem homologadas\\."
        )
    elif ja_existe:
        texto = f"✅ *Cadastro atualizado\\!*\n\nSaudações, Ir\\.·\\. {nome_esc}\\. Seus dados foram atualizados\\."
        if mudou_loja:
            texto += "\n\n⚠️ *Importante:* Seus dados de Loja foram alterados\\. Seu cadastro retornou à *análise pendente* do Secretário por segurança\\."
    else:
        texto = (
            f"✅ *Cadastro realizado a contento\\!*\n\n"
            f"Bem\\-vindo ao Bode Andarilho, Ir\\.·\\. {nome_esc}\\!\n"
            "Use /start para acessar o Painel do Obreiro\\."
        )
    await query.edit_message_text(text=texto, parse_mode="MarkdownV2")


async def draft_membro_cancelar(update: Update, context) -> None:
    query = update.callback_query
    await query.answer()
    telegram_id = int(update.effective_user.id)
    _limpar_rascunho(_RASCUNHOS_MEMBRO, telegram_id)
    await query.edit_message_text("Tudo certo. O rascunho do cadastro foi cancelado.")


import re

def limpar_nome_loja(nome: str) -> str:
    """
    Remove prefixos maçônicos redundantes para manter apenas o Nome Nobre.
    """
    from src.sheets_supabase import padronizar_nome_loja
    return padronizar_nome_loja(nome)

def _extrair_dados_loja(body: Dict[str, Any]) -> Dict[str, Any]:
    from src.sheets_supabase import extrair_prefixo_e_nome
    raw_nome = _norm_text(body.get("nome"))[:200]
    prefixo, nome_base = extrair_prefixo_e_nome(raw_nome)
    return _normalizar_dados_potencia({
        "nome": nome_base,
        "prefixo": prefixo,
        "numero": _norm_text(body.get("numero") or "0")[:10],
        "oriente": _norm_text(body.get("oriente"))[:200],
        "rito": _norm_text(body.get("rito"))[:200],
        "rito_outro": _norm_text(body.get("rito_outro"))[:200],
        "potencia": _norm_text(body.get("potencia"))[:200],
        "potencia_outra": _norm_text(body.get("potencia_outra") or body.get("potencia_complemento"))[:200],
        "endereco": _norm_text(body.get("endereco"))[:400],
        "secretario_responsavel_id": _norm_text(body.get("secretario_responsavel_id"))[:80],
        "secretario_responsavel_nome": _norm_text(body.get("secretario_responsavel_nome"))[:200],
    })



def _validar_dados_loja(dados: Dict[str, Any]) -> Optional[str]:
    if not all([dados["nome"], dados["oriente"], dados["rito"], dados["potencia"], dados["endereco"]]):
        return "Preencha todos os campos obrigatórios."
    if dados["rito"] not in {"REAA", "Schroeder", "Schröder", "Adonhiramita", "Brasileiro", "York", "Moderno", "Escocês Retificado", "MLAA", "Memphis-Misraim", "Outro"}:
        return "Rito inválido."
    if dados["rito"] == "Outro" and not dados["rito_outro"]:
        return "Informe o rito quando selecionar 'Outro'."
    if not validar_potencia(dados["potencia"], dados.get("potencia_complemento")):
        return "Informe a potência principal e a potência local."
    return None


def _payload_loja(dados: Dict[str, Any], executor_id: int) -> Dict[str, Any]:
    rito = dados["rito_outro"] if dados.get("rito") == "Outro" else dados["rito"]
    return {
        "nome": dados["nome"],
        "prefixo": dados.get("prefixo", ""),
        "numero": dados["numero"],
        "oriente": dados["oriente"],
        "rito": rito,
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
        await query.answer("Não encontrei um rascunho de loja.", show_alert=True)
        return
    secretarios = listar_secretarios_ativos() or []
    if not secretarios:
        await query.answer("Nenhum secretário ativo foi encontrado.", show_alert=True)
        return
    await query.edit_message_text(
        "Escolha o secretário responsável por esta loja:",
        reply_markup=_teclado_secretarios("draft_loja_set_secretario", secretarios),
    )


async def draft_loja_set_secretario(update: Update, context) -> None:
    query = update.callback_query
    await query.answer()
    telegram_id = int(update.effective_user.id)
    dados = _obter_rascunho(_RASCUNHOS_LOJA, telegram_id)
    if not dados:
        await query.answer("Não encontrei um rascunho de loja.", show_alert=True)
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
        await query.edit_message_text("Tudo certo. A seleção do secretário foi cancelada.")
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
        await query.answer("Não encontrei um rascunho de loja.", show_alert=True)
        return
    nivel = str(get_nivel(telegram_id))
    if nivel == "3" and not _norm_text(dados.get("secretario_responsavel_id")):
        await query.answer("Defina primeiro o secretário responsável.", show_alert=True)
        return
    ok = cadastrar_loja(telegram_id, _payload_loja(dados, telegram_id))
    if not ok:
        await query.answer("Não consegui registrar a loja agora.", show_alert=True)
        return

    # Hook Conquistas Coletivas
    try:
        from src.conquistas import checar_e_disparar_marco_coletivo
        asyncio.create_task(checar_e_disparar_marco_coletivo(context.bot, dados))
    except Exception:
        pass
    _limpar_rascunho(_RASCUNHOS_LOJA, telegram_id)
    # TODO (Fase de Otimização de Queries): Substituir busca por texto por pesquisa simples utilizando a Foreign Key loja_id (UUID).
    loja = buscar_loja_por_nome_numero(
        dados.get("nome", ""),
        dados.get("numero", ""),
        dados.get("potencia", "")
    )
    loja_id = _norm_text((loja or {}).get("ID") or (loja or {}).get("id"))
    nome_esc = _escape_md(dados.get("nome", ""))
    await query.edit_message_text(
        text=(
            f"🏛️ *Loja cadastrada\\!*\n\n"
            f"✨ *{nome_esc}* foi registrada com sucesso e já pode ser usada nos próximos eventos\\.\n\n"
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
        "secretario_responsavel_id": _norm_text(body.get("secretario_responsavel_id"))[:80],
        "secretario_responsavel_nome": _norm_text(body.get("secretario_responsavel_nome"))[:200],
    })




def _validar_loja_para_evento(dados: dict) -> str | None:
    faltantes = []
    campos = [
        ("nome_loja", "nome da loja"),
        ("numero_loja", "número da loja"),
        ("oriente", "oriente/cidade"),
        ("rito", "rito"),
        ("potencia", "potência principal"),
        ("potencia_complemento", "potência local"),
        ("endereco", "endereço da sessão"),
    ]
    for chave, rotulo in campos:
        valor = str(dados.get(chave) or "").strip()
        if chave == "numero_loja" and valor == "0":
            valor = ""
        if not valor:
            faltantes.append(rotulo)
    if faltantes:
        return f"A loja selecionada está com o cadastro incompleto. Por favor, edite a loja e preencha os seguintes campos antes de criar uma sessão: {', '.join(faltantes)}."
    return None

def _validar_dados_evento(dados: Dict[str, Any]) -> Optional[str]:
    obrigatorios = [
        dados["data"], dados["horario"], dados["grau"], dados["tipo_sessao"],
        dados["traje"], dados["agape"], dados["nome_loja"], dados["oriente"],
        dados["rito"], dados["potencia"], dados["endereco"],
    ]
    if not all(obrigatorios):
        return "Preencha todos os campos obrigatórios."
    dt = _parse_data_ddmmyyyy(dados["data"])
    if not dt:
        return "Data inválida. Use DD/MM/AAAA."
    if dt < datetime.now().replace(hour=0, minute=0, second=0, microsecond=0):
        return "A data não pode ser no passado."
    if dados["grau"] not in {"Aprendiz", "Companheiro", "Mestre", "Outro"}:
        return "Grau da sessão inválido."
    if dados["grau"] == "Outro" and not dados["grau_outro"]:
        return "Informe o grau da sessão quando selecionar 'Outro'."
    if dados["traje"] not in {"Traje maçônico", "Livre", "Outro"}:
        return "Traje inválido."
    if dados["traje"] == "Outro" and not dados["traje_outro"]:
        return "Informe o traje quando selecionar 'Outro'."
    if dados["rito"] not in {"REAA", "Schroeder", "Schröder", "Adonhiramita", "Brasileiro", "York", "Moderno", "Escocês Retificado", "MLAA", "Memphis-Misraim", "Outro"}:
        return "Rito inválido."
    if dados["rito"] == "Outro" and not dados["rito_outro"]:
        return "Informe o rito quando selecionar 'Outro'."
    if not validar_potencia(dados["potencia"], dados.get("potencia_complemento")):
        return "Informe a potência principal e a potência local."
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
        "Dia da semana": _dia_semana_pt_br(dt),
        "Hora": dados["horario"],
        "Nome da loja": dados["nome_loja"],
        "Número da loja": dados["numero_loja"],
        "Oriente": dados["oriente"],
        "Grau": grau,
        "Tipo de sessão": dados["tipo_sessao"],
        "Rito": rito,
        "Potência": potencia,
        "Potência complemento": potencia_complemento,
        "Traje obrigatório": traje,
        "Ágape": dados["agape"],
        "Observações": dados["observacoes"],
        "Telegram ID do grupo": _GRUPO_PRINCIPAL_ID,
        "Telegram ID do secretário": secretario_id,
        "Status": "Ativo",
        "Endereço da sessão": dados["endereco"],
        "Modo visual": dados.get("modo_visual") or "template_loja",
        "Card especial URL": dados.get("card_especial_url", ""),
        "Card renderizado URL": "",
        "Card file_id Telegram": "",
        "Telegram tipo mensagem grupo": "",
    }


def _loja_para_payload_evento(loja: Dict[str, Any]) -> Dict[str, Any]:
    """Normaliza uma loja cadastrada para preencher rascunhos de sessão."""
    return {
        "loja_id": _norm_text(loja.get("ID") or loja.get("id")),
        "nome_loja": _norm_text(loja.get("Nome da Loja") or loja.get("nome_loja")),
        "numero_loja": _norm_text(loja.get("Número") or loja.get("numero") or "0"),
        "oriente": _norm_text(loja.get("Oriente da Loja") or loja.get("Oriente") or loja.get("oriente_loja")),
        "rito": _norm_text(loja.get("Rito") or loja.get("rito")),
        "potencia": _norm_text(loja.get("Potência") or loja.get("potencia")),
        "potencia_complemento": _norm_text(loja.get("Potência complemento") or loja.get("potencia_complemento")),
        "potencia_outra": _norm_text(loja.get("Potência complemento") or loja.get("potencia_complemento")),
        "endereco": _norm_text(loja.get("Endereço") or loja.get("endereco")),
        "secretario_responsavel_id": _norm_text(
            loja.get("Telegram ID do secretário responsável")
            or loja.get("secretario_responsavel_id")
            or loja.get("Telegram ID")
            or loja.get("telegram_id")
        ),
        "secretario_responsavel_nome": _norm_text(
            loja.get("Nome do secretário responsável")
            or loja.get("secretario_responsavel_nome")
        ),
    }


def _aplicar_loja_cadastrada_ao_evento(dados: Dict[str, Any], lojas_existentes: List[Dict[str, Any]]) -> Dict[str, Any]:
    loja_id = _norm_text(dados.get("loja_id"))
    if not loja_id:
        return dados
    loja = next(
        (
            lj for lj in lojas_existentes
            if _norm_text(lj.get("ID") or lj.get("id")) == loja_id
        ),
        None,
    )
    if not loja:
        return dados
    merged = dict(dados)
    for key, value in _loja_para_payload_evento(loja).items():
        if value:
            merged[key] = value
    return _normalizar_dados_potencia(merged)


def _texto_publicacao_evento(dados: Dict[str, Any]) -> str:
    dt = _parse_data_ddmmyyyy(dados.get("data", ""))
    dia_semana = _dia_semana_pt_br(dt)
    numero_loja = _norm_text(dados.get("numero_loja") or "0")
    numero_fmt = f" {numero_loja}" if numero_loja and numero_loja != "0" else ""
    return "\n".join([
        "NOVA SESSÃO",
        "",
        f"{dados.get('data', '')} ({dia_semana}) • {dados.get('horario', '')}" if dia_semana else f"{dados.get('data', '')} • {dados.get('horario', '')}",
        f"Grau: {dados.get('grau', '')}",
        "",
        "LOJA",
        f"{dados.get('nome_loja', '')}{numero_fmt}",
        f"{dados.get('oriente', '')} - {dados.get('potencia', '')}",
        "",
        "SESSÃO",
        f"Tipo: {dados.get('tipo_sessao', '')}",
        f"Rito: {dados.get('rito', '')}",
        f"Traje: {dados.get('traje', '')}",
        f"Ágape: {dados.get('agape', '')}",
        "",
        "ORDEM DO DIA / OBSERVAÇÕES",
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
    logger.info("miniapp.evento.rascunho.inicio telegram_id=%s", telegram_id)
    dados = _extrair_dados_evento(body or {})
    nivel = str(get_nivel(telegram_id))
    lojas_existentes = listar_lojas(telegram_id, include_todas=(nivel == "3")) or []
    dados = _aplicar_loja_cadastrada_ao_evento(dados, lojas_existentes)
    
    # Validação do limite de 4 sessões ativas por Loja ou por Secretário
    if nivel != "3":
        from src.sheets_supabase import contar_sessoes_ativas_loja, contar_sessoes_ativas_secretario
        if (contar_sessoes_ativas_loja(dados.get("loja_id"), dados.get("nome_loja"), dados.get("numero_loja"), dados.get("potencia")) >= 4 or
            contar_sessoes_ativas_secretario(telegram_id) >= 4):
            return _json_error(
                "Limite de 4 sessões futuras/ativas atingido para esta Loja ou Secretário. Publicar poucas sessões mantém a agenda útil e evita despejar o calendário anual de uma vez.",
                400
            )
        
    mensagem_loja = _validar_loja_para_evento(dados)
    if mensagem_loja:
        return _json_error(mensagem_loja, 400)
    mensagem = _validar_dados_evento(dados)
    if mensagem:
        return _json_error(mensagem, 400)

    # Se a loja já existe e algum dado vital estava vazio no banco, mas foi informado agora, atualiza no banco
    loja_id = dados.get("loja_id")
    if loja_id:
        from src.sheets_supabase import buscar_loja_por_id, atualizar_loja
        loja_obj = buscar_loja_por_id(loja_id)
        if loja_obj:
            mapeamento = {
                "Nome da Loja": "nome_loja",
                "Número": "numero_loja",
                "Oriente da Loja": "oriente",
                "Rito": "rito",
                "Potência": "potencia",
                "Potência complemento": "potencia_complemento",
                "Endereço": "endereco",
            }
            atualizacoes = {}
            for campo_db, chave_dados in mapeamento.items():
                val_db = _norm_text(loja_obj.get(campo_db) or "")
                val_novo = _norm_text(dados.get(chave_dados) or (dados.get("potencia_outra") if chave_dados == "potencia_complemento" else ""))
                
                # Se no banco está vazio (ou número é 0), e o usuário preencheu no evento, atualiza no banco
                if (not val_db or val_db == "0") and val_novo and val_novo != "0":
                    atualizacoes[campo_db] = val_novo
            
            if atualizacoes:
                atualizar_loja(loja_id, atualizacoes)
                logger.info("Atualizando campos faltantes da loja %s no banco: %s", loja_id, list(atualizacoes.keys()))
                # Atualiza a loja no cache/dados locais para que a alteração seja refletida imediatamente
                for lj in lojas_existentes:
                    if _norm_text(lj.get("ID") or lj.get("id")) == loja_id:
                        for k, v in atualizacoes.items():
                            lj[k] = v
                            # Também atualiza a chave normalizada se existir
                            if k == "Endereço": lj["endereco"] = v
                            if k == "Oriente da Loja": lj["oriente_loja"] = v
                            if k == "Potência complemento": lj["potencia_complemento"] = v
                dados = _aplicar_loja_cadastrada_ao_evento(dados, lojas_existentes)

    _salvar_rascunho(_RASCUNHOS_EVENTO, telegram_id, dados)
    try:
        await _enviar_resumo_rascunho_evento(request.app.state.telegram_app.bot, telegram_id)
        logger.info("miniapp.evento.rascunho.revisao_enviada telegram_id=%s", telegram_id)
    except Exception as e:
        logger.warning("Falha ao enviar resumo do rascunho de evento para %s: %s", telegram_id, e)
        return _json_error(
            "Rascunho salvo, mas não consegui enviar a revisão no chat. Feche o Mini App e tente abrir o cadastro novamente.",
            500,
        )
    return JSONResponse({"ok": True, "message": "Rascunho salvo com sucesso.", "review_sent": True})


async def draft_evento_escolher_secretario(update: Update, context) -> None:
    query = update.callback_query
    await query.answer()
    telegram_id = int(update.effective_user.id)
    dados = _obter_rascunho(_RASCUNHOS_EVENTO, telegram_id)
    if not dados:
        await query.answer("Não encontrei um rascunho de evento.", show_alert=True)
        return
    secretarios = listar_secretarios_ativos() or []
    if not secretarios:
        await query.answer("Nenhum secretário ativo foi encontrado.", show_alert=True)
        return
    await query.edit_message_text(
        "Escolha o secretário responsável por esta sessão:",
        reply_markup=_teclado_secretarios("draft_evento_set_secretario", secretarios),
    )


async def draft_evento_set_secretario(update: Update, context) -> None:
    query = update.callback_query
    await query.answer()
    telegram_id = int(update.effective_user.id)
    dados = _obter_rascunho(_RASCUNHOS_EVENTO, telegram_id)
    if not dados:
        await query.answer("Não encontrei um rascunho de evento.", show_alert=True)
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
        await query.edit_message_text("Tudo certo. A escolha do secretário foi cancelada.")
        return
    nivel = str(get_nivel(telegram_id))
    lojas_existentes = listar_lojas(telegram_id, include_todas=(nivel == "3")) or []
    await query.edit_message_text(
        text=_resumo_evento_md(dados),
        parse_mode="MarkdownV2",
        reply_markup=_teclado_rascunho_evento(dados, nivel, lojas_existentes),
    )


def _rotulo_modo_visual_evento(modo: str) -> str:
    return {
        "template_padrao": "Arte sugerida pelo sistema",
        "template_loja": "Template da loja",
        "card_especial": "Arte pronta da sessão",
    }.get(_norm_text(modo), "Template da loja")


def _teclado_visual_rascunho_evento(nivel: str, salvar_loja: bool) -> InlineKeyboardMarkup:
    sufixo = "com_loja" if salvar_loja else "sem_loja"
    linhas: List[List[InlineKeyboardButton]] = []
    linhas.append([InlineKeyboardButton("Arte sugerida pelo sistema", callback_data=f"draft_evento_visual|template_padrao|{sufixo}")])
    linhas.append([InlineKeyboardButton("Template da loja", callback_data=f"draft_evento_visual|template_loja|{sufixo}")])
    linhas.append([InlineKeyboardButton("Arte pronta da sessão", callback_data=f"draft_evento_visual|card_especial|{sufixo}")])
    linhas.append([InlineKeyboardButton("Voltar ao resumo", callback_data="draft_evento_visual_voltar")])
    linhas.append([InlineKeyboardButton("Cancelar", callback_data="draft_evento_cancelar")])
    return InlineKeyboardMarkup(linhas)


def _loja_do_rascunho_evento(dados: Dict[str, Any], lojas_existentes: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    loja_id = _norm_text(dados.get("loja_id"))
    if loja_id:
        for loja in lojas_existentes:
            if _norm_text(loja.get("ID") or loja.get("id")) == loja_id:
                return loja

    nome = _norm_text(dados.get("nome_loja"))
    numero = _norm_text(dados.get("numero_loja") or "0")
    if not nome:
        return None
    for loja in lojas_existentes:
        if (
            _norm_text(loja.get("Nome da Loja") or loja.get("nome")) == nome
            and _norm_text(loja.get("Numero") or loja.get("Número") or loja.get("numero") or "0") == numero
        ):
            return loja
    return None


def _template_url_loja(loja: Optional[Dict[str, Any]]) -> str:
    if not loja:
        return ""
    direto = _norm_text(loja.get("Template sessão URL") or loja.get("template_sessao_url"))
    if direto:
        return direto
    for chave, valor in loja.items():
        chave_norm = _norm_text(chave).lower()
        if "template" in chave_norm and "url" in chave_norm:
            url = _norm_text(valor)
            if url:
                return url
    return ""


def _teclado_template_loja_indisponivel(loja_id: str, origem: str) -> InlineKeyboardMarkup:
    linhas: List[List[InlineKeyboardButton]] = []
    if loja_id:
        linhas.append([InlineKeyboardButton("Enviar template da loja agora", callback_data=f"loja_template_pos|{loja_id}")])
    linhas.append([InlineKeyboardButton("Usar arte sugerida pelo sistema", callback_data=f"draft_evento_visual|template_padrao|{origem}")])
    linhas.append([InlineKeyboardButton("Voltar ao resumo", callback_data="draft_evento_visual_voltar")])
    return InlineKeyboardMarkup(linhas)


async def draft_evento_escolher_visual(update: Update, context, salvar_loja: bool) -> None:
    query = update.callback_query
    await query.answer()
    telegram_id = int(update.effective_user.id)
    dados = _obter_rascunho(_RASCUNHOS_EVENTO, telegram_id)
    if not dados:
        await query.answer("Não encontrei um rascunho de evento.", show_alert=True)
        return
    nivel = str(get_nivel(telegram_id))
    if nivel == "3" and not _norm_text(dados.get("secretario_responsavel_id")):
        await query.answer("Defina primeiro o secretário responsável.", show_alert=True)
        return
    await query.edit_message_text(
        "Escolha como a sessão será publicada no grupo:",
        reply_markup=_teclado_visual_rascunho_evento(nivel, salvar_loja),
    )


async def draft_evento_escolher_visual_com_loja(update: Update, context) -> None:
    await draft_evento_escolher_visual(update, context, salvar_loja=True)


async def draft_evento_escolher_visual_sem_loja(update: Update, context) -> None:
    await draft_evento_escolher_visual(update, context, salvar_loja=False)


async def draft_evento_visual_voltar(update: Update, context) -> None:
    query = update.callback_query
    await query.answer()
    telegram_id = int(update.effective_user.id)
    dados = _obter_rascunho(_RASCUNHOS_EVENTO, telegram_id)
    if not dados:
        await query.edit_message_text("Tudo certo. Não encontrei um rascunho ativo.")
        return
    nivel = str(get_nivel(telegram_id))
    lojas_existentes = listar_lojas(telegram_id, include_todas=(nivel == "3")) or []
    await query.edit_message_text(
        text=_resumo_evento_md(dados),
        parse_mode="MarkdownV2",
        reply_markup=_teclado_rascunho_evento(dados, nivel, lojas_existentes),
    )


async def draft_evento_definir_visual(update: Update, context) -> None:
    query = update.callback_query
    await query.answer("Processando...")
    telegram_id = int(update.effective_user.id)
    dados = _obter_rascunho(_RASCUNHOS_EVENTO, telegram_id)
    if not dados:
        await query.answer("Não encontrei um rascunho de evento.", show_alert=True)
        return
    partes = (query.data or "").split("|", 2)
    if len(partes) != 3:
        await query.answer("Opção visual inválida.", show_alert=True)
        return
    _, modo_visual, origem = partes
    nivel = str(get_nivel(telegram_id))
    if modo_visual not in {"template_loja", "template_padrao", "card_especial"}:
        await query.answer("Opção visual inválida.", show_alert=True)
        return
    if modo_visual == "template_loja":
        lojas_existentes = listar_lojas(telegram_id, include_todas=(nivel == "3")) or []
        loja = _loja_do_rascunho_evento(dados, lojas_existentes)
        template_url = _template_url_loja(loja)
        if not template_url:
            loja_id = _norm_text((loja or {}).get("ID") or (loja or {}).get("id") or dados.get("loja_id"))
            await query.edit_message_text(
                "Esta loja ainda não tem Template da loja configurado. Envie o template agora no privado ou use a arte sugerida pelo sistema para esta sessão.",
                reply_markup=_teclado_template_loja_indisponivel(loja_id, origem),
            )
            return
    dados["modo_visual"] = modo_visual
    if modo_visual != "card_especial":
        dados.pop("card_especial_url", None)
    _salvar_rascunho(_RASCUNHOS_EVENTO, telegram_id, dados)
    if modo_visual == "card_especial" and not _norm_text(dados.get("card_especial_url")):
        context.user_data["draft_evento_arte_pronta_origem"] = origem
        await query.edit_message_text(
            "Envie agora a arte pronta da sessão como foto ou documento de imagem. O bot publicará a imagem no grupo e adicionará apenas os botões de confirmação e gerenciamento.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Cancelar", callback_data="draft_evento_cancelar")]]),
        )
        return
    await _confirmar_evento(update, context, salvar_loja=(origem == "com_loja"))


async def receber_arte_pronta_evento(update: Update, context) -> None:
    msg = update.message
    origem = context.user_data.get("draft_evento_arte_pronta_origem")
    if not msg or not origem:
        return
    telegram_id = int(update.effective_user.id)
    dados = _obter_rascunho(_RASCUNHOS_EVENTO, telegram_id)
    if not dados:
        context.user_data.pop("draft_evento_arte_pronta_origem", None)
        await msg.reply_text("Não encontrei um rascunho de sessão ativo.")
        return
    tg_file = None
    filename = "arte_evento.jpg"
    content_type = "image/jpeg"
    if msg.photo:
        tg_file = await msg.photo[-1].get_file()
    elif msg.document and (msg.document.mime_type or "").startswith("image/"):
        tg_file = await msg.document.get_file()
        filename = msg.document.file_name or filename
        content_type = msg.document.mime_type or mimetypes.guess_type(filename)[0] or "image/jpeg"
    if not tg_file:
        await msg.reply_text("Envie uma imagem válida como foto ou documento.")
        return
    raw = await tg_file.download_as_bytearray()
    try:
        Image.open(BytesIO(raw)).verify()
    except Exception:
        await msg.reply_text("Não consegui validar essa imagem. Envie PNG, JPG ou WEBP.")
        return
    ext = os.path.splitext(filename)[1].lower() or ".jpg"
    if ext not in (".jpg", ".jpeg", ".png", ".webp"):
        ext = ".jpg"
    path = f"eventos/drafts/{telegram_id}/arte_pronta{ext}"
    url = upload_storage_publico(BUCKET_EVENT_CARDS, path, bytes(raw), content_type)
    if not url:
        await msg.reply_text(
            "Storage de cards indisponível; use arte sugerida pelo sistema por enquanto.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("Usar arte sugerida pelo sistema", callback_data=f"draft_evento_visual|template_padrao|{origem}")
            ]]),
        )
        return
    dados["modo_visual"] = "card_especial"
    dados["card_especial_url"] = url
    _salvar_rascunho(_RASCUNHOS_EVENTO, telegram_id, dados)
    context.user_data.pop("draft_evento_arte_pronta_origem", None)
    await msg.reply_text(
        "Arte pronta da sessão recebida. Publique quando estiver pronto.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Publicar com arte pronta", callback_data=f"draft_evento_visual|card_especial|{origem}")]]),
    )


async def _publicar_e_finalizar_bg(
    context,
    id_evento: str,
    evento: Dict[str, Any],
    query_chat_id: int,
    query_message_id: int,
    telegram_id: int,
) -> None:
    logger.info("Iniciando background task _publicar_e_finalizar_bg para o evento %s", id_evento)
    try:
        # Processar conquistas coletivas ANTES de publicar no grupo
        try:
            from src.conquistas_coletivas import processar_conquistas_coletivas_evento
            await processar_conquistas_coletivas_evento(context.bot, evento)
        except Exception as e_col:
            logger.warning("Falha silenciosa ao processar conquistas coletivas do evento: %s", e_col)

        # Publica no grupo
        logger.info("Chamando _publicar_evento_no_grupo para o evento %s", id_evento)
        await _publicar_evento_no_grupo(context, id_evento, evento)
        logger.info("Sucesso em _publicar_evento_no_grupo para o evento %s", id_evento)

        # Atualiza a mensagem original no privado indicando sucesso
        try:
            await context.bot.edit_message_text(
                chat_id=query_chat_id,
                message_id=query_message_id,
                text="✅ Sessão publicada com sucesso no grupo."
            )
        except Exception as e:
            logger.warning("Não foi possível editar a mensagem de confirmação no chat privado: %s", e)


    except Exception as e:
        logger.exception("Erro em _publicar_e_finalizar_bg para o evento %s: %s", id_evento, e)
        try:
            await context.bot.edit_message_text(
                chat_id=query_chat_id,
                message_id=query_message_id,
                text="❌ A sessão foi salva, mas ocorreu um erro ao gerar a imagem e publicar no grupo."
            )
        except Exception as e_msg:
            logger.warning("Não foi possível enviar mensagem de erro da publicação: %s", e_msg)


async def _confirmar_evento(update: Update, context, salvar_loja: bool) -> None:
    query = update.callback_query
    telegram_id = int(update.effective_user.id)
    dados = _obter_rascunho(_RASCUNHOS_EVENTO, telegram_id)
    if not dados:
        await query.answer("Não encontrei um rascunho de evento.", show_alert=True)
        return
    nivel = str(get_nivel(telegram_id))
    secretario_id = _norm_text(dados.get("secretario_responsavel_id")) or str(telegram_id)
    if nivel == "3" and not _norm_text(dados.get("secretario_responsavel_id")):
        await query.answer("Defina primeiro o secretário responsável.", show_alert=True)
        return
    lojas_existentes = listar_lojas(telegram_id, include_todas=(nivel == "3")) or []
    dados = _aplicar_loja_cadastrada_ao_evento(dados, lojas_existentes)
    
    # Validação do limite de 4 sessões ativas por Loja ou por Secretário
    if nivel != "3":
        from src.sheets_supabase import contar_sessoes_ativas_loja, contar_sessoes_ativas_secretario
        if (contar_sessoes_ativas_loja(dados.get("loja_id"), dados.get("nome_loja"), dados.get("numero_loja"), dados.get("potencia")) >= 4 or
            contar_sessoes_ativas_secretario(telegram_id) >= 4):
            msg_limite = (
                "⚠️ *LIMITE DE SESSÕES ATIVAS ATINGIDO*\n\n"
                "Ir.·. Secretário, identificamos que você ou esta Oficina já possui 4 ou mais sessões futuras/ativas cadastradas.\n\n"
                "Para manter o calendário dinâmico e evitar o acúmulo de informações, o sistema limita a publicação a no máximo 4 sessões futuras ativas por Loja ou por Secretário.\n\n"
                "Aguarde a realização de alguma sessão atual ou cancele uma existente para cadastrar novos convites. Publicar poucas sessões mantém a agenda útil e evita despejar o calendário anual de uma vez."
            )
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup
            await query.edit_message_text(
                text=msg_limite,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Voltar", callback_data="menu_principal")]])
            )
            return
        
    secretario_id = _norm_text(dados.get("secretario_responsavel_id")) or secretario_id
    loja_existente = not _evento_tem_loja_nova(dados, lojas_existentes)
    if salvar_loja and loja_existente:
        await query.answer("Esta loja já existe. A sessão será vinculada ao cadastro existente.", show_alert=True)
        salvar_loja = False
    if salvar_loja and _evento_tem_loja_nova(dados, lojas_existentes):
        ok_loja = cadastrar_loja(
            telegram_id,
            {
                "nome": dados.get("nome_loja"),
                "numero": dados.get("numero_loja"),
                "oriente": dados.get("oriente"),
                "rito": dados.get("rito"),
                "potencia": dados.get("potencia"),
                "potencia_complemento": dados.get("potencia_complemento") or dados.get("potencia_outra") or "",
                "endereco": dados.get("endereco"),
                "secretario_responsavel_id": secretario_id,
                "secretario_responsavel_nome": _norm_text(dados.get("secretario_responsavel_nome")),
                "vinculo_atualizado_por_id": str(telegram_id),
            },
        )
        if not ok_loja:
            await query.answer("Não consegui salvar a loja vinculada a esta sessão.", show_alert=True)
            return

        # Hook Conquistas Coletivas
        try:
            from src.conquistas import checar_e_disparar_marco_coletivo
            asyncio.create_task(checar_e_disparar_marco_coletivo(context.bot, {
                "nome": dados.get("nome_loja"),
                "oriente": dados.get("oriente")
            }))
        except Exception:
            pass
    evento = _payload_evento(dados, secretario_id)
    id_evento = cadastrar_evento(evento)
    if not id_evento:
        await query.answer("Não consegui registrar a sessão agora.", show_alert=True)
        return

    _limpar_rascunho(_RASCUNHOS_EVENTO, telegram_id)
    await query.edit_message_text("⏳ Publicando no grupo...")

    query_chat_id = query.message.chat_id
    query_message_id = query.message.message_id

    task = asyncio.create_task(
        _publicar_e_finalizar_bg(
            context,
            id_evento,
            evento,
            query_chat_id,
            query_message_id,
            telegram_id,
        )
    )
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)


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
    await query.edit_message_text("Tudo certo. O rascunho da sessão foi cancelado.")


def _teclado_secretarios(prefixo: str, secretarios: List[Dict[str, Any]]) -> InlineKeyboardMarkup:
    linhas: List[List[InlineKeyboardButton]] = []
    for sec in secretarios[:30]:
        sid = _norm_text(sec.get("telegram_id"))
        nome = _norm_text(sec.get("nome") or sid)
        if sid:
            linhas.append([InlineKeyboardButton(f"👤 {nome}", callback_data=f"{prefixo}|{sid}")])
    linhas.append([InlineKeyboardButton("❌ Cancelar", callback_data=f"{prefixo}_cancelar")])
    return InlineKeyboardMarkup(linhas)


def _evento_tem_loja_nova(dados: Dict[str, Any], lojas_existentes: List[Dict[str, Any]]) -> bool:
    loja_id = _norm_text(dados.get("loja_id"))
    if loja_id:
        for loja in lojas_existentes:
            if _norm_text(loja.get("ID") or loja.get("id")) == loja_id:
                return False
    from src.sheets_supabase import padronizar_nome_loja
    nome = _norm_text(padronizar_nome_loja(dados.get("nome_loja")))
    numero = _norm_text(dados.get("numero_loja") or "0")
    rito = _norm_text(dados.get("rito"))
    potencia = _norm_text(dados.get("potencia"))
    potencia_complemento = _norm_text(dados.get("potencia_complemento") or dados.get("potencia_outra"))
    if not nome:
        return False
    for loja in lojas_existentes:
        loja_potencia = _norm_text(loja.get("Potência") or loja.get("potencia"))
        loja_complemento = _norm_text(loja.get("Potência complemento") or loja.get("potencia_complemento"))
        if (
            _norm_text(padronizar_nome_loja(loja.get("Nome da Loja") or loja.get("nome_loja"))) == nome
            and _norm_text(loja.get("Número") or "0") == numero
            and _norm_text(loja.get("Rito") or loja.get("rito")) == rito
            and (not potencia or loja_potencia == potencia)
            and (not potencia_complemento or loja_complemento == potencia_complemento)
        ):
            return False
    return True


def _resumo_evento_md(dados: Dict[str, Any]) -> str:
    numero_loja = _norm_text(dados.get("numero_loja") or "0")
    numero_fmt = f" {_escape_md(numero_loja)}" if numero_loja and numero_loja != "0" else ""
    responsavel = _norm_text(dados.get("secretario_responsavel_nome") or dados.get("secretario_responsavel_id"))
    linha_resp = f"*Secretário responsável:* {_escape_md(responsavel)}\n" if responsavel else ""
    obs = _norm_text(dados.get("observacoes"))
    linha_obs = f"*Ordem do dia / observações:* {_escape_md(obs)}\n" if obs else ""
    grau = dados.get("grau_outro") if _norm_text(dados.get("grau")) == "Outro" else dados.get("grau", "")
    traje = dados.get("traje_outro") if _norm_text(dados.get("traje")) == "Outro" else dados.get("traje", "")
    rito = dados.get("rito_outro") if _norm_text(dados.get("rito")) == "Outro" else dados.get("rito", "")
    potencia = _potencia_resumo(dados)
    return (
        "📋 *Confirme a sessão antes de publicar*\n\n"
        f"*Data:* {_escape_md(dados.get('data', ''))}\n"
        f"*Horário:* {_escape_md(dados.get('horario', ''))}\n"
        f"*Grau da sessão:* {_escape_md(grau or '')}\n"
        f"*Tipo de sessão:* {_escape_md(dados.get('tipo_sessao', ''))}\n"
        f"*Traje:* {_escape_md(traje or '')}\n"
        f"*Ágape:* {_escape_md(dados.get('agape', ''))}\n"
        f"{linha_obs}"
        f"*Loja:* {_escape_md(dados.get('nome_loja', ''))}{numero_fmt}\n"
        f"*Oriente:* {_escape_md(dados.get('oriente', ''))}\n"
        f"*Rito:* {_escape_md(rito or '')}\n"
        f"*Potência local:* {_escape_md(potencia or '')}\n"
        f"*Endereço:* {_escape_md(dados.get('endereco', ''))}\n"
        f"{linha_resp}"
    )


def _resumo_evento_texto(dados: Dict[str, Any]) -> str:
    numero_loja = _norm_text(dados.get("numero_loja") or "0")
    numero_fmt = f" {numero_loja}" if numero_loja and numero_loja != "0" else ""
    responsavel = _norm_text(dados.get("secretario_responsavel_nome") or dados.get("secretario_responsavel_id"))
    obs = _norm_text(dados.get("observacoes")) or "-"
    grau = dados.get("grau_outro") if _norm_text(dados.get("grau")) == "Outro" else dados.get("grau", "")
    traje = dados.get("traje_outro") if _norm_text(dados.get("traje")) == "Outro" else dados.get("traje", "")
    rito = dados.get("rito_outro") if _norm_text(dados.get("rito")) == "Outro" else dados.get("rito", "")
    potencia = _potencia_resumo(dados)
    linhas = [
        "Confirme a sessão antes de publicar",
        "",
        f"Data: {dados.get('data', '')}",
        f"Horário: {dados.get('horario', '')}",
        f"Grau da sessão: {grau or ''}",
        f"Tipo de sessão: {dados.get('tipo_sessao', '')}",
        f"Traje: {traje or ''}",
        f"Ágape: {dados.get('agape', '')}",
        f"Ordem do dia / observações: {obs}",
        f"Loja: {dados.get('nome_loja', '')}{numero_fmt}",
        f"Oriente: {dados.get('oriente', '')}",
        f"Rito: {rito or ''}",
        f"Potência local: {potencia or ''}",
        f"Endereço: {dados.get('endereco', '')}",
    ]
    if responsavel:
        linhas.append(f"Secretário responsável: {responsavel}")
    return "\n".join(linhas)



def _teclado_rascunho_evento(dados: Dict[str, Any], nivel: str, lojas_existentes: List[Dict[str, Any]]) -> InlineKeyboardMarkup:
    linhas: List[List[InlineKeyboardButton]] = []
    if str(nivel) == "3" and not _norm_text(dados.get("secretario_responsavel_id")):
        linhas.append([InlineKeyboardButton("👤 Definir secretário responsável", callback_data="draft_evento_escolher_secretario")])
    else:
        if _evento_tem_loja_nova(dados, lojas_existentes):
            linhas.append([InlineKeyboardButton("✅ Publicar e salvar loja", callback_data="draft_evento_escolher_visual_com_loja")])
            linhas.append([InlineKeyboardButton("✅ Publicar sem salvar loja", callback_data="draft_evento_escolher_visual_sem_loja")])
        else:
            linhas.append([InlineKeyboardButton("✅ Publicar no grupo", callback_data="draft_evento_escolher_visual_sem_loja")])
    linhas.append([_botao_editar_webapp("✏️ Editar formulário", WEBAPP_URL_EVENTO)])
    linhas.append([InlineKeyboardButton("❌ Cancelar", callback_data="draft_evento_cancelar")])
    return InlineKeyboardMarkup(linhas)


async def _enviar_resumo_rascunho_membro(telegram_app, telegram_id: int) -> None:
    dados = _obter_rascunho(_RASCUNHOS_MEMBRO, telegram_id)
    if not dados:
        return
    user_data = telegram_app.user_data.get(telegram_id) or {}
    readonly_loja = bool(user_data.get("cadastro_readonly_loja"))
    
    await telegram_app.bot.send_message(
        chat_id=telegram_id,
        text=_resumo_membro_md(dados),
        parse_mode="MarkdownV2",
        reply_markup=_teclado_rascunho_membro(readonly_loja),
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
    teclado = _teclado_rascunho_evento(dados, nivel, lojas_existentes)
    try:
        msg = await bot.send_message(
            chat_id=telegram_id,
            text=_resumo_evento_md(dados),
            parse_mode="MarkdownV2",
            reply_markup=teclado,
        )
        logger.info("miniapp.evento.revisao.telegram.ok telegram_id=%s message_id=%s modo=markdownv2", telegram_id, getattr(msg, "message_id", ""))
    except Exception as e:
        logger.warning("Falha ao enviar revisão de evento com MarkdownV2 para %s: %s", telegram_id, e)
        msg = await bot.send_message(
            chat_id=telegram_id,
            text=_resumo_evento_texto(dados),
            reply_markup=teclado,
        )
        logger.info("miniapp.evento.revisao.telegram.ok telegram_id=%s message_id=%s modo=texto", telegram_id, getattr(msg, "message_id", ""))


# ─────────────────────────────────────────────────────────────────────────────
# VERIFICAÇÃO DE SEGURANÇA (HMAC-SHA256 — padrão Telegram Mini App)
# ─────────────────────────────────────────────────────────────────────────────

def verify_telegram_webapp_data(init_data: str, bot_token: str) -> Optional[dict]:
    """
    Verifica a assinatura do initData conforme:
    https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app

    Retorna o dict do usuário Telegram se válido; None caso contrário.
    Rejeita tokens com mais de 24 h (proteção contra replay attacks).
    """
    if not init_data or not bot_token:
        return None
    try:
        # parse_qsl URL-decodifica os valores automaticamente — obrigatório para
        # que o data_check_string bata com o que o Telegram assinou.
        params: Dict[str, str] = dict(parse_qsl(init_data, strict_parsing=False))

        hash_value = params.pop("hash", "")
        if not hash_value:
            return None

        # auth_date não pode ser muito antigo (24 h)
        auth_date = int(params.get("auth_date", 0))
        if time.time() - auth_date > 86400:
            logger.warning("initData expirado (auth_date=%s)", auth_date)
            return None

        # String de verificação: pares chave=valor ordenados por chave, separados por \n
        data_check = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))

        # Chave secreta: HMAC-SHA256("WebAppData", bot_token)
        secret = hmac.new(b"WebAppData", bot_token.encode("utf-8"), digestmod=hashlib.sha256).digest()
        expected = hmac.new(secret, data_check.encode("utf-8"), digestmod=hashlib.sha256).hexdigest()

        if not hmac.compare_digest(expected, hash_value):
            logger.warning("Assinatura initData inválida.")
            return None

        # parse_qsl já decodificou o valor de "user"; só precisa fazer o parse JSON
        return json.loads(params.get("user", "{}"))

    except Exception as e:
        logger.warning("Erro na verificação initData: %s", e)
        return None


# ─────────────────────────────────────────────────────────────────────────────
# FUNÇÕES AUXILIARES INTERNAS
# ─────────────────────────────────────────────────────────────────────────────

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
    """Teclado de confirmação de presença publicado no grupo (mesmo padrão do fluxo conversacional)."""
    tipo = (agape_str or "").lower()
    linhas: List[List[InlineKeyboardButton]] = []
    if "gratuito" in tipo:
        linhas.append([InlineKeyboardButton("🍽 Participar com ágape (gratuito)", callback_data=f"confirmar|{id_evento}|gratuito")])
        linhas.append([InlineKeyboardButton("🚫 Participar sem ágape", callback_data=f"confirmar|{id_evento}|sem")])
    elif "pago" in tipo:
        linhas.append([InlineKeyboardButton("🍽 Participar com ágape (pago)", callback_data=f"confirmar|{id_evento}|pago")])
        linhas.append([InlineKeyboardButton("🚫 Participar sem ágape", callback_data=f"confirmar|{id_evento}|sem")])
    else:
        linhas.append([InlineKeyboardButton("✅ Confirmar presença", callback_data=f"confirmar|{id_evento}|sem")])
    linhas.append([InlineKeyboardButton("👥 Ver confirmados", callback_data=f"ver_confirmados|{id_evento}")])
    return InlineKeyboardMarkup(linhas)


# ─────────────────────────────────────────────────────────────────────────────
# ESTILOS E JS BASE COMPARTILHADOS
# ─────────────────────────────────────────────────────────────────────────────

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
.hidden{display:none!important}
.readonly-field{opacity:.72}
.loja-resumo{font-size:14px;line-height:1.45;margin-top:8px}
.loja-resumo strong{display:block;font-size:15px;margin-bottom:2px}
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
  if(tg && tg.MainButton && tg.MainButton.isVisible){
    if(isLoading){
      try{ tg.MainButton.showProgress(); }catch(e){}
      try{ tg.MainButton.disable(); }catch(e){}
    }else{
      try{ tg.MainButton.hideProgress(); }catch(e){}
      try{ tg.MainButton.enable(); }catch(e){}
    }
  }
  const btn=document.getElementById('btn_publicar_evento');
  if(btn){
    btn.disabled=!!isLoading;
    btn.textContent=isLoading?'Enviando...':'Salvar rascunho e continuar no Telegram';
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
  if(!v){setErr(id,label+' é obrigatório.');return false;}
  clearErr(id);return true;
}
function scrollToFirstError(){
  const firstErr = Array.from(document.querySelectorAll('.err.on')).find(el => {
    return el.offsetWidth > 0 || el.offsetHeight > 0;
  });
  if(firstErr){
    firstErr.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }
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
        f'<title>{title} — Bode Andarilho</title>'
        f'<script src="https://telegram.org/js/telegram-web-app.js"></script>'
        f'<style>{_CSS}</style></head>'
        f'<body><h1>🐐 {title}</h1>'
        f'{body}'
        f'<div id="toast" class="toast"></div>'
        f'<script>{_JS_BASE}{script}</script>'
        f'</body></html>'
    )


# ─────────────────────────────────────────────────────────────────────────────
# HTML — CADASTRO DE MEMBRO
# ─────────────────────────────────────────────────────────────────────────────

def html_cadastro_membro() -> str:
    body = """
<div class="card">
  <div class="info">Após preencher, o bot enviará um resumo no chat para confirmação final. O template visual é opcional e poderá ser enviado depois.</div>
</div>
<div id="lojas_membro_card" class="card" style="display:none">
  <div class="card-title">Sua Loja</div>
  <div class="field">
    <label for="loja_sel_membro">Selecione sua loja cadastrada</label>
    <select id="loja_sel_membro">
      <option value="">Preencher manualmente...</option>
    </select>
    <div class="info">Se preferir, você pode seguir com o preenchimento manual logo abaixo.</div>
  </div>
</div>
<div class="card">
  <div class="card-title">Identificação</div>
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
      <option value="Não">Não</option>
    </select>
    <div id="mi_err" class="err"></div>
  </div>
  <div class="field">
    <label for="vm">Venerável Mestre? *</label>
    <select id="vm">
      <option value="">Selecione...</option>
      <option value="Sim">Sim</option>
      <option value="Não">Não</option>
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
    <label for="numero_loja">Número <span class="info">(0 se não houver)</span></label>
    <input id="numero_loja" type="text" value="0" inputmode="numeric" maxlength="8">
  </div>
  <div class="field">
    <label for="oriente">Oriente *</label>
    <input id="oriente" type="text" placeholder="Ex.: São Paulo / SP">
    <div id="oriente_err" class="err"></div>
  </div>
  <div class="field">
    <label for="potencia">Potência *</label>
    <select id="potencia">
      <option value="">Selecione...</option>
      <option value="GOB">GOB</option>
      <option value="CMSB">CMSB</option>
      <option value="COMAB">COMAB</option>
    </select>
    <div id="potencia_err" class="err"></div>
  </div>
  <div class="field" id="potencia_outra_wrap" style="display:none">
    <label for="potencia_outra">Potência local *</label>
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
    setErr('data_nasc','Use uma data válida no formato DD/MM/AAAA.');ok=false;
  }else clearErr('data_nasc');
  ok=req('grau','Grau')&&ok;
  ok=req('mi','Mestre Instalado')&&ok;
  ok=req('vm','Venerável Mestre')&&ok;
  ok=req('loja','Nome da loja')&&ok;
  ok=req('oriente','Oriente')&&ok;
  ok=req('potencia','Potência principal')&&ok;
  if (!document.getElementById('potencia_outra').readOnly) {
    ok=req('potencia_outra','Potência local')&&ok;
  }
  
  if(!ok) {
    showToast('Verifique os campos obrigatórios em vermelho.', 4000);
    setTimeout(scrollToFirstError, 100);
  }
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
  tg.MainButton.setText('Continuar para revisão');
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
    }catch{showToast('Falha de conexão. Tente novamente.');tg.MainButton.hideProgress();tg.MainButton.enable();}
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
      if(j.draft.readonly_loja){
        document.getElementById('loja').readOnly = true;
        document.getElementById('numero_loja').readOnly = true;
        document.getElementById('potencia').style.pointerEvents = 'none';
        document.getElementById('potencia').style.opacity = '0.7';
        if(document.getElementById('potencia_outra')) {
          const el = document.getElementById('potencia_outra');
          const potVal = document.getElementById('potencia') ? document.getElementById('potencia').value : '';
          const emptyComplement = !el.value && ['GOB','CMSB','COMAB'].includes(potVal);
          el.readOnly = !emptyComplement;
          if (emptyComplement) {
            el.classList.remove('readonly-field');
          }
        }
        if(document.getElementById('lojas_membro_card')) document.getElementById('lojas_membro_card').style.display = 'none';
      }
      syncPotenciaOutra();
    }
  }catch(e){}
})();
"""
    return _html_wrap("Registro de Obreiro", body, script)



def html_cadastro_loja() -> str:
    body = """
<div class="card">
  <div class="info">Após preencher, o bot enviará um resumo no chat para confirmação final.</div>
</div>
<div class="card">
  <div class="card-title">Dados da Loja</div>
  <div class="field">
    <label for="nome_loja">Nome da loja *</label>
    <input id="nome_loja" type="text" placeholder="Ex.: Luz da Fraternidade">
    <div id="nome_loja_err" class="err"></div>
  </div>
  <div class="field">
    <label for="numero">Número <span class="info">(0 se não houver)</span></label>
    <input id="numero" type="text" value="0" inputmode="numeric" maxlength="8">
  </div>
  <div class="field">
    <label for="oriente">Oriente *</label>
    <input id="oriente" type="text" placeholder="Ex.: São Paulo / SP">
    <div id="oriente_err" class="err"></div>
  </div>
  <div class="field">
    <label for="rito">Rito *</label>
    <select id="rito">
      <option value="">Selecione...</option>
      <option value="REAA">REAA (Escocês)</option>
      <option value="York">York</option>
      <option value="Schröder">Schröder</option>
      <option value="Adonhiramita">Adonhiramita</option>
      <option value="Brasileiro">Brasileiro</option>
      <option value="Moderno">Moderno</option>
      <option value="Escocês Retificado">Escocês Retificado</option>
      <option value="MLAA">MLAA (Maçons Livres Antigos e Aceitos)</option>
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
    <label for="potencia">Potência *</label>
    <select id="potencia">
      <option value="">Selecione...</option>
      <option value="GOB">GOB</option>
      <option value="CMSB">CMSB</option>
      <option value="COMAB">COMAB</option>
    </select>
    <div id="potencia_err" class="err"></div>
  </div>
  <div class="field" id="potencia_outra_wrap" style="display:none">
    <label for="potencia_outra">Potência local *</label>
    <input id="potencia_outra" type="text" placeholder="Ex.: GOB-RS, GLMERGS, GORGS">
    <div id="potencia_outra_err" class="err"></div>
  </div>
  <div class="field">
    <label for="endereco">Endereço da loja ou link do Google Maps *</label>
    <input id="endereco" type="text" placeholder="Ex.: https://maps.app.goo.gl/... ou Rua X, 123 - Centro">
    <div id="endereco_err" class="err"></div>
    <div class="info">Preferencialmente, cole o link do Google Maps para facilitar a localização exata.</div>
  </div>
</div>
"""
    script = """
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

function validate(){
  let ok=true;
  ok=req('nome_loja','Nome da loja')&&ok;
  ok=req('oriente','Oriente')&&ok;
  ok=req('rito','Rito')&&ok;
  if(val('rito')==='Outro') ok=req('rito_outro','Rito')&&ok;
  ok=req('potencia','Potência principal')&&ok;
  ok=req('potencia_outra','Potência local')&&ok;
  ok=req('endereco','Endereço')&&ok;
  
  if(!ok) {
    showToast('Verifique os campos obrigatórios em vermelho.', 4000);
    setTimeout(scrollToFirstError, 100);
  }
  return ok;
}
function syncPotenciaComplemento(){
  const wrap=document.getElementById('potencia_outra_wrap');
  if(wrap)wrap.style.display=val('potencia')?'block':'none';
}
document.getElementById('potencia').addEventListener('change',syncPotenciaComplemento);
syncPotenciaComplemento();
document.getElementById('rito').addEventListener('change',()=>syncOutro('rito','rito_outro_wrap','rito_outro','Outro'));
syncOutro('rito','rito_outro_wrap','rito_outro','Outro');

if(tg && tg.MainButton){
tg.MainButton.setText('Continuar para revisão');
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
        rito_outro:val('rito_outro'),
        potencia:val('potencia'),
        potencia_outra:val('potencia_outra'),
        endereco:val('endereco')
      })
    });
    const j=await r.json();
    if(j.ok){closeMiniAppSafe();}
    else{showToast(j.error||'Erro. Tente novamente.');tg.MainButton.hideProgress();tg.MainButton.enable();}
  }catch{showToast('Falha de conexão. Tente novamente.');tg.MainButton.hideProgress();tg.MainButton.enable();}
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
      if(j.draft.rito)aplicarValorComOutro('rito','rito_outro','rito_outro_wrap',j.draft.rito_outro||j.draft.rito,'Outro');
      if(j.draft.potencia)document.getElementById('potencia').value=j.draft.potencia;
      if(j.draft.endereco)document.getElementById('endereco').value=j.draft.endereco;
    }
  }catch(e){}
})();
"""
    return _html_wrap("Registro de Loja", body, script)


# ─────────────────────────────────────────────────────────────────────────────
# HTML — CADASTRO DE EVENTO
# ─────────────────────────────────────────────────────────────────────────────

def html_cadastro_evento() -> str:
    body = """
<div class="card">
  <div class="info">Preencha os dados e continue. A publicação final será confirmada no chat do bot.</div>
</div>
</div>

<div class="card">

<div class="card">
  <div class="card-title">A sessão</div>
  <div class="field">
    <label for="data_ev">Data * <span class="info">(DD/MM/AAAA)</span></label>
    <input id="data_ev" type="text" placeholder="25/03/2026" maxlength="10" inputmode="numeric">
    <div id="data_ev_err" class="err"></div>
  </div>
  <div class="field">
    <label for="horario">Horário *</label>
    <input id="horario" type="time" value="19:30">
    <div id="horario_err" class="err"></div>
  </div>
  <div class="field">
    <label for="grau">Grau da sessão *</label>
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
    <label for="grau_outro">Informe o grau da sessão *</label>
    <input id="grau_outro" type="text" placeholder="Ex.: Câmara do Meio">
    <div id="grau_outro_err" class="err"></div>
  </div>
  <div class="field">
    <label for="tipo_sessao">Tipo de sessão *</label>
    <input id="tipo_sessao" type="text" placeholder="Ex.: Ordinária, Magna, Iniciação">
    <div id="tipo_sessao_err" class="err"></div>
  </div>
  <div class="field">
    <label for="traje">Traje *</label>
    <select id="traje">
      <option value="">Selecione...</option>
      <option value="Traje maçônico">Traje maçônico</option>
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
    <label for="agape">Ágape *</label>
    <select id="agape">
      <option value="">Selecione...</option>
      <option value="Nao">Não haverá ágape</option>
      <option value="Sim (Gratuito)">Sim - Gratuito</option>
      <option value="Sim (Pago)">Sim - Pago (dividido)</option>
    </select>
    <div id="agape_err" class="err"></div>
  </div>
  <div class="field">
    <label for="observacoes">Ordem do dia / observações <span class="info">(opcional)</span></label>
    <textarea id="observacoes" placeholder="Informações adicionais da sessão..."></textarea>
  </div>
  <div class="field">
    <label for="endereco">Endereço da sessão ou link do Google Maps *</label>
    <input id="endereco" type="text" placeholder="Ex.: https://maps.app.goo.gl/... ou Rua X, 123 - Centro">
    <div id="endereco_err" class="err"></div>
    <div class="info">Preferencialmente, cole o link do Google Maps para que o bot gere o atalho de mapa.</div>
  </div>
</div>

<div id="dados_loja_card" class="card">
  <div class="card-title">Dados da Loja</div>
  <div id="lojas_card" style="display:none; padding-bottom: 12px; border-bottom: 1px solid var(--border); margin-bottom: 16px;">
    <div id="lojas_admin_info" class="info" style="display:none">Selecione uma loja cadastrada, ou escolha "Cadastrar nova" para preencher manualmente.</div>
    <div class="field">
      <label for="loja_sel" style="font-weight:700">Loja pre-cadastrada:</label>
      <select id="loja_sel">
        <option value="">[ Cadastrar nova loja manualmente ]</option>
      </select>
      <div id="loja_sel_err" class="err"></div>
    </div>
  </div>
  <div class="field">
    <label for="nome_loja">Nome da loja *</label>
    <input id="nome_loja" type="text" placeholder="Ex.: Luz da Fraternidade">
    <div id="nome_loja_err" class="err"></div>
  </div>
  <div class="field">
    <label for="numero_loja">Número <span class="info">(0 se não houver)</span></label>
    <input id="numero_loja" type="text" value="0" inputmode="numeric" maxlength="8">
  </div>
  <div class="field">
    <label for="oriente">Oriente *</label>
    <input id="oriente" type="text" placeholder="Ex.: São Paulo / SP">
    <div id="oriente_err" class="err"></div>
  </div>
  <div class="field">
    <label for="rito">Rito *</label>
    <select id="rito">
      <option value="">Selecione...</option>
      <option value="REAA">REAA (Escocês)</option>
      <option value="York">York</option>
      <option value="Schröder">Schröder</option>
      <option value="Adonhiramita">Adonhiramita</option>
      <option value="Brasileiro">Brasileiro</option>
      <option value="Moderno">Moderno</option>
      <option value="Escocês Retificado">Escocês Retificado</option>
      <option value="MLAA">MLAA (Maçons Livres Antigos e Aceitos)</option>
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
    <label for="potencia">Potência *</label>
    <select id="potencia">
      <option value="">Selecione...</option>
      <option value="GOB">GOB</option>
      <option value="CMSB">CMSB</option>
      <option value="COMAB">COMAB</option>
    </select>
    <div id="potencia_err" class="err"></div>
  </div>
  <div class="field" id="potencia_outra_wrap" style="display:none">
    <label for="potencia_outra">Potência local *</label>
    <input id="potencia_outra" type="text" placeholder="Ex.: GOB-RS, GLMERGS, GORGS">
    <div id="potencia_outra_err" class="err"></div>
  </div>
</div>

<div id="acoes_publicacao" class="actions">
  <div class="actions-stack">
    <button id="btn_publicar_evento" type="button" class="btn-primary" onclick="publicarEvento()">Salvar rascunho e continuar no Telegram</button>
    <button id="btn_cancelar_evento" type="button" class="btn-secondary" onclick="closeMiniAppSafe()">Fechar</button>
    <button id="btn_ir_chat" type="button" class="btn-secondary" style="display:none">Voltar ao chat do bot</button>
  </div>
</div>
"""
    script = r"""
maskDate(document.getElementById('data_ev'));
let lojasCarregadas=[];
let lojaSelecionadaViaAtalho=false;
let lojaConfirmadaViaAtalho=false;
let adminFlow=false;
let novaLojaManual=false;
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

function selectedLoja(){
  const sel=document.getElementById('loja_sel');
  if(!sel||sel.value==='')return null;
  return lojasCarregadas[Number(sel.value)]||null;
}

function setLojaFieldsReadonly(readonly){
  ['nome_loja','numero_loja','oriente','rito','rito_outro','potencia','potencia_outra'].forEach(id=>{
    const el=document.getElementById(id);
    if(!el)return;
    let makeReadonly = !!readonly;
    if(id === 'potencia_outra' && readonly){
      const potVal = document.getElementById('potencia') ? document.getElementById('potencia').value : '';
      if(!el.value && ['GOB','CMSB','COMAB'].includes(potVal)){
        makeReadonly = false;
      }
    }
    el.readOnly=makeReadonly;
    if(el.tagName==='SELECT')el.disabled=makeReadonly;
    el.classList.toggle('readonly-field',makeReadonly);
    if(makeReadonly) clearErr(id);
  });
}

function renderLojaResumo(loja, isInit){
  if(!loja){
    setLojaFieldsReadonly(false);
    if(!isInit){
      ['nome_loja','oriente','rito','rito_outro','potencia','potencia_outra'].forEach(id=>{
        const el=document.getElementById(id);
        if(el) el.value='';
      });
      if(document.getElementById('numero_loja')) document.getElementById('numero_loja').value='0';
      syncOutro('rito','rito_outro_wrap','rito_outro','Outro');
      syncOutro('potencia','potencia_outra_wrap','potencia_outra','');
    }
    return;
  }
  setLojaFieldsReadonly(true);
}

(async()=>{
  try{
    const r=await fetch('/api/lojas',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({init_data:tgInitData()})
    });
    const j=await r.json();
    adminFlow=(j.nivel||'')==='3';
    const infoAdmin=document.getElementById('lojas_admin_info');
    const btnManual=document.getElementById('btn_nova_loja_manual');
    if(adminFlow){
      document.getElementById('lojas_card').style.display='block';
      if(infoAdmin)infoAdmin.style.display='block';
      renderLojaResumo(null,true);
    }
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
    }else if(adminFlow){
      showToast('Nenhuma loja cadastrada encontrada. Use o cadastro manual apenas para loja nova.');
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
      syncOutro('potencia','potencia_outra_wrap','potencia_outra','');
      if(jDraft.draft.endereco)document.getElementById('endereco').value=jDraft.draft.endereco;
      if(jDraft.draft.loja_id&&lojasCarregadas.length){
        const idx=lojasCarregadas.findIndex(l=>(l.id||'')===jDraft.draft.loja_id);
        if(idx>=0){
          document.getElementById('loja_sel').value=String(idx);
          lojaSelecionadaViaAtalho=true;
          lojaConfirmadaViaAtalho=true;
          novaLojaManual=false;
          renderLojaResumo(lojasCarregadas[idx]);
        }
      }else if(adminFlow&&jDraft.draft.nome_loja){
        novaLojaManual=true;
        renderLojaResumo(null,true);
      }
    }
  }catch(e){}
})();

document.getElementById('loja_sel').addEventListener('change',function(){
  if(!this.value){
    lojaSelecionadaViaAtalho=false;
    lojaConfirmadaViaAtalho=false;
    novaLojaManual=true;
    renderLojaResumo(null,false);
    return;
  }
  lojaSelecionadaViaAtalho=true;
  lojaConfirmadaViaAtalho=true;
  novaLojaManual=false;
  clearErr('loja_sel');
  const o=this.options[this.selectedIndex];
  const l=JSON.parse(o.dataset.loja||'{}');
  if(l.nome)document.getElementById('nome_loja').value=l.nome;
  if(l.numero)document.getElementById('numero_loja').value=l.numero;
  if(l.oriente)document.getElementById('oriente').value=l.oriente;
  if(l.rito)aplicarValorComOutro('rito','rito_outro','rito_outro_wrap',l.rito,'Outro');
  if(l.potencia)document.getElementById('potencia').value=l.potencia;
  document.getElementById('potencia_outra').value=l.potencia_complemento||'';
  syncOutro('potencia','potencia_outra_wrap','potencia_outra','');
  if(l.endereco)document.getElementById('endereco').value=l.endereco;
  renderLojaResumo(l);
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
    setErr('data_ev','Use uma data válida no formato DD/MM/AAAA.');ok=false;
  }else{
    const hoje=new Date();
    hoje.setHours(0,0,0,0);
    if(dataEvento<hoje){
      setErr('data_ev','A data da sessão não pode estar no passado.');ok=false;
    }else{
      clearErr('data_ev');
    }
  }
  ok=req('horario','Horário')&&ok;
  ok=req('grau','Grau da sessão')&&ok;
  if(val('grau')==='Outro') ok=req('grau_outro','Grau da sessão')&&ok;
  ok=req('tipo_sessao','Tipo de sessão')&&ok;
  ok=req('traje','Traje')&&ok;
  if(val('traje')==='Outro') ok=req('traje_outro','Traje')&&ok;
  ok=req('agape','Ágape')&&ok;
  ok=req('nome_loja','Nome da loja')&&ok;
  ok=req('oriente','Oriente')&&ok;
  ok=req('rito','Rito')&&ok;
  if(val('rito')==='Outro') ok=req('rito_outro','Rito')&&ok;
  ok=req('potencia','Potência principal')&&ok;
  if (!document.getElementById('potencia_outra').readOnly) {
    ok=req('potencia_outra','Potência local')&&ok;
  }
  ok=req('endereco','Endereço')&&ok;
  
  if(!ok) {
    showToast('Verifique os campos obrigatórios em vermelho.', 4000);
    setTimeout(scrollToFirstError, 100);
  }
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
        loja_id:(selectedLoja()||{}).id||'',
        secretario_responsavel_id:(selectedLoja()||{}).secretario_responsavel_id||'',
        secretario_responsavel_nome:(selectedLoja()||{}).secretario_responsavel_nome||''
      })
    });
    const j=await r.json();
    if(j.ok){
      if(tg && tg.MainButton && tg.MainButton.isVisible){
        closeMiniAppSafe();
      }else{
        showToast('Rascunho salvo. Continue a confirmação no chat do Telegram.');
        const btnIrChat=document.getElementById('btn_ir_chat');
        if(btnIrChat)btnIrChat.style.display='inline-flex';
        const btnPublicar=document.getElementById('btn_publicar_evento');
        if(btnPublicar){
          btnPublicar.disabled=true;
          btnPublicar.textContent='Rascunho enviado para o Telegram';
        }
        const btnCancelar=document.getElementById('btn_cancelar_evento');
        if(btnCancelar)btnCancelar.textContent='Fechar Mini App';
        setPrimaryLoading(false);
        enviandoEvento=false;
      }
    }else{
      showToast(j.error||'Erro. Tente novamente.');
      setPrimaryLoading(false);
      enviandoEvento=false;
    }
  }catch{
    showToast('Falha de conexão. Tente novamente.');
    setPrimaryLoading(false);
    enviandoEvento=false;
  }
}

if(tg && tg.MainButton){
  const acoes = document.getElementById('acoes_publicacao');
  if(acoes) acoes.style.display = 'none';
  tg.MainButton.setText('Salvar rascunho e continuar');
  tg.MainButton.show();
  tg.MainButton.onClick(publicarEvento);
} else {
  const btnPublicar=document.getElementById('btn_publicar_evento');
  if(btnPublicar){
    btnPublicar.addEventListener('click',publicarEvento);
  }
  const btnCancelar=document.getElementById('btn_cancelar_evento');
  if(btnCancelar){
    btnCancelar.addEventListener('click',()=>closeMiniAppSafe());
  }
  const btnIrChat=document.getElementById('btn_ir_chat');
  if(btnIrChat){
    btnIrChat.addEventListener('click',()=>closeMiniAppSafe());
  }
}
"""
    return _html_wrap("Agendamento de Sessão", body, script)



# ─────────────────────────────────────────────────────────────────────────────
# HANDLERS GET (servem os HTMLs)
# ─────────────────────────────────────────────────────────────────────────────

async def get_cadastro_membro(request: Request) -> HTMLResponse:
    return HTMLResponse(html_cadastro_membro())


async def get_cadastro_evento(request: Request) -> HTMLResponse:
    return HTMLResponse(html_cadastro_evento())


async def get_cadastro_loja(request: Request) -> HTMLResponse:
    return HTMLResponse(html_cadastro_loja())


def _apoios_table(name: str):
    if not supabase:
        return None
    return supabase.table(name)


def _money_float(value: Any) -> float:
    try:
        return float(str(value or "0").replace(",", "."))
    except Exception:
        return 0.0


def _int_or_default(value: Any, default: int = 0) -> int:
    try:
        return int(float(str(value or default).replace(",", ".")))
    except Exception:
        return default


def _bool_from_any(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "s", "sim", "true", "on", "ativo", "yes"}


def _current_month() -> str:
    return datetime.now().strftime("%Y-%m")


def _norm_iso_date(value: Any) -> str:
    raw = _norm_text(value)
    if not raw:
        return ""
    if len(raw) == 10 and raw[4] == "-" and raw[7] == "-":
        return raw
    for fmt in ("%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except Exception:
            pass
    return raw[:10]


async def _apoios_request_payload(request: Request) -> Dict[str, Any]:
    if request.method == "GET":
        return dict(request.query_params)
    try:
        return await request.json()
    except Exception:
        return {}


async def _validar_admin_apoios(request: Request, body: Dict[str, Any]) -> tuple[Optional[int], Optional[JSONResponse]]:
    bot_token: str = request.app.state.bot_token
    init_data = (body.get("init_data") or request.query_params.get("init_data") or "").strip()
    user = verify_telegram_webapp_data(init_data, bot_token)
    if not user or not user.get("id"):
        return None, JSONResponse({"ok": False, "error": "Não autorizado."}, status_code=403)
    telegram_id = int(user["id"])
    if str(get_nivel(telegram_id)) != "3":
        return telegram_id, JSONResponse({"ok": False, "error": "Área exclusiva para administradores."}, status_code=403)
    return telegram_id, None


def _fetch_apoios(table: str, order: str = "created_at", desc: bool = True) -> List[Dict[str, Any]]:
    t = _apoios_table(table)
    if t is None:
        return []
    try:
        q = t.select("*")
        if order:
            q = q.order(order, desc=desc)
        return list((q.execute().data or []))
    except Exception as exc:
        logger.warning("Falha ao consultar %s: %s", table, exc)
        return []


def _decode_data_url(data_url: str) -> tuple[bytes, str]:
    raw = _norm_text(data_url)
    if not raw or "," not in raw:
        return b"", "application/octet-stream"
    header, payload = raw.split(",", 1)
    content_type = "application/octet-stream"
    if header.startswith("data:") and ";" in header:
        content_type = header[5:].split(";", 1)[0] or content_type
    try:
        return base64.b64decode(payload), content_type
    except Exception:
        return b"", content_type


def _upload_apoio_asset(prefix: str, row_id: str, field: str, data_url: str) -> str:
    content, content_type = _decode_data_url(data_url)
    if not content:
        return ""
    ext = mimetypes.guess_extension(content_type) or ".bin"
    path = f"{prefix}/{row_id}/{field}{ext}"
    return upload_storage_publico(BUCKET_APOIOS_PUBLICIDADE, path, content, content_type) or ""


def _upsert_apoios_config(apoiador_id: str, body: Dict[str, Any]) -> None:
    table = _apoios_table("apoios_config")
    if not apoiador_id or table is None:
        return
    row = {
        "apoiador_id": apoiador_id,
        "permite_logo_card": _bool_from_any(body.get("permite_logo_card")),
        "permite_confirmados": _bool_from_any(body.get("permite_confirmados")),
        "permite_ia": _bool_from_any(body.get("permite_ia")),
        "permite_rodape": _bool_from_any(body.get("permite_rodape")),
        "permite_botao_link": _bool_from_any(body.get("permite_botao_link", "true")),
        "limite_card_mes": _int_or_default(body.get("limite_card_mes")),
        "limite_confirmados_mes": _int_or_default(body.get("limite_confirmados_mes")),
        "limite_ia_mes": _int_or_default(body.get("limite_ia_mes")),
        "limite_rodape_mes": _int_or_default(body.get("limite_rodape_mes")),
        "peso_prioridade": max(1, _int_or_default(body.get("peso_prioridade"), 1)),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    existente = table.select("id").eq("apoiador_id", apoiador_id).limit(1).execute()
    if existente.data:
        table.update(row).eq("id", existente.data[0]["id"]).execute()
    else:
        table.insert(row).execute()


def _dashboard_apoios() -> Dict[str, Any]:
    apoiadores = _fetch_apoios("apoiadores")
    contratos = _fetch_apoios("apoios_contratos")
    pagamentos = _fetch_apoios("apoios_pagamentos")
    exibicoes = _fetch_apoios("apoios_exibicoes")
    criativos = _fetch_apoios("apoios_criativos")
    hoje = datetime.now().date()
    mes = _current_month()
    contratos_ativos: List[Dict[str, Any]] = []
    vencendo: List[Dict[str, Any]] = []
    vencidos: List[Dict[str, Any]] = []
    inadimplentes: List[Dict[str, Any]] = []
    for contrato in contratos:
        status = str(contrato.get("status") or "").lower()
        fim = None
        try:
            fim = datetime.strptime(str(contrato.get("data_fim") or "")[:10], "%Y-%m-%d").date()
        except Exception:
            pass
        if status == "ativo" and (not fim or fim >= hoje):
            contratos_ativos.append(contrato)
            if fim and 0 <= (fim - hoje).days <= int(contrato.get("renovacao_alerta_dias") or 30):
                vencendo.append(contrato)
        if status == "vencido" or (fim and fim < hoje):
            vencidos.append(contrato)
        if status == "inadimplente":
            inadimplentes.append(contrato)
    pagamentos_mes = [p for p in pagamentos if str(p.get("competencia") or "").startswith(mes)]
    recebido_mes = sum(_money_float(p.get("valor_pago")) for p in pagamentos_mes if str(p.get("status") or "").lower() == "pago")
    saldo_aberto = sum(_money_float(p.get("valor_previsto")) - _money_float(p.get("valor_pago")) for p in pagamentos_mes if str(p.get("status") or "").lower() != "pago")
    por_tipo: Dict[str, int] = {}
    for exibicao in exibicoes:
        tipo = str(exibicao.get("tipo_exibicao") or "sem_tipo")
        por_tipo[tipo] = por_tipo.get(tipo, 0) + 1
    return {
        "apoiadores": apoiadores,
        "contratos": contratos,
        "pagamentos": pagamentos,
        "criativos": criativos,
        "metricas": {
            "apoiadores_ativos": len([a for a in apoiadores if str(a.get("status") or "").lower() == "ativo"]),
            "contratos_ativos": len(contratos_ativos),
            "contratos_vencendo": len(vencendo),
            "contratos_vencidos": len(vencidos),
            "contratos_inadimplentes": len(inadimplentes),
            "receita_prevista": round(sum(_money_float(c.get("valor_contribuicao")) for c in contratos_ativos), 2),
            "recebido_mes": round(recebido_mes, 2),
            "saldo_aberto_mes": round(saldo_aberto, 2),
            "exibicoes_por_tipo": por_tipo,
        },
    }


async def api_apoios_dashboard(request: Request) -> JSONResponse:
    body = await _apoios_request_payload(request)
    _, erro = await _validar_admin_apoios(request, body)
    if erro:
        return erro
    return JSONResponse({"ok": True, **_dashboard_apoios()})


async def api_apoios_apoiadores(request: Request) -> JSONResponse:
    body = await _apoios_request_payload(request)
    _, erro = await _validar_admin_apoios(request, body)
    if erro:
        return erro
    if request.method == "GET":
        return JSONResponse({"ok": True, "apoiadores": _fetch_apoios("apoiadores")})
    row = {
        "nome": _norm_text(body.get("nome"))[:200],
        "responsavel_nome": _norm_text(body.get("responsavel_nome"))[:200],
        "telefone": _norm_text(body.get("telefone"))[:50],
        "email": _norm_text(body.get("email"))[:180],
        "segmento": _norm_text(body.get("segmento"))[:120],
        "cidade": _norm_text(body.get("cidade"))[:120],
        "link_publico": _norm_text(body.get("link_publico"))[:400],
        "texto_curto": _norm_text(body.get("texto_curto"))[:500],
        "status": _norm_text(body.get("status") or "ativo")[:30],
        "observacoes": _norm_text(body.get("observacoes"))[:800],
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    if not row["nome"]:
        return JSONResponse({"ok": False, "error": "Informe o nome do apoiador."}, status_code=400)
    try:
        table = _apoios_table("apoiadores")
        if table is None:
            raise RuntimeError("Supabase indisponivel")
        row_id = _norm_text(body.get("id"))
        if row_id:
            table.update(row).eq("id", row_id).execute()
        else:
            inserted = table.insert(row).execute()
            row_id = str((inserted.data or [{}])[0].get("id") or "")
        media_update: Dict[str, str] = {}
        logo_url = _upload_apoio_asset("apoiadores", row_id, "logo", _norm_text(body.get("logo_data_url")))
        img_url = _upload_apoio_asset("apoiadores", row_id, "publicidade", _norm_text(body.get("imagem_publicidade_data_url")))
        if logo_url:
            media_update["logo_url"] = logo_url
        if img_url:
            media_update["imagem_publicidade_url"] = img_url
        if media_update:
            table.update(media_update).eq("id", row_id).execute()
        return JSONResponse({"ok": True, "id": row_id})
    except Exception as exc:
        logger.warning("Falha ao salvar apoiador via Mini App: %s", exc)
        return JSONResponse({"ok": False, "error": "Falha ao salvar apoiador."}, status_code=500)


async def api_apoios_contratos(request: Request) -> JSONResponse:
    body = await _apoios_request_payload(request)
    _, erro = await _validar_admin_apoios(request, body)
    if erro:
        return erro
    if request.method == "GET":
        return JSONResponse({"ok": True, "contratos": _fetch_apoios("apoios_contratos")})
    row = {
        "apoiador_id": _norm_text(body.get("apoiador_id")),
        "categoria": _norm_text(body.get("categoria") or "institucional"),
        "data_inicio": _norm_iso_date(body.get("data_inicio")),
        "data_fim": _norm_iso_date(body.get("data_fim")),
        "valor_contribuicao": _money_float(body.get("valor_contribuicao")),
        "finalidade": _norm_text(body.get("finalidade"))[:400],
        "status": _norm_text(body.get("status") or "ativo"),
        "periodicidade": _norm_text(body.get("periodicidade") or "mensal"),
        "dia_vencimento": _int_or_default(body.get("dia_vencimento"), 10),
        "renovacao_alerta_dias": _int_or_default(body.get("renovacao_alerta_dias"), 30),
        "termo_url": _norm_text(body.get("termo_url"))[:500],
        "observacoes": _norm_text(body.get("observacoes"))[:800],
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    if not row["apoiador_id"] or not row["data_inicio"] or not row["data_fim"]:
        return JSONResponse({"ok": False, "error": "Informe apoiador e período do contrato."}, status_code=400)
    try:
        table = _apoios_table("apoios_contratos")
        if table is None:
            raise RuntimeError("Supabase indisponivel")
        row_id = _norm_text(body.get("id"))
        if row_id:
            table.update(row).eq("id", row_id).execute()
        else:
            inserted = table.insert(row).execute()
            row_id = str((inserted.data or [{}])[0].get("id") or "")
        _upsert_apoios_config(row["apoiador_id"], body)
        return JSONResponse({"ok": True, "id": row_id})
    except Exception as exc:
        logger.warning("Falha ao salvar contrato via Mini App: %s", exc)
        return JSONResponse({"ok": False, "error": "Falha ao salvar contrato."}, status_code=500)


async def api_apoios_pagamentos(request: Request) -> JSONResponse:
    body = await _apoios_request_payload(request)
    _, erro = await _validar_admin_apoios(request, body)
    if erro:
        return erro
    if request.method == "GET":
        return JSONResponse({"ok": True, "pagamentos": _fetch_apoios("apoios_pagamentos")})
    row = {
        "apoiador_id": _norm_text(body.get("apoiador_id")),
        "contrato_id": _norm_text(body.get("contrato_id")) or None,
        "competencia": _norm_text(body.get("competencia") or _current_month())[:7],
        "data_vencimento": _norm_iso_date(body.get("data_vencimento")) or None,
        "valor_previsto": _money_float(body.get("valor_previsto")),
        "valor_pago": _money_float(body.get("valor_pago")),
        "data_pagamento": _norm_iso_date(body.get("data_pagamento")) or None,
        "status": _norm_text(body.get("status") or "pendente"),
        "forma_pagamento": _norm_text(body.get("forma_pagamento"))[:80],
        "observacoes": _norm_text(body.get("observacoes"))[:800],
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    if not row["apoiador_id"] or not row["competencia"]:
        return JSONResponse({"ok": False, "error": "Informe apoiador e competência."}, status_code=400)
    try:
        table = _apoios_table("apoios_pagamentos")
        if table is None:
            raise RuntimeError("Supabase indisponivel")
        row_id = _norm_text(body.get("id"))
        if row_id:
            table.update(row).eq("id", row_id).execute()
        else:
            inserted = table.insert(row).execute()
            row_id = str((inserted.data or [{}])[0].get("id") or "")
        comp_url = _upload_apoio_asset("pagamentos", row_id, "comprovante", _norm_text(body.get("comprovante_data_url")))
        if comp_url:
            table.update({"comprovante_url": comp_url}).eq("id", row_id).execute()
        return JSONResponse({"ok": True, "id": row_id})
    except Exception as exc:
        logger.warning("Falha ao salvar pagamento via Mini App: %s", exc)
        return JSONResponse({"ok": False, "error": "Falha ao salvar pagamento."}, status_code=500)


async def api_apoios_criativos(request: Request) -> JSONResponse:
    body = await _apoios_request_payload(request)
    _, erro = await _validar_admin_apoios(request, body)
    if erro:
        return erro
    if request.method == "GET":
        return JSONResponse({"ok": True, "criativos": _fetch_apoios("apoios_criativos")})
    row = {
        "apoiador_id": _norm_text(body.get("apoiador_id")),
        "contrato_id": _norm_text(body.get("contrato_id")) or None,
        "tipo_posicionamento": _norm_text(body.get("tipo_posicionamento") or "tela_apoiadores"),
        "titulo": _norm_text(body.get("titulo"))[:160],
        "texto": _norm_text(body.get("texto"))[:1000],
        "link_url": _norm_text(body.get("link_url"))[:500],
        "status": _norm_text(body.get("status") or "ativo"),
        "prioridade": _int_or_default(body.get("prioridade"), 1),
        "data_inicio": _norm_iso_date(body.get("data_inicio")) or None,
        "data_fim": _norm_iso_date(body.get("data_fim")) or None,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    if not row["apoiador_id"] or not row["tipo_posicionamento"]:
        return JSONResponse({"ok": False, "error": "Informe apoiador e posicionamento."}, status_code=400)
    try:
        table = _apoios_table("apoios_criativos")
        if table is None:
            raise RuntimeError("Supabase indisponivel")
        row_id = _norm_text(body.get("id"))
        if row_id:
            table.update(row).eq("id", row_id).execute()
        else:
            inserted = table.insert(row).execute()
            row_id = str((inserted.data or [{}])[0].get("id") or "")
        imagem_url = _upload_apoio_asset("criativos", row_id, "imagem", _norm_text(body.get("imagem_data_url")))
        if imagem_url:
            table.update({"imagem_url": imagem_url}).eq("id", row_id).execute()
        return JSONResponse({"ok": True, "id": row_id})
    except Exception as exc:
        logger.warning("Falha ao salvar criativo via Mini App: %s", exc)
        return JSONResponse({"ok": False, "error": "Falha ao salvar criativo."}, status_code=500)


def html_apoios_admin() -> str:
    body = """
<div class="card" style="text-align: center; padding: 20px;">
  <div style="font-size: 48px; margin-bottom: 12px;">📢</div>
  <h2 style="margin-bottom: 8px;">Painel de Gestão</h2>
  <p style="color: var(--hint); margin: 8px 0 20px; font-size: 14px;">Selecione um dos módulos para gerenciar:</p>
  <div class="actions-stack">
    <button class="btn-primary" style="margin-bottom: 10px;" onclick="window.location.href='/webapp/apoios/apoiadores'">🤝 Apoiadores</button>
    <button class="btn-primary" style="margin-bottom: 10px;" onclick="window.location.href='/webapp/apoios/contratos'">📋 Contratos</button>
    <button class="btn-primary" style="margin-bottom: 10px;" onclick="window.location.href='/webapp/apoios/financeiro'">💰 Financeiro</button>
    <button class="btn-primary" style="margin-bottom: 10px;" onclick="window.location.href='/webapp/apoios/criativos'">🎨 Criativos</button>
  </div>
</div>
"""
    return _html_wrap("Publicidade e Apoiadores", body, "")


async def get_apoios_admin(request: Request) -> HTMLResponse:
    return HTMLResponse(html_apoios_admin())


def html_apoios_apoiadores() -> str:
    body = """
<style>
.item-card { background: rgba(128,128,128,0.1); border: 1px solid var(--border); border-radius: 8px; padding: 10px; cursor: pointer; transition: all 0.2s; display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.item-card:hover { border-color: var(--btn); background: rgba(128,128,128,0.15); }
.item-card.selected { border-color: var(--btn); background: rgba(36,129,204,0.1); }
.badge { font-size: 11px; padding: 3px 8px; border-radius: 12px; font-weight: bold; text-transform: uppercase; }
.badge-ativo { background: #2ec4b6; color: #fff; }
.badge-pausado { background: #ff9f1c; color: #fff; }
.badge-encerrado { background: #7f8c8d; color: #fff; }
.badge-inadimplente { background: #e71d36; color: #fff; }
.badge-vencido { background: #7f8c8d; color: #fff; }
.sec-title { font-size: 14px; font-weight: bold; margin-bottom: 10px; color: var(--hint); display: flex; justify-content: space-between; align-items: center; }
.list-container { max-height: 250px; overflow-y: auto; margin-bottom: 15px; }
.btn-small { background: var(--btn); color: var(--btn-text); border: none; border-radius: 6px; padding: 5px 10px; font-size: 12px; cursor: pointer; font-weight: 600; }
.avatar-preview { width: 40px; height: 40px; border-radius: 50%; object-fit: cover; background: rgba(128,128,128,0.2); margin-right: 10px; display: inline-block; vertical-align: middle; }
.card-content-flex { display: flex; align-items: center; }
.btn-danger { background: #ff3b30; color: #fff; }
</style>

<div class="card">
  <div class="sec-title">
    <span>🤝 Apoiadores Cadastrados</span>
    <button class="btn-small" onclick="novoApoiador()">+ Novo</button>
  </div>
  <div id="lista_apoiadores" class="list-container">Carregando...</div>
</div>

<div class="card" id="form_card">
  <div class="card-title" id="form_title">Novo Apoiador</div>
  <input type="hidden" id="apoiador_id">
  
  <div class="field">
    <label>Nome do Apoiador / Empresa</label>
    <input id="apoiador_nome" placeholder="Ex: Sind Ofícios">
    <span class="err" id="apoiador_nome_err"></span>
  </div>
  
  <div class="field">
    <label>Nome do Responsável</label>
    <input id="apoiador_responsavel" placeholder="Ex: João Silva">
  </div>
  
  <div class="field flex-fields" style="display: flex; gap: 10px;">
    <div style="flex: 1;">
      <label>Telefone</label>
      <input id="apoiador_telefone" placeholder="Ex: (48) 99999-9999">
    </div>
    <div style="flex: 1;">
      <label>E-mail</label>
      <input id="apoiador_email" type="email" placeholder="Ex: contato@empresa.com">
    </div>
  </div>
  
  <div class="field flex-fields" style="display: flex; gap: 10px;">
    <div style="flex: 1;">
      <label>Segmento de Atuação</label>
      <input id="apoiador_segmento" placeholder="Ex: Advocacia, Alimentos">
    </div>
    <div style="flex: 1;">
      <label>Cidade</label>
      <input id="apoiador_cidade" placeholder="Ex: Florianópolis">
    </div>
  </div>
  
  <div class="field">
    <label>Link Público (Site / Redes Sociais)</label>
    <input id="apoiador_link" type="url" placeholder="https://...">
  </div>
  
  <div class="field">
    <label>Descrição / Texto Curto</label>
    <textarea id="apoiador_texto" placeholder="Breve texto sobre o apoiador..."></textarea>
  </div>
  
  <div class="field">
    <label>Status</label>
    <select id="apoiador_status">
      <option value="ativo">Ativo</option>
      <option value="pausado">Pausado</option>
      <option value="encerrado">Encerrado</option>
    </select>
  </div>
  
  <div class="field" style="display: flex; align-items: center; gap: 12px;">
    <div style="flex: 1;">
      <label>Logo do Apoiador</label>
      <input id="apoiador_logo" type="file" accept="image/*" onchange="previewImg(this, 'preview_logo')">
    </div>
    <img id="preview_logo" class="avatar-preview" src="" style="display: none;">
  </div>
  
  <div class="field" style="display: flex; align-items: center; gap: 12px;">
    <div style="flex: 1;">
      <label>Imagem de Publicidade</label>
      <input id="apoiador_imagem" type="file" accept="image/*" onchange="previewImg(this, 'preview_publicidade')">
    </div>
    <img id="preview_publicidade" class="avatar-preview" src="" style="display: none; border-radius: 8px;">
  </div>
  
  <div class="field">
    <label>Observações Internas</label>
    <textarea id="apoiador_observacoes" placeholder="Notas contratuais, detalhes importantes..."></textarea>
  </div>

  <div class="actions">
    <button class="btn-primary" id="btn_salvar" onclick="salvarApoiador()">Salvar Apoiador</button>
  </div>
</div>
"""
    script = """
let state = { apoiadores: [] };
const byId = id => document.getElementById(id);

function previewImg(input, imgId) {
  const file = input.files[0];
  if (file) {
    const reader = new FileReader();
    reader.onload = function(e) {
      byId(imgId).src = e.target.result;
      byId(imgId).style.display = 'block';
    }
    reader.readAsDataURL(file);
  }
}

async function fileData(id) {
  const f = (byId(id).files || [])[0];
  if (!f) return '';
  return await new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(r.result || '');
    r.onerror = reject;
    r.readAsDataURL(f);
  });
}

async function api(path, payload) {
  const resp = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...payload, init_data: tgInitData() })
  });
  const data = await resp.json();
  if (!data.ok) throw new Error(data.error || 'Falha na operação.');
  return data;
}

function renderApoiadores() {
  const container = byId('lista_apoiadores');
  if (state.apoiadores.length === 0) {
    container.innerHTML = '<div style="color: var(--hint); text-align: center; padding: 12px;">Nenhum apoiador cadastrado.</div>';
    return;
  }
  container.innerHTML = '';
  state.apoiadores.forEach(a => {
    const card = document.createElement('div');
    card.className = 'item-card';
    card.id = 'apoiador_card_' + a.id;
    
    const logoSrc = a.logo_url || '';
    const logoHtml = logoSrc ? `<img class="avatar-preview" src="${logoSrc}">` : '<div class="avatar-preview" style="display: inline-flex; align-items: center; justify-content: center; font-weight: bold; font-size: 18px; color: var(--hint);">🤝</div>';
    
    card.innerHTML = `
      <div class="card-content-flex">
        ${logoHtml}
        <div>
          <div style="font-weight: 600;">${a.nome || 'Sem nome'}</div>
          <div style="font-size: 12px; color: var(--hint);">${a.segmento || 'Sem segmento'} - ${a.cidade || ''}</div>
        </div>
      </div>
      <span class="badge badge-${a.status || 'ativo'}">${a.status || 'ativo'}</span>
    `;
    card.onclick = () => editarApoiador(a);
    container.appendChild(card);
  });
}

function novoApoiador() {
  byId('form_title').textContent = 'Novo Apoiador';
  byId('apoiador_id').value = '';
  byId('apoiador_nome').value = '';
  byId('apoiador_responsavel').value = '';
  byId('apoiador_telefone').value = '';
  byId('apoiador_email').value = '';
  byId('apoiador_segmento').value = '';
  byId('apoiador_cidade').value = '';
  byId('apoiador_link').value = '';
  byId('apoiador_texto').value = '';
  byId('apoiador_status').value = 'ativo';
  byId('apoiador_logo').value = '';
  byId('apoiador_imagem').value = '';
  byId('preview_logo').style.display = 'none';
  byId('preview_publicidade').style.display = 'none';
  byId('apoiador_observacoes').value = '';
  
  document.querySelectorAll('.item-card').forEach(el => el.classList.remove('selected'));
  clearErr('apoiador_nome');
}

function editarApoiador(a) {
  novoApoiador();
  byId('form_title').textContent = 'Editar Apoiador';
  byId('apoiador_id').value = a.id || '';
  byId('apoiador_nome').value = a.nome || '';
  byId('apoiador_responsavel').value = a.responsavel_nome || '';
  byId('apoiador_telefone').value = a.telefone || '';
  byId('apoiador_email').value = a.email || '';
  byId('apoiador_segmento').value = a.segmento || '';
  byId('apoiador_cidade').value = a.cidade || '';
  byId('apoiador_link').value = a.link_publico || '';
  byId('apoiador_texto').value = a.texto_curto || '';
  byId('apoiador_status').value = a.status || 'ativo';
  byId('apoiador_observacoes').value = a.observacoes || '';
  
  if (a.logo_url) {
    byId('preview_logo').src = a.logo_url;
    byId('preview_logo').style.display = 'block';
  }
  if (a.imagem_publicidade_url) {
    byId('preview_publicidade').src = a.imagem_publicidade_url;
    byId('preview_publicidade').style.display = 'block';
  }
  
  const selectedCard = byId('apoiador_card_' + a.id);
  if (selectedCard) selectedCard.classList.add('selected');
}

async function carregar() {
  try {
    const data = await api('/api/apoios/dashboard', {});
    state = data;
    renderApoiadores();
  } catch (e) {
    showToast(e.message, 4500);
  }
}

async function salvarApoiador() {
  if (!req('apoiador_nome', 'Nome do Apoiador')) {
    scrollToFirstError();
    return;
  }
  
  const btn = byId('btn_salvar');
  btn.disabled = true;
  btn.textContent = 'Salvando...';
  
  try {
    await api('/api/apoios/apoiadores', {
      id: val('apoiador_id'),
      nome: val('apoiador_nome'),
      responsavel_nome: val('apoiador_responsavel'),
      telefone: val('apoiador_telefone'),
      email: val('apoiador_email'),
      segmento: val('apoiador_segmento'),
      cidade: val('apoiador_cidade'),
      link_publico: val('apoiador_link'),
      texto_curto: val('apoiador_texto'),
      status: val('apoiador_status'),
      logo_data_url: await fileData('apoiador_logo'),
      imagem_publicidade_data_url: await fileData('apoiador_imagem'),
      observacoes: val('apoiador_observacoes')
    });
    showToast('Apoiador salvo com sucesso!');
    novoApoiador();
    await carregar();
  } catch (e) {
    showToast(e.message, 4500);
  } finally {
    btn.disabled = false;
    btn.textContent = 'Salvar Apoiador';
  }
}

carregar();
"""
    return _html_wrap("Apoiadores", body, script)


async def get_apoios_apoiadores(request: Request) -> HTMLResponse:
    return HTMLResponse(html_apoios_apoiadores())


def html_apoios_contratos() -> str:
    body = """
<style>
.item-card { background: rgba(128,128,128,0.1); border: 1px solid var(--border); border-radius: 8px; padding: 10px; cursor: pointer; transition: all 0.2s; display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.item-card:hover { border-color: var(--btn); background: rgba(128,128,128,0.15); }
.item-card.selected { border-color: var(--btn); background: rgba(36,129,204,0.1); }
.badge { font-size: 11px; padding: 3px 8px; border-radius: 12px; font-weight: bold; text-transform: uppercase; }
.badge-ativo { background: #2ec4b6; color: #fff; }
.badge-pausado { background: #ff9f1c; color: #fff; }
.badge-encerrado { background: #7f8c8d; color: #fff; }
.badge-inadimplente { background: #e71d36; color: #fff; }
.badge-vencido { background: #7f8c8d; color: #fff; }
.sec-title { font-size: 14px; font-weight: bold; margin-bottom: 10px; color: var(--hint); display: flex; justify-content: space-between; align-items: center; }
.list-container { max-height: 250px; overflow-y: auto; margin-bottom: 15px; }
.btn-small { background: var(--btn); color: var(--btn-text); border: none; border-radius: 6px; padding: 5px 10px; font-size: 12px; cursor: pointer; font-weight: 600; }
.switch-container { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; }
.switch-container input { width: auto; }
</style>

<div class="card">
  <div class="sec-title">
    <span>📋 Contratos Registrados</span>
    <button class="btn-small" onclick="novoContrato()">+ Novo</button>
  </div>
  <div id="lista_contratos" class="list-container">Carregando...</div>
</div>

<div class="card" id="form_card">
  <div class="card-title" id="form_title">Novo Contrato</div>
  <input type="hidden" id="contrato_id">
  
  <div class="field">
    <label>Apoiador</label>
    <select id="contrato_apoiador">
      <option value="">Selecione...</option>
    </select>
    <span class="err" id="contrato_apoiador_err"></span>
  </div>
  
  <div class="field flex-fields" style="display: flex; gap: 10px;">
    <div style="flex: 1;">
      <label>Categoria</label>
      <select id="contrato_categoria">
        <option value="master">Master</option>
        <option value="destaque">Destaque</option>
        <option value="institucional">Institucional</option>
        <option value="amigo_projeto">Amigo do Projeto</option>
      </select>
    </div>
    <div style="flex: 1;">
      <label>Periodicidade</label>
      <select id="contrato_periodicidade">
        <option value="mensal">Mensal</option>
        <option value="trimestral">Trimestral</option>
        <option value="semestral">Semestral</option>
        <option value="anual">Anual</option>
        <option value="avulso">Avulso</option>
      </select>
    </div>
  </div>
  
  <div class="field flex-fields" style="display: flex; gap: 10px;">
    <div style="flex: 1;">
      <label>Data Início</label>
      <input id="contrato_inicio" placeholder="DD/MM/AAAA">
      <span class="err" id="contrato_inicio_err"></span>
    </div>
    <div style="flex: 1;">
      <label>Data Fim</label>
      <input id="contrato_fim" placeholder="DD/MM/AAAA">
      <span class="err" id="contrato_fim_err"></span>
    </div>
  </div>

  <div class="field flex-fields" style="display: flex; gap: 10px;">
    <div style="flex: 1;">
      <label>Valor da Contribuição (R$)</label>
      <input id="contrato_valor" inputmode="decimal" placeholder="0.00">
      <span class="err" id="contrato_valor_err"></span>
    </div>
    <div style="flex: 1;">
      <label>Dia de Vencimento</label>
      <input id="contrato_dia_vencimento" type="number" value="10" min="1" max="31">
    </div>
  </div>
  
  <div class="field flex-fields" style="display: flex; gap: 10px;">
    <div style="flex: 1;">
      <label>Alerta de Renovação (dias antes)</label>
      <input id="contrato_alerta" type="number" value="30">
    </div>
    <div style="flex: 1;">
      <label>Status</label>
      <select id="contrato_status">
        <option value="ativo">Ativo</option>
        <option value="pausado">Pausado</option>
        <option value="inadimplente">Inadimplente</option>
        <option value="vencido">Vencido</option>
        <option value="encerrado">Encerrado</option>
      </select>
    </div>
  </div>

  <div class="field">
    <label>Link para Termo Assinado (PDF/Drive)</label>
    <input id="contrato_termo" placeholder="https://...">
  </div>
  
  <div class="field">
    <label>Finalidade / Contrapartida</label>
    <textarea id="contrato_finalidade" placeholder="Ex: Divulgação no site, postagens no canal..."></textarea>
  </div>
  
  <div class="field">
    <label>Configurações de Exibição</label>
    <div style="margin-top: 8px; display: grid; grid-template-columns: 1fr 1fr; gap: 10px;">
      <div class="switch-container"><input type="checkbox" id="permite_logo_card" checked> <label for="permite_logo_card" style="margin:0;">Logo em card</label></div>
      <div class="switch-container"><input type="checkbox" id="permite_confirmados"> <label for="permite_confirmados" style="margin:0;">Confirmados premium</label></div>
      <div class="switch-container"><input type="checkbox" id="permite_ia" checked> <label for="permite_ia" style="margin:0;">Menções IA</label></div>
      <div class="switch-container"><input type="checkbox" id="permite_rodape" checked> <label for="permite_rodape" style="margin:0;">Rodapé diploma</label></div>
      <div class="switch-container"><input type="checkbox" id="permite_botao_link" checked> <label for="permite_botao_link" style="margin:0;">Botão link</label></div>
    </div>
  </div>
  
  <div class="field">
    <label>Limites de Exibição Mensal (0 = sem limite)</label>
    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 6px;">
      <input id="limite_card_mes" type="number" placeholder="Limite Card" value="0">
      <input id="limite_confirmados_mes" type="number" placeholder="Limite Confirmados" value="0">
      <input id="limite_ia_mes" type="number" placeholder="Limite IA" value="0">
      <input id="limite_rodape_mes" type="number" placeholder="Limite Rodapé" value="0">
    </div>
  </div>
  
  <div class="field">
    <label>Peso de Prioridade (Exibições)</label>
    <input id="peso_prioridade" type="number" value="1" min="1">
  </div>
  
  <div class="field">
    <label>Observações Internas</label>
    <textarea id="contrato_observacoes" placeholder="Notas internas..."></textarea>
  </div>

  <div class="actions">
    <button class="btn-primary" id="btn_salvar" onclick="salvarContrato()">Salvar Contrato</button>
  </div>
</div>
"""
    script = """
let state = { contratos: [], apoiadores: [], config: [] };
const byId = id => document.getElementById(id);

async function api(path, payload) {
  const resp = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...payload, init_data: tgInitData() })
  });
  const data = await resp.json();
  if (!data.ok) throw new Error(data.error || 'Falha na operação.');
  return data;
}

function fillSponsors() {
  const s = byId('contrato_apoiador');
  s.innerHTML = '<option value="">Selecione...</option>';
  state.apoiadores.forEach(a => {
    const o = document.createElement('option');
    o.textContent = a.nome;
    o.value = a.id;
    s.appendChild(o);
  });
}

function formatDateBR(isoDate) {
  if (!isoDate) return '';
  const parts = isoDate.split('-');
  if (parts.length === 3) return `${parts[2]}/${parts[1]}/${parts[0]}`;
  return isoDate;
}

function renderContratos() {
  const container = byId('lista_contratos');
  if (state.contratos.length === 0) {
    container.innerHTML = '<div style="color: var(--hint); text-align: center; padding: 12px;">Nenhum contrato cadastrado.</div>';
    return;
  }
  container.innerHTML = '';
  state.contratos.forEach(c => {
    const card = document.createElement('div');
    card.className = 'item-card';
    card.id = 'contrato_card_' + c.id;
    
    const apo = state.apoiadores.find(a => a.id === c.apoiador_id) || {};
    const valFmt = Number(c.valor_contribuicao || 0).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
    
    card.innerHTML = `
      <div>
        <div style="font-weight: 600;">${apo.nome || 'Apoiador Excluído'}</div>
        <div style="font-size: 12px; color: var(--hint);">${c.categoria.toUpperCase()} - ${valFmt} (${c.periodicidade})</div>
        <div style="font-size: 11px; color: var(--hint);">${formatDateBR(c.data_inicio)} até ${formatDateBR(c.data_fim)}</div>
      </div>
      <span class="badge badge-${c.status || 'ativo'}">${c.status || 'ativo'}</span>
    `;
    card.onclick = () => editarContrato(c);
    container.appendChild(card);
  });
}

function novoContrato() {
  byId('form_title').textContent = 'Novo Contrato';
  byId('contrato_id').value = '';
  byId('contrato_apoiador').value = '';
  byId('contrato_categoria').value = 'institucional';
  byId('contrato_periodicidade').value = 'mensal';
  byId('contrato_inicio').value = '';
  byId('contrato_fim').value = '';
  byId('contrato_valor').value = '';
  byId('contrato_dia_vencimento').value = 10;
  byId('contrato_alerta').value = 30;
  byId('contrato_status').value = 'ativo';
  byId('contrato_termo').value = '';
  byId('contrato_finalidade').value = '';
  byId('permite_logo_card').checked = true;
  byId('permite_confirmados').checked = false;
  byId('permite_ia').checked = true;
  byId('permite_rodape').checked = true;
  byId('permite_botao_link').checked = true;
  byId('limite_card_mes').value = 0;
  byId('limite_confirmados_mes').value = 0;
  byId('limite_ia_mes').value = 0;
  byId('limite_rodape_mes').value = 0;
  byId('peso_prioridade').value = 1;
  byId('contrato_observacoes').value = '';
  
  document.querySelectorAll('.item-card').forEach(el => el.classList.remove('selected'));
  clearErr('contrato_apoiador');
  clearErr('contrato_inicio');
  clearErr('contrato_fim');
  clearErr('contrato_valor');
}

function editarContrato(c) {
  novoContrato();
  byId('form_title').textContent = 'Editar Contrato';
  byId('contrato_id').value = c.id || '';
  byId('contrato_apoiador').value = c.apoiador_id || '';
  byId('contrato_categoria').value = c.categoria || 'institucional';
  byId('contrato_periodicidade').value = c.periodicidade || 'mensal';
  byId('contrato_inicio').value = formatDateBR(c.data_inicio);
  byId('contrato_fim').value = formatDateBR(c.data_fim);
  byId('contrato_valor').value = c.valor_contribuicao || '';
  byId('contrato_dia_vencimento').value = c.dia_vencimento || 10;
  byId('contrato_alerta').value = c.renovacao_alerta_dias || 30;
  byId('contrato_status').value = c.status || 'ativo';
  byId('contrato_termo').value = c.termo_url || '';
  byId('contrato_finalidade').value = c.finalidade || '';
  byId('contrato_observacoes').value = c.observacoes || '';
  
  // Encontrar config correspondente
  const cfg = state.config ? state.config.find(x => x.apoiador_id === c.apoiador_id) : null;
  if (cfg) {
    byId('permite_logo_card').checked = cfg.permite_logo_card !== false;
    byId('permite_confirmados').checked = !!cfg.permite_confirmados;
    byId('permite_ia').checked = cfg.permite_ia !== false;
    byId('permite_rodape').checked = cfg.permite_rodape !== false;
    byId('permite_botao_link').checked = cfg.permite_botao_link !== false;
    byId('limite_card_mes').value = cfg.limite_card_mes || 0;
    byId('limite_confirmados_mes').value = cfg.limite_confirmados_mes || 0;
    byId('limite_ia_mes').value = cfg.limite_ia_mes || 0;
    byId('limite_rodape_mes').value = cfg.limite_rodape_mes || 0;
    byId('peso_prioridade').value = cfg.peso_prioridade || 1;
  }
  
  const selectedCard = byId('contrato_card_' + c.id);
  if (selectedCard) selectedCard.classList.add('selected');
}

async function carregar() {
  try {
    const data = await api('/api/apoios/dashboard', {});
    state = data;
    fillSponsors();
    renderContratos();
  } catch (e) {
    showToast(e.message, 4500);
  }
}

async function salvarContrato() {
  let ok = true;
  if (!req('contrato_apoiador', 'Apoiador')) ok = false;
  if (!req('contrato_inicio', 'Data início')) ok = false;
  if (!req('contrato_fim', 'Data fim')) ok = false;
  if (!req('contrato_valor', 'Valor')) ok = false;
  
  if (!ok) {
    scrollToFirstError();
    return;
  }
  
  const dIni = parseDateBR(val('contrato_inicio'));
  const dFim = parseDateBR(val('contrato_fim'));
  
  if (!dIni) { setErr('contrato_inicio', 'Formato DD/MM/AAAA inválido.'); ok = false; }
  if (!dFim) { setErr('contrato_fim', 'Formato DD/MM/AAAA inválido.'); ok = false; }
  
  if (!ok) {
    scrollToFirstError();
    return;
  }
  
  const btn = byId('btn_salvar');
  btn.disabled = true;
  btn.textContent = 'Salvando...';
  
  try {
    await api('/api/apoios/contratos', {
      id: val('contrato_id'),
      apoiador_id: val('contrato_apoiador'),
      categoria: val('contrato_categoria'),
      periodicidade: val('contrato_periodicidade'),
      data_inicio: val('contrato_inicio'),
      data_fim: val('contrato_fim'),
      valor_contribuicao: val('contrato_valor'),
      dia_vencimento: val('contrato_dia_vencimento'),
      renovacao_alerta_dias: val('contrato_alerta'),
      status: val('contrato_status'),
      termo_url: val('contrato_termo'),
      finalidade: val('contrato_finalidade'),
      observacoes: val('contrato_observacoes'),
      // configs
      permite_logo_card: byId('permite_logo_card').checked ? 'true' : 'false',
      permite_confirmados: byId('permite_confirmados').checked ? 'true' : 'false',
      permite_ia: byId('permite_ia').checked ? 'true' : 'false',
      permite_rodape: byId('permite_rodape').checked ? 'true' : 'false',
      permite_botao_link: byId('permite_botao_link').checked ? 'true' : 'false',
      limite_card_mes: val('limite_card_mes'),
      limite_confirmados_mes: val('limite_confirmados_mes'),
      limite_ia_mes: val('limite_ia_mes'),
      limite_rodape_mes: val('limite_rodape_mes'),
      peso_prioridade: val('peso_prioridade')
    });
    showToast('Contrato salvo com sucesso!');
    novoContrato();
    await carregar();
  } catch (e) {
    showToast(e.message, 4500);
  } finally {
    btn.disabled = false;
    btn.textContent = 'Salvar Contrato';
  }
}

maskDate(byId('contrato_inicio'));
maskDate(byId('contrato_fim'));
carregar();
"""
    return _html_wrap("Contratos", body, script)


async def get_apoios_contratos(request: Request) -> HTMLResponse:
    return HTMLResponse(html_apoios_contratos())


def html_apoios_financeiro() -> str:
    body = """
<style>
.item-card { background: rgba(128,128,128,0.1); border: 1px solid var(--border); border-radius: 8px; padding: 10px; cursor: pointer; transition: all 0.2s; display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.item-card:hover { border-color: var(--btn); background: rgba(128,128,128,0.15); }
.item-card.selected { border-color: var(--btn); background: rgba(36,129,204,0.1); }
.badge { font-size: 11px; padding: 3px 8px; border-radius: 12px; font-weight: bold; text-transform: uppercase; }
.badge-pago { background: #2ec4b6; color: #fff; }
.badge-pendente { background: #ff9f1c; color: #fff; }
.badge-parcial { background: #3a86c8; color: #fff; }
.badge-atrasado { background: #e71d36; color: #fff; }
.badge-cancelado { background: #7f8c8d; color: #fff; }
.sec-title { font-size: 14px; font-weight: bold; margin-bottom: 10px; color: var(--hint); display: flex; justify-content: space-between; align-items: center; }
.list-container { max-height: 250px; overflow-y: auto; margin-bottom: 15px; }
.btn-small { background: var(--btn); color: var(--btn-text); border: none; border-radius: 6px; padding: 5px 10px; font-size: 12px; cursor: pointer; font-weight: 600; }
.comp-preview { max-width: 100px; max-height: 100px; border-radius: 4px; object-fit: cover; margin-top: 6px; display: none; }
</style>

<div class="card">
  <div class="sec-title">
    <span>💰 Lançamentos Financeiros</span>
    <button class="btn-small" onclick="novoPagamento()">+ Novo Lançamento</button>
  </div>
  <div id="lista_pagamentos" class="list-container">Carregando...</div>
</div>

<div class="card" id="form_card">
  <div class="card-title" id="form_title">Novo Lançamento</div>
  <input type="hidden" id="pagamento_id">
  
  <div class="field">
    <label>Apoiador</label>
    <select id="pagamento_apoiador" onchange="onApoiadorChange()">
      <option value="">Selecione...</option>
    </select>
    <span class="err" id="pagamento_apoiador_err"></span>
  </div>

  <div class="field">
    <label>Contrato Relacionado (Opcional)</label>
    <select id="pagamento_contrato">
      <option value="">Sem contrato</option>
    </select>
  </div>
  
  <div class="field flex-fields" style="display: flex; gap: 10px;">
    <div style="flex: 1;">
      <label>Competência (AAAA-MM)</label>
      <input id="pagamento_competencia" placeholder="Ex: 2026-05">
      <span class="err" id="pagamento_competencia_err"></span>
    </div>
    <div style="flex: 1;">
      <label>Vencimento</label>
      <input id="pagamento_vencimento" placeholder="DD/MM/AAAA">
      <span class="err" id="pagamento_vencimento_err"></span>
    </div>
  </div>

  <div class="field flex-fields" style="display: flex; gap: 10px;">
    <div style="flex: 1;">
      <label>Valor Previsto (R$)</label>
      <input id="pagamento_previsto" inputmode="decimal" placeholder="0.00">
      <span class="err" id="pagamento_previsto_err"></span>
    </div>
    <div style="flex: 1;">
      <label>Valor Pago (R$)</label>
      <input id="pagamento_pago" inputmode="decimal" placeholder="0.00" value="0">
    </div>
  </div>

  <div class="field flex-fields" style="display: flex; gap: 10px;">
    <div style="flex: 1;">
      <label>Data Pagamento</label>
      <input id="pagamento_data" placeholder="DD/MM/AAAA">
    </div>
    <div style="flex: 1;">
      <label>Forma de Pagamento</label>
      <input id="pagamento_forma" placeholder="Ex: PIX, Transferência">
    </div>
  </div>

  <div class="field">
    <label>Status</label>
    <select id="pagamento_status">
      <option value="pendente">Pendente</option>
      <option value="pago">Pago</option>
      <option value="parcial">Pago Parcial</option>
      <option value="atrasado">Atrasado</option>
      <option value="cancelado">Cancelado</option>
    </select>
  </div>
  
  <div class="field">
    <label>Comprovante (Imagem / PDF)</label>
    <input id="pagamento_comprovante" type="file" accept="image/*,.pdf" onchange="previewFile(this)">
    <img id="preview_comprovante" class="comp-preview" src="">
    <div id="pdf_status" style="display:none; margin-top:6px; font-size:12px; color:var(--hint);">📄 Documento PDF Selecionado</div>
    <div id="comprovante_link_div" style="display:none; margin-top:6px;"><a id="comprovante_link" href="#" target="_blank" style="font-size:13px; color:var(--link);">Visualizar Comprovante Existente</a></div>
  </div>

  <div class="field">
    <label>Observações</label>
    <textarea id="pagamento_observacoes" placeholder="Notas financeiras..."></textarea>
  </div>

  <div class="actions">
    <button class="btn-primary" id="btn_salvar" onclick="salvarPagamento()">Salvar Financeiro</button>
  </div>
</div>
"""
    script = """
let state = { pagamentos: [], apoiadores: [], contratos: [] };
const byId = id => document.getElementById(id);

async function api(path, payload) {
  const resp = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...payload, init_data: tgInitData() })
  });
  const data = await resp.json();
  if (!data.ok) throw new Error(data.error || 'Falha na operação.');
  return data;
}

function previewFile(input) {
  const file = input.files[0];
  byId('preview_comprovante').style.display = 'none';
  byId('pdf_status').style.display = 'none';
  if (file) {
    if (file.type.startsWith('image/')) {
      const reader = new FileReader();
      reader.onload = function(e) {
        byId('preview_comprovante').src = e.target.result;
        byId('preview_comprovante').style.display = 'block';
      }
      reader.readAsDataURL(file);
    } else {
      byId('pdf_status').style.display = 'block';
    }
  }
}

async function fileData(id) {
  const f = (byId(id).files || [])[0];
  if (!f) return '';
  return await new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(r.result || '');
    r.onerror = reject;
    r.readAsDataURL(f);
  });
}

function fillSponsors() {
  const s = byId('pagamento_apoiador');
  s.innerHTML = '<option value="">Selecione...</option>';
  state.apoiadores.forEach(a => {
    const o = document.createElement('option');
    o.textContent = a.nome;
    o.value = a.id;
    s.appendChild(o);
  });
}

function onApoiadorChange() {
  const sponsorId = val('pagamento_apoiador');
  const s = byId('pagamento_contrato');
  s.innerHTML = '<option value="">Sem contrato</option>';
  if (!sponsorId) return;
  
  const sponsorContratos = state.contratos.filter(c => c.apoiador_id === sponsorId);
  sponsorContratos.forEach(c => {
    const o = document.createElement('option');
    o.textContent = `${c.categoria.toUpperCase()} (${formatDateBR(c.data_inicio)} a ${formatDateBR(c.data_fim)})`;
    o.value = c.id;
    s.appendChild(o);
  });
}

function formatDateBR(isoDate) {
  if (!isoDate) return '';
  const parts = isoDate.split('-');
  if (parts.length === 3) return `${parts[2]}/${parts[1]}/${parts[0]}`;
  return isoDate;
}

function renderPagamentos() {
  const container = byId('lista_pagamentos');
  if (state.pagamentos.length === 0) {
    container.innerHTML = '<div style="color: var(--hint); text-align: center; padding: 12px;">Nenhum lançamento lançamento financeiro.</div>';
    return;
  }
  container.innerHTML = '';
  
  const ord = [...state.pagamentos].sort((a,b) => (b.data_vencimento || '').localeCompare(a.data_vencimento || ''));
  
  ord.forEach(p => {
    const card = document.createElement('div');
    card.className = 'item-card';
    card.id = 'pagamento_card_' + p.id;
    
    const apo = state.apoiadores.find(a => a.id === p.apoiador_id) || {};
    const valPrev = Number(p.valor_previsto || 0).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
    const valPago = Number(p.valor_pago || 0).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
    
    card.innerHTML = `
      <div>
        <div style="font-weight: 600;">${apo.nome || 'Apoiador Excluído'}</div>
        <div style="font-size: 12px; color: var(--hint);">Comp: ${p.competencia} - Previsto: ${valPrev}</div>
        <div style="font-size: 11px; color: var(--hint);">Venc: ${formatDateBR(p.data_vencimento)} | Pago: ${valPago}</div>
      </div>
      <span class="badge badge-${p.status || 'pendente'}">${p.status || 'pendente'}</span>
    `;
    card.onclick = () => editarPagamento(p);
    container.appendChild(card);
  });
}

function novoPagamento() {
  byId('form_title').textContent = 'Novo Lançamento';
  byId('pagamento_id').value = '';
  byId('pagamento_apoiador').value = '';
  byId('pagamento_contrato').innerHTML = '<option value="">Sem contrato</option>';
  byId('pagamento_competencia').value = new Date().toISOString().substring(0, 7);
  byId('pagamento_vencimento').value = '';
  byId('pagamento_previsto').value = '';
  byId('pagamento_pago').value = '0';
  byId('pagamento_data').value = '';
  byId('pagamento_forma').value = '';
  byId('pagamento_status').value = 'pendente';
  byId('pagamento_comprovante').value = '';
  byId('preview_comprovante').style.display = 'none';
  byId('pdf_status').style.display = 'none';
  byId('comprovante_link_div').style.display = 'none';
  byId('pagamento_observacoes').value = '';
  
  document.querySelectorAll('.item-card').forEach(el => el.classList.remove('selected'));
  clearErr('pagamento_apoiador');
  clearErr('pagamento_competencia');
  clearErr('pagamento_vencimento');
  clearErr('pagamento_previsto');
}

function editarPagamento(p) {
  novoPagamento();
  byId('form_title').textContent = 'Editar Lançamento';
  byId('pagamento_id').value = p.id || '';
  byId('pagamento_apoiador').value = p.apoiador_id || '';
  onApoiadorChange();
  byId('pagamento_contrato').value = p.contrato_id || '';
  byId('pagamento_competencia').value = p.competencia || '';
  byId('pagamento_vencimento').value = formatDateBR(p.data_vencimento);
  byId('pagamento_previsto').value = p.valor_previsto || '';
  byId('pagamento_pago').value = p.valor_pago || '0';
  byId('pagamento_data').value = formatDateBR(p.data_pagamento);
  byId('pagamento_forma').value = p.forma_pagamento || '';
  byId('pagamento_status').value = p.status || 'pendente';
  byId('pagamento_observacoes').value = p.observacoes || '';
  
  if (p.comprovante_url) {
    if (p.comprovante_url.endsWith('.pdf')) {
      byId('pdf_status').style.display = 'block';
    } else {
      byId('preview_comprovante').src = p.comprovante_url;
      byId('preview_comprovante').style.display = 'block';
    }
    byId('comprovante_link').href = p.comprovante_url;
    byId('comprovante_link_div').style.display = 'block';
  }
  
  const selectedCard = byId('pagamento_card_' + p.id);
  if (selectedCard) selectedCard.classList.add('selected');
}

async function carregar() {
  try {
    const data = await api('/api/apoios/dashboard', {});
    state = data;
    fillSponsors();
    renderPagamentos();
  } catch (e) {
    showToast(e.message, 4500);
  }
}

async function salvarPagamento() {
  let ok = true;
  if (!req('pagamento_apoiador', 'Apoiador')) ok = false;
  if (!req('pagamento_competencia', 'Competência')) ok = false;
  if (!req('pagamento_vencimento', 'Data de vencimento')) ok = false;
  if (!req('pagamento_previsto', 'Valor previsto')) ok = false;
  
  if (!ok) {
    scrollToFirstError();
    return;
  }
  
  const dVenc = parseDateBR(val('pagamento_vencimento'));
  if (!dVenc) { setErr('pagamento_vencimento', 'Formato DD/MM/AAAA inválido.'); ok = false; }
  
  const pDateStr = val('pagamento_data');
  if (pDateStr) {
    const dPag = parseDateBR(pDateStr);
    if (!dPag) { setErr('pagamento_data', 'Formato DD/MM/AAAA inválido.'); ok = false; }
  }
  
  if (!ok) {
    scrollToFirstError();
    return;
  }
  
  const btn = byId('btn_salvar');
  btn.disabled = true;
  btn.textContent = 'Salvando...';
  
  try {
    await api('/api/apoios/pagamentos', {
      id: val('pagamento_id'),
      apoiador_id: val('pagamento_apoiador'),
      contrato_id: val('pagamento_contrato'),
      competencia: val('pagamento_competencia'),
      data_vencimento: val('pagamento_vencimento'),
      valor_previsto: val('pagamento_previsto'),
      valor_pago: val('pagamento_pago'),
      data_pagamento: val('pagamento_data'),
      status: val('pagamento_status'),
      forma_pagamento: val('pagamento_forma'),
      comprovante_data_url: await fileData('pagamento_comprovante'),
      observacoes: val('pagamento_observacoes')
    });
    showToast('Lançamento financeiro salvo com sucesso!');
    novoPagamento();
    await carregar();
  } catch (e) {
    showToast(e.message, 4500);
  } finally {
    btn.disabled = false;
    btn.textContent = 'Salvar Financeiro';
  }
}

maskDate(byId('pagamento_vencimento'));
maskDate(byId('pagamento_data'));
carregar();
"""
    return _html_wrap("Financeiro", body, script)


async def get_apoios_financeiro(request: Request) -> HTMLResponse:
    return HTMLResponse(html_apoios_financeiro())


def html_apoios_criativos() -> str:
    body = """
<style>
.item-card { background: rgba(128,128,128,0.1); border: 1px solid var(--border); border-radius: 8px; padding: 10px; cursor: pointer; transition: all 0.2s; display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.item-card:hover { border-color: var(--btn); background: rgba(128,128,128,0.15); }
.item-card.selected { border-color: var(--btn); background: rgba(36,129,204,0.1); }
.badge { font-size: 11px; padding: 3px 8px; border-radius: 12px; font-weight: bold; text-transform: uppercase; }
.badge-ativo { background: #2ec4b6; color: #fff; }
.badge-pausado { background: #ff9f1c; color: #fff; }
.badge-encerrado { background: #7f8c8d; color: #fff; }
.sec-title { font-size: 14px; font-weight: bold; margin-bottom: 10px; color: var(--hint); display: flex; justify-content: space-between; align-items: center; }
.list-container { max-height: 250px; overflow-y: auto; margin-bottom: 15px; }
.btn-small { background: var(--btn); color: var(--btn-text); border: none; border-radius: 6px; padding: 5px 10px; font-size: 12px; cursor: pointer; font-weight: 600; }
.avatar-preview { width: 40px; height: 40px; border-radius: 4px; object-fit: cover; background: rgba(128,128,128,0.2); margin-right: 10px; display: inline-block; vertical-align: middle; }
.card-content-flex { display: flex; align-items: center; }
</style>

<div class="card">
  <div class="sec-title">
    <span>🎨 Materiais Publicitários</span>
    <button class="btn-small" onclick="novoCriativo()">+ Novo Criativo</button>
  </div>
  <div id="lista_criativos" class="list-container">Carregando...</div>
</div>

<div class="card" id="form_card">
  <div class="card-title" id="form_title">Novo Criativo</div>
  <input type="hidden" id="criativo_id">
  
  <div class="field">
    <label>Apoiador</label>
    <select id="criativo_apoiador" onchange="onApoiadorChange()">
      <option value="">Selecione...</option>
    </select>
    <span class="err" id="criativo_apoiador_err"></span>
  </div>

  <div class="field">
    <label>Contrato Relacionado (Opcional)</label>
    <select id="criativo_contrato">
      <option value="">Sem contrato</option>
    </select>
  </div>

  <div class="field">
    <label>Posicionamento / Canal</label>
    <select id="criativo_tipo">
      <option value="card_logo">Logo em Card (Listagem Principal)</option>
      <option value="rodape_diploma">Rodapé de Diploma</option>
      <option value="tela_apoiadores">Tela de Apoiadores do WebApp</option>
      <option value="ia_resposta_texto">Menção em Resposta da IA</option>
      <option value="confirmados_premium_texto">Lista de Confirmados Premium</option>
    </select>
    <span class="err" id="criativo_tipo_err"></span>
  </div>

  <div class="field">
    <label>Título do Anúncio (Opcional)</label>
    <input id="criativo_titulo" placeholder="Ex: Promoção Exclusiva">
  </div>

  <div class="field">
    <label>Texto / Copy Publicitária</label>
    <textarea id="criativo_texto" placeholder="Mensagem da publicidade que será exibida..."></textarea>
  </div>

  <div class="field">
    <label>URL de Destino / Link do Botão</label>
    <input id="criativo_link" type="url" placeholder="https://...">
  </div>

  <div class="field flex-fields" style="display: flex; gap: 10px;">
    <div style="flex: 1;">
      <label>Data Início (Opcional)</label>
      <input id="criativo_inicio" placeholder="DD/MM/AAAA">
    </div>
    <div style="flex: 1;">
      <label>Data Fim (Opcional)</label>
      <input id="criativo_fim" placeholder="DD/MM/AAAA">
    </div>
  </div>

  <div class="field flex-fields" style="display: flex; gap: 10px;">
    <div style="flex: 1;">
      <label>Prioridade / Peso</label>
      <input id="criativo_prioridade" type="number" value="1" min="1">
    </div>
    <div style="flex: 1;">
      <label>Status</label>
      <select id="criativo_status">
        <option value="ativo">Ativo</option>
        <option value="pausado">Pausado</option>
        <option value="encerrado">Encerrado</option>
      </select>
    </div>
  </div>

  <div class="field" style="display: flex; align-items: center; gap: 12px;">
    <div style="flex: 1;">
      <label>Imagem Publicitária</label>
      <input id="criativo_imagem" type="file" accept="image/*" onchange="previewImg(this)">
    </div>
    <img id="preview_imagem" class="avatar-preview" src="" style="display: none; border-radius: 6px;">
  </div>

  <div class="actions">
    <button class="btn-primary" id="btn_salvar" onclick="salvarCriativo()">Salvar Criativo</button>
  </div>
</div>
"""
    script = """
let state = { criativos: [], apoiadores: [], contratos: [] };
const byId = id => document.getElementById(id);

async function api(path, payload) {
  const resp = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...payload, init_data: tgInitData() })
  });
  const data = await resp.json();
  if (!data.ok) throw new Error(data.error || 'Falha na operação.');
  return data;
}

function previewImg(input) {
  const file = input.files[0];
  if (file) {
    const reader = new FileReader();
    reader.onload = function(e) {
      byId('preview_imagem').src = e.target.result;
      byId('preview_imagem').style.display = 'block';
    }
    reader.readAsDataURL(file);
  }
}

async function fileData(id) {
  const f = (byId(id).files || [])[0];
  if (!f) return '';
  return await new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(r.result || '');
    r.onerror = reject;
    r.readAsDataURL(f);
  });
}

function fillSponsors() {
  const s = byId('criativo_apoiador');
  s.innerHTML = '<option value="">Selecione...</option>';
  state.apoiadores.forEach(a => {
    const o = document.createElement('option');
    o.textContent = a.nome;
    o.value = a.id;
    s.appendChild(o);
  });
}

function onApoiadorChange() {
  const sponsorId = val('criativo_apoiador');
  const s = byId('criativo_contrato');
  s.innerHTML = '<option value="">Sem contrato</option>';
  if (!sponsorId) return;
  
  const sponsorContratos = state.contratos.filter(c => c.apoiador_id === sponsorId);
  sponsorContratos.forEach(c => {
    const o = document.createElement('option');
    o.textContent = `${c.categoria.toUpperCase()} (${formatDateBR(c.data_inicio)} a ${formatDateBR(c.data_fim)})`;
    o.value = c.id;
    s.appendChild(o);
  });
}

function formatDateBR(isoDate) {
  if (!isoDate) return '';
  const parts = isoDate.split('-');
  if (parts.length === 3) return `${parts[2]}/${parts[1]}/${parts[0]}`;
  return isoDate;
}

function renderCriativos() {
  const container = byId('lista_criativos');
  if (state.criativos.length === 0) {
    container.innerHTML = '<div style="color: var(--hint); text-align: center; padding: 12px;">Nenhum criativo cadastrado.</div>';
    return;
  }
  container.innerHTML = '';
  state.criativos.forEach(c => {
    const card = document.createElement('div');
    card.className = 'item-card';
    card.id = 'criativo_card_' + c.id;
    
    const apo = state.apoiadores.find(a => a.id === c.apoiador_id) || {};
    const imgHtml = c.imagem_url ? `<img class="avatar-preview" src="${c.imagem_url}">` : '<div class="avatar-preview" style="display: inline-flex; align-items: center; justify-content: center; font-weight: bold; font-size: 18px; color: var(--hint);">🎨</div>';
    
    card.innerHTML = `
      <div class="card-content-flex">
        ${imgHtml}
        <div>
          <div style="font-weight: 600;">${c.titulo || 'Sem título'} - ${apo.nome || 'Apoiador Excluído'}</div>
          <div style="font-size: 12px; color: var(--hint);">${c.tipo_posicionamento.toUpperCase()}</div>
        </div>
      </div>
      <span class="badge badge-${c.status || 'ativo'}">${c.status || 'ativo'}</span>
    `;
    card.onclick = () => editarCriativo(c);
    container.appendChild(card);
  });
}

function novoCriativo() {
  byId('form_title').textContent = 'Novo Criativo';
  byId('criativo_id').value = '';
  byId('criativo_apoiador').value = '';
  byId('criativo_contrato').innerHTML = '<option value="">Sem contrato</option>';
  byId('criativo_tipo').value = 'tela_apoiadores';
  byId('criativo_titulo').value = '';
  byId('criativo_texto').value = '';
  byId('criativo_link').value = '';
  byId('criativo_inicio').value = '';
  byId('criativo_fim').value = '';
  byId('criativo_prioridade').value = 1;
  byId('criativo_status').value = 'ativo';
  byId('criativo_imagem').value = '';
  byId('preview_imagem').style.display = 'none';
  
  document.querySelectorAll('.item-card').forEach(el => el.classList.remove('selected'));
  clearErr('criativo_apoiador');
  clearErr('criativo_tipo');
}

function editarCriativo(c) {
  novoCriativo();
  byId('form_title').textContent = 'Editar Criativo';
  byId('criativo_id').value = c.id || '';
  byId('criativo_apoiador').value = c.apoiador_id || '';
  onApoiadorChange();
  byId('criativo_contrato').value = c.contrato_id || '';
  byId('criativo_tipo').value = c.tipo_posicionamento || 'tela_apoiadores';
  byId('criativo_titulo').value = c.titulo || '';
  byId('criativo_texto').value = c.texto || '';
  byId('criativo_link').value = c.link_url || '';
  byId('criativo_inicio').value = formatDateBR(c.data_inicio);
  byId('criativo_fim').value = formatDateBR(c.data_fim);
  byId('criativo_prioridade').value = c.prioridade || 1;
  byId('criativo_status').value = c.status || 'ativo';
  
  if (c.imagem_url) {
    byId('preview_imagem').src = c.imagem_url;
    byId('preview_imagem').style.display = 'block';
  }
  
  const selectedCard = byId('criativo_card_' + c.id);
  if (selectedCard) selectedCard.classList.add('selected');
}

async function carregar() {
  try {
    const data = await api('/api/apoios/dashboard', {});
    state = data;
    fillSponsors();
    renderCriativos();
  } catch (e) {
    showToast(e.message, 4500);
  }
}

async function salvarCriativo() {
  let ok = true;
  if (!req('criativo_apoiador', 'Apoiador')) ok = false;
  if (!req('criativo_tipo', 'Posicionamento')) ok = false;
  
  if (!ok) {
    scrollToFirstError();
    return;
  }
  
  const cIni = val('criativo_inicio');
  if (cIni) {
    const dIni = parseDateBR(cIni);
    if (!dIni) { setErr('criativo_inicio', 'Formato DD/MM/AAAA inválido.'); ok = false; }
  }
  
  const cFim = val('criativo_fim');
  if (cFim) {
    const dFim = parseDateBR(cFim);
    if (!dFim) { setErr('criativo_fim', 'Formato DD/MM/AAAA inválido.'); ok = false; }
  }
  
  if (!ok) {
    scrollToFirstError();
    return;
  }
  
  const btn = byId('btn_salvar');
  btn.disabled = true;
  btn.textContent = 'Salvando...';
  
  try {
    await api('/api/apoios/criativos', {
      id: val('criativo_id'),
      apoiador_id: val('criativo_apoiador'),
      contrato_id: val('criativo_contrato'),
      tipo_posicionamento: val('criativo_tipo'),
      titulo: val('criativo_titulo'),
      texto: val('criativo_texto'),
      link_url: val('criativo_link'),
      data_inicio: val('criativo_inicio'),
      data_fim: val('criativo_fim'),
      prioridade: val('criativo_prioridade'),
      status: val('criativo_status'),
      imagem_data_url: await fileData('criativo_imagem')
    });
    showToast('Material publicitário salvo com sucesso!');
    novoCriativo();
    await carregar();
  } catch (e) {
    showToast(e.message, 4500);
  } finally {
    btn.disabled = false;
    btn.textContent = 'Salvar Criativo';
  }
}

maskDate(byId('criativo_inicio'));
maskDate(byId('criativo_fim'));
carregar();
"""
    return _html_wrap("Criativos", body, script)


async def get_apoios_criativos(request: Request) -> HTMLResponse:
    return HTMLResponse(html_apoios_criativos())


# ─────────────────────────────────────────────────────────────────────────────
# API — LISTAR LOJAS (para o form de evento)
# ─────────────────────────────────────────────────────────────────────────────

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

    nivel = str(get_nivel(int(telegram_id)))
    lojas = listar_lojas(int(telegram_id), include_todas=(nivel == "3")) or []
    result = []
    for lj in lojas:
        result.append({
            "id":       str(lj.get("ID") or lj.get("id") or ""),
            "nome":     lj.get("Nome da Loja", ""),
            "numero":   str(lj.get("Número") or "0"),
            "oriente":  lj.get("Oriente da Loja") or lj.get("Oriente", ""),
            "rito":     lj.get("Rito", ""),
            "potencia": lj.get("Potência", ""),
            "potencia_complemento": lj.get("Potência complemento", ""),
            "endereco": lj.get("Endereço", ""),
            "secretario_responsavel_id": str(lj.get("Telegram ID do secretário responsável") or lj.get("secretario_responsavel_id") or lj.get("Telegram ID") or ""),
            "secretario_responsavel_nome": lj.get("Nome do secretário responsável") or lj.get("secretario_responsavel_nome") or "",
            "template_sessao_url": lj.get("Template sessão URL") or lj.get("template_sessao_url") or "",
            "status_template": lj.get("Status template") or lj.get("status_template") or "",
            "estado_uf": lj.get("Estado UF") or lj.get("estado_uf") or "",
            "cidade": lj.get("Cidade") or lj.get("cidade") or "",
        })
    return JSONResponse({"ok": True, "lojas": result, "nivel": nivel})


# ─────────────────────────────────────────────────────────────────────────────
# API — CADASTRO DE MEMBRO
# ─────────────────────────────────────────────────────────────────────────────

async def api_cadastro_membro(request: Request) -> JSONResponse:
    bot_token: str = request.app.state.bot_token
    try:
        body: dict = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "JSON inválido."}, status_code=400)

    init_data = (body.get("init_data") or "").strip()
    user = verify_telegram_webapp_data(init_data, bot_token)
    if not user:
        return JSONResponse({"ok": False, "error": "Não autorizado."}, status_code=403)

    telegram_id = user.get("id")
    if not telegram_id:
        return JSONResponse({"ok": False, "error": "Usuário não identificado."}, status_code=403)
    if not await _usuario_esta_no_grupo(request.app.state.telegram_app.bot, int(telegram_id)):
        return JSONResponse(
            {
                "ok": False,
                "error": "Seu cadastro só pode ser concluído por quem está participando do grupo do Bode Andarilho no momento.",
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
        return JSONResponse({"ok": False, "error": "Preencha todos os campos obrigatórios."}, status_code=400)
    if not validar_potencia(potencia, potencia_complemento):
        return JSONResponse({"ok": False, "error": "Informe a potência principal e a potência local."}, status_code=400)

    try:
        datetime.strptime(data_nasc, "%d/%m/%Y")
    except ValueError:
        return JSONResponse({"ok": False, "error": "Data de nascimento inválida (DD/MM/AAAA)."}, status_code=400)

    graus_validos = {"Aprendiz", "Companheiro", "Mestre", "Mestre Instalado"}
    if grau not in graus_validos:
        return JSONResponse({"ok": False, "error": "Grau inválido."}, status_code=400)

    ja_existe = buscar_membro(int(telegram_id))

    app = request.app.state.telegram_app
    user_data = app.user_data.get(int(telegram_id)) or {}
    
    status = "Pendente"
    nivel = "0"
    status_auditoria = ""
    is_sec = False
    
    if user_data.get("token_cadastro_secretario"):
        status_auditoria = "Pendente_Secretario"
        is_sec = True
    elif user_data.get("cadastro_voucher"):
        status = "Ativo"
        nivel = "1"

    dados: Dict[str, Any] = {
        "Telegram ID":        str(telegram_id),
        "Nome":               nome,
        "Data de nascimento": data_nasc,
        "Grau":               grau,
        "Venerável Mestre":   vm,
        "Loja":               loja,
        "Número da loja":     numero_loja,
        "Oriente":            oriente,
        "Potência":           potencia,
        "Potência complemento": potencia_complemento,
        "Status":             status,
        "Nivel":              nivel,
        "Status Auditoria":   status_auditoria,
    }

    ok = cadastrar_membro(dados)
    if not ok:
        return JSONResponse({"ok": False, "error": "Falha ao salvar. Tente novamente."}, status_code=500)

    if is_sec:
        try:
            from src.cadastro import notificar_secretario_pendente_adm
            membro_novo = buscar_membro(int(telegram_id))
            if membro_novo:
                await notificar_secretario_pendente_adm(app, membro_novo)
        except Exception as e_notif:
            logger.warning("Erro ao notificar admin de secretario pendente via API: %s", e_notif)

    try:
        bot = request.app.state.telegram_app.bot
        nome_esc = _escape_md(nome)
        if is_sec:
            msg = (
                f"✅ *Cadastro realizado com sucesso\\!*\n\n"
                f"Prezado Ir\\.·\\. {nome_esc}, seu cadastro de Secretário foi encaminhado para a aprovação da Administração Geral\\.\n\n"
                f"Você será notificado aqui assim que as suas credenciais forem homologadas\\."
            )
        elif ja_existe:
            msg = f"✅ *Cadastro atualizado\\!*\n\nSaudações, Ir\\.·\\. {nome_esc}\\. Seus dados foram atualizados\\."
        else:
            msg = (
                f"✅ *Cadastro realizado a contento\\!*\n\n"
                f"Bem\\-vindo ao Bode Andarilho, Ir\\.·\\. {nome_esc}\\!\n"
                f"Use /start para acessar o Painel do Obreiro\\."
            )
        await bot.send_message(chat_id=telegram_id, text=msg, parse_mode="MarkdownV2")
    except Exception as e:
        logger.warning("Falha ao enviar confirmação de cadastro para %s: %s", telegram_id, e)

    return JSONResponse({"ok": True})


# ─────────────────────────────────────────────────────────────────────────────
# API — CADASTRO DE LOJA
# ─────────────────────────────────────────────────────────────────────────────

async def api_cadastro_loja(request: Request) -> JSONResponse:
    bot_token: str = request.app.state.bot_token
    try:
        body: dict = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "JSON inválido."}, status_code=400)

    init_data = (body.get("init_data") or "").strip()
    user = verify_telegram_webapp_data(init_data, bot_token)
    if not user:
        return JSONResponse({"ok": False, "error": "Não autorizado."}, status_code=403)

    telegram_id = user.get("id")
    if not telegram_id:
        return JSONResponse({"ok": False, "error": "Usuário não identificado."}, status_code=403)

    nome     = (body.get("nome")     or "").strip()[:200]
    numero   = (body.get("numero")   or "0").strip()[:10]
    oriente  = (body.get("oriente")  or "").strip()[:200]
    rito_raw = (body.get("rito")     or "").strip()[:200]
    rito_outro = (body.get("rito_outro") or "").strip()[:200]
    if rito_raw == "Outro" and rito_outro:
        rito_raw = rito_outro
    rito = normalizar_rito(rito_raw) or rito_raw
    potencia, potencia_complemento = normalizar_potencia(
        (body.get("potencia") or "").strip()[:200],
        (body.get("potencia_outra") or body.get("potencia_complemento") or "").strip()[:200],
    )
    endereco = (body.get("endereco") or "").strip()[:400]

    if not all([nome, oriente, rito, potencia, endereco]):
        return JSONResponse({"ok": False, "error": "Preencha todos os campos obrigatórios."}, status_code=400)
    if not validar_potencia(potencia, potencia_complemento):
        return JSONResponse({"ok": False, "error": "Informe a potência principal e a potência local."}, status_code=400)

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

    # Hook Conquistas Coletivas
    try:
        from src.conquistas import checar_e_disparar_marco_coletivo
        bot = request.app.state.telegram_app.bot
        asyncio.create_task(checar_e_disparar_marco_coletivo(bot, dados_loja))
    except Exception:
        pass

    try:
        bot = request.app.state.telegram_app.bot
        nome_esc = _escape_md(nome)
        await bot.send_message(
            chat_id=telegram_id,
            text=f"✅ *Loja cadastrada\\!*\n\n🏛 *{nome_esc}* registrada com sucesso\\.\nEla estará disponível como atalho no cadastro de eventos\\.",
            parse_mode="MarkdownV2",
        )
    except Exception as e:
        logger.warning("Falha ao confirmar cadastro de loja para %s: %s", telegram_id, e)

    return JSONResponse({"ok": True})


# ─────────────────────────────────────────────────────────────────────────────
# API — CADASTRO DE EVENTO
# ─────────────────────────────────────────────────────────────────────────────

async def api_cadastro_evento(request: Request) -> JSONResponse:
    bot_token: str = request.app.state.bot_token
    try:
        body: dict = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "JSON inválido."}, status_code=400)

    init_data = (body.get("init_data") or "").strip()
    user = verify_telegram_webapp_data(init_data, bot_token)
    if not user:
        return JSONResponse({"ok": False, "error": "Não autorizado."}, status_code=403)

    telegram_id = user.get("id")
    if not telegram_id:
        return JSONResponse({"ok": False, "error": "Usuário não identificado."}, status_code=403)

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
    rito_raw    = (body.get("rito")       or "").strip()[:200]
    rito_outro  = (body.get("rito_outro") or "").strip()[:200]
    if rito_raw == "Outro" and rito_outro:
        rito_raw = rito_outro
    rito        = normalizar_rito(rito_raw) or rito_raw
    potencia, potencia_complemento = normalizar_potencia(
        (body.get("potencia") or "").strip()[:200],
        (body.get("potencia_outra") or body.get("potencia_complemento") or "").strip()[:200],
    )
    endereco    = (body.get("endereco")   or "").strip()[:400]

    if not all([data_str, horario, grau, tipo_sessao, traje, agape, nome_loja, oriente, rito, potencia, endereco]):
        return JSONResponse({"ok": False, "error": "Preencha todos os campos obrigatórios."}, status_code=400)
        
    # Validação do limite de 4 sessões ativas por Loja ou por Secretário
    nivel = str(get_nivel(int(telegram_id)))
    if nivel != "3":
        loja_id = body.get("loja_id") or body.get("ID da loja")
        from src.sheets_supabase import contar_sessoes_ativas_loja, contar_sessoes_ativas_secretario
        if (contar_sessoes_ativas_loja(loja_id, nome_loja, numero_loja, potencia) >= 4 or
            contar_sessoes_ativas_secretario(telegram_id) >= 4):
            return JSONResponse({
                "ok": False,
                "error": "Limite de 4 sessões futuras/ativas atingido para esta Loja ou Secretário. Publicar poucas sessões mantém a agenda útil e evita despejar o calendário anual de uma vez."
            }, status_code=400)
        
    if not validar_potencia(potencia, potencia_complemento):
        return JSONResponse({"ok": False, "error": "Informe a potência principal e a potência local."}, status_code=400)

    dt = _parse_data_ddmmyyyy(data_str)
    if not dt:
        return JSONResponse({"ok": False, "error": "Data inválida. Use DD/MM/AAAA."}, status_code=400)

    hoje = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    if dt < hoje:
        return JSONResponse({"ok": False, "error": "A data não pode ser no passado."}, status_code=400)

    dia_semana = _dia_semana_pt_br(dt)

    evento: Dict[str, Any] = {
        "Data do evento":              data_str,
        "Dia da semana":               dia_semana,
        "Hora":                        horario,
        "Nome da loja":                nome_loja,
        "Número da loja":              numero_loja,
        "Oriente":                     oriente,
        "Grau":                        grau,
        "Tipo de sessão":              tipo_sessao,
        "Rito":                        rito,
        "Potência":                    potencia,
        "Potência complemento":        potencia_complemento,
        "Traje obrigatório":           traje,
        "Ágape":                       agape,
        "Observações":                 observacoes,
        "Telegram ID do grupo":        _GRUPO_PRINCIPAL_ID,
        "Telegram ID do secretário":   str(telegram_id),
        "Status":                      "Ativo",
        "Endereço da sessão":          endereco,
    }

    id_evento = cadastrar_evento(evento)
    if not id_evento:
        return JSONResponse({"ok": False, "error": "Falha ao salvar o evento. Tente novamente."}, status_code=500)

    # Publicar no grupo e notificar secretário
    try:
        bot = request.app.state.telegram_app.bot

        import asyncio
        async def task_segura():
            try:
                await _publicar_evento_no_grupo(request.app.state.telegram_app, id_evento, dict(evento))
            except Exception as e:
                logger.error("ERRO GRAVE NA TASK BACKGROUND DE PUBLICACAO: %s", e, exc_info=True)
        t = asyncio.create_task(task_segura())
        _BACKGROUND_TASKS.add(t)
        t.add_done_callback(_BACKGROUND_TASKS.discard)
    except Exception as e:
        logger.warning("Falha ao agendar publicacao do evento %s no grupo para %s: %s", id_evento, telegram_id, e)

    try:
        await bot.send_message(
            chat_id=telegram_id,
            text="✅ *Evento cadastrado e publicado no grupo\\!*",
            parse_mode="MarkdownV2",
        )
    except Exception as e:
        logger.warning("Falha ao confirmar evento para %s: %s", telegram_id, e)

    return JSONResponse({"ok": True})


# ─────────────────────────────────────────────────────────────────────────────
# MÓDULO SALA DE TROFÉUS (GALERIA DE CONQUISTAS)
# ─────────────────────────────────────────────────────────────────────────────

def html_galeria() -> str:
    """Retorna o layout premium dark mode / glassmorphism para o Mini App."""
    styles = """
:root {
  --gold: #d4af37;
  --gold-light: #f3e5ab;
  --bg-dark: #0d0f14;
  --card-bg: rgba(255, 255, 255, 0.04);
  --card-border: rgba(255, 255, 255, 0.06);
  --text-primary: #f0f2f5;
  --text-secondary: #9ca3af;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
  background: linear-gradient(180deg, #111827 0%, #030712 100%);
  color: var(--text-primary);
  min-height: 100vh;
  padding: 16px 16px 80px;
  -webkit-font-smoothing: antialiased;
}
.header-premium {
  text-align: center;
  margin-bottom: 24px;
  padding: 24px 16px;
  background: linear-gradient(135deg, rgba(255,255,255,0.03) 0%, rgba(255,255,255,0.01) 100%);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  border-radius: 20px;
  border: 1px solid var(--card-border);
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.3);
}
.header-premium h1 {
  font-family: 'Cinzel', serif;
  font-size: 20px;
  font-weight: 700;
  background: linear-gradient(90deg, var(--gold) 0%, var(--gold-light) 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  margin-bottom: 6px;
  letter-spacing: 1.5px;
}
.header-premium .subtitle {
  font-size: 13px;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.section-title {
  font-family: 'Cinzel', serif;
  font-size: 14px;
  font-weight: 700;
  color: var(--gold);
  letter-spacing: 1px;
  margin: 28px 0 14px 4px;
  display: flex;
  align-items: center;
  gap: 10px;
  text-transform: uppercase;
}
.section-title::after {
  content: '';
  flex-grow: 1;
  height: 1px;
  background: linear-gradient(to right, rgba(212, 175, 55, 0.3), transparent);
}
.grid-badges {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
}
@media (min-width: 480px) {
  .grid-badges { grid-template-columns: repeat(4, 1fr); }
}
.badge-card {
  background: var(--card-bg);
  border: 1px solid var(--card-border);
  border-radius: 16px;
  padding: 16px 8px 12px;
  text-align: center;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
  cursor: pointer;
}
.badge-card:active {
  transform: scale(0.94);
  background: rgba(255, 255, 255, 0.07);
}
.badge-card.locked {
  opacity: 0.35;
  filter: grayscale(100%);
}
.badge-card.unlocked {
  border-color: rgba(212, 175, 55, 0.25);
  box-shadow: 0 4px 20px rgba(212, 175, 55, 0.04);
}
.badge-icon {
  width: 56px;
  height: 56px;
  margin: 0 auto 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(212,175,55,0.15) 0%, rgba(212,175,55,0.02) 100%);
  font-family: 'Cinzel', serif;
  font-weight: 700;
  font-size: 20px;
  color: var(--gold);
  border: 1px solid rgba(212, 175, 55, 0.4);
  box-shadow: inset 0 0 12px rgba(212,175,55,0.12);
}
.locked .badge-icon {
  background: rgba(255,255,255,0.03);
  color: #777;
  border-color: rgba(255,255,255,0.1);
  box-shadow: none;
}
.badge-title {
  font-size: 11px;
  font-weight: 600;
  line-height: 1.3;
  color: var(--text-primary);
  height: 2.6em;
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}
.list-item-glass {
  background: var(--card-bg);
  border: 1px solid var(--card-border);
  border-radius: 14px;
  padding: 14px 16px;
  margin-bottom: 10px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  backdrop-filter: blur(4px);
}
.item-info h4 {
  font-size: 14px;
  font-weight: 600;
  margin-bottom: 3px;
}
.item-info p {
  font-size: 12px;
  color: var(--text-secondary);
}
.badge-pill {
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  padding: 5px 10px;
  border-radius: 20px;
  background: rgba(212, 175, 55, 0.12);
  color: var(--gold);
  border: 1px solid rgba(212, 175, 55, 0.25);
}
.loader {
  grid-column: 1 / -1;
  text-align: center;
  padding: 40px 0;
  color: var(--text-secondary);
  font-size: 13px;
  letter-spacing: 0.5px;
}
"""

    body = """
<div class="header-premium">
  <h1 id="el_nome">CARREGANDO OBREIRO...</h1>
  <div class="subtitle" id="el_loja">Aguardando conexão digital...</div>
</div>

<div class="section-title">🎖️ Medalhas Individuais</div>
<div class="grid-badges" id="el_grid">
  <div class="loader">Solicitando arquivos da Chancelaria...</div>
</div>

<div class="section-title">🏛️ Vigor da Oficina (6 Meses)</div>
<div id="el_vigor_lista">
  <div class="loader">Processando atas de presença...</div>
</div>

<div class="section-title">🌍 Expansão Coletiva</div>
<div id="el_exp_lista">
  <div class="loader">Sincronizando coordenadas...</div>
</div>
"""

    script = """
(async () => {
  try {
    const resp = await fetch('/api/galeria', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ init_data: tgInitData() })
    });
    
    const dados = await resp.json();
    if (!dados.ok) {
      document.body.innerHTML = `<div style="padding:40px 20px; text-align:center; color:#ef4444; font-weight:600;">Acesso não autorizado. Por favor abra através do Bot oficial.</div>`;
      return;
    }
    
    // Preenchimento
    document.getElementById('el_nome').textContent = dados.nome_membro.toUpperCase();
    document.getElementById('el_loja').textContent = dados.nome_loja;
    
    // 1. Grid Medalhas
    const grid = document.getElementById('el_grid');
    grid.innerHTML = '';
    dados.conquistas_individuais.forEach(b => {
      const card = document.createElement('div');
      card.className = `badge-card ${b.desbloqueada ? 'unlocked' : 'locked'}`;
      card.onclick = () => {
        if (tg && tg.showAlert) {
          tg.showAlert(`${b.titulo}\\n\\n${b.descricao}\\n\\nStatus: ${b.desbloqueada ? 'DESBLOQUEADA ✅' : 'BLOQUEADA 🔒'}`);
        } else {
          alert(`${b.titulo}\\n${b.descricao}`);
        }
      };
      
      const icon = document.createElement('div');
      icon.className = 'badge-icon';
      icon.textContent = b.slug.toUpperCase();
      
      const title = document.createElement('div');
      title.className = 'badge-title';
      title.textContent = b.titulo.replace('Iniciado na ', '').replace('Mestre dos ', '').replace('Estrela de ', '');
      
      card.appendChild(icon);
      card.appendChild(title);
      grid.appendChild(card);
    });
    
    // 2. Vigor Oficina
    const vigorBox = document.getElementById('el_vigor_lista');
    vigorBox.innerHTML = '';
    if (!dados.marcos_oficina || dados.marcos_oficina.length === 0) {
      vigorBox.innerHTML = '<div style="text-align:center; font-size:12px; padding:10px; color:#6b7280;">Nenhum selo de vigor computado recentemente.</div>';
    } else {
      dados.marcos_oficina.forEach(v => {
        const div = document.createElement('div');
        div.className = 'list-item-glass';
        
        let pills = [];
        if (v.excelencia) pills.push('<span class="badge-pill">Oficina de Excelência</span>');
        if (v.farol) pills.push('<span class="badge-pill" style="margin-left:4px;">Farol da Região</span>');
        
        div.innerHTML = `
          <div class="item-info">
            <h4>${v.mes_formatado}</h4>
            <p>Histórico de Vigor Administrativo</p>
          </div>
          <div>${pills.join('')}</div>
        `;
        vigorBox.appendChild(div);
      });
    }
    
    // 3. Expansao
    const expBox = document.getElementById('el_exp_lista');
    expBox.innerHTML = '';
    if (!dados.marcos_expansao || dados.marcos_expansao.length === 0) {
      expBox.innerHTML = '<div style="text-align:center; font-size:12px; padding:10px; color:#6b7280;">Expandindo colunas pelo território nacional.</div>';
    } else {
      dados.marcos_expansao.forEach(e => {
        const div = document.createElement('div');
        div.className = 'list-item-glass';
        div.innerHTML = `
          <div class="item-info">
            <h4>${e.titulo}</h4>
            <p>Marco Global de Integração</p>
          </div>
          <span class="badge-pill">🚩 EXPANSÃO</span>
        `;
        expBox.appendChild(div);
      });
    }
    
    // Deep linking startapp trigger
    if (tg && tg.initDataUnsafe && tg.initDataUnsafe.start_param === 'galeria') {
      try {
        tg.HapticFeedback.notificationOccurred('success');
      } catch(h){}
    }
    
  } catch (e) {
    console.error(e);
    document.body.innerHTML = `<div style="padding:40px 20px; text-align:center; color:#ef4444;">Falha crítica ao conectar com o backend.</div>`;
  }
})();
"""

    return (
        f'<!DOCTYPE html><html lang="pt-BR">'
        f'<head><meta charset="UTF-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">'
        f'<link href="https://fonts.googleapis.com/css2?family=Cinzel:wght@700&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">'
        f'<title>Sala de Troféus — Bode Andarilho</title>'
        f'<script src="https://telegram.org/js/telegram-web-app.js"></script>'
        f'<style>{styles}</style></head>'
        f'<body>'
        f'{body}'
        f'<script>{_JS_BASE}{script}</script>'
        f'</body></html>'
    )


async def get_galeria(request: Request) -> HTMLResponse:
    """Serve a interface gráfica web do Módulo de Conquistas."""
    return HTMLResponse(html_galeria())


async def api_galeria(request: Request) -> JSONResponse:
    """Endpoint API autenticado que alimenta os dados da Sala de Troféus."""
    bot_token: str = request.app.state.bot_token
    try:
        body: dict = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "JSON inválido."}, status_code=400)

    init_data = (body.get("init_data") or "").strip()
    user = verify_telegram_webapp_data(init_data, bot_token)
    if not user:
        return JSONResponse({"ok": False, "error": "Não autorizado."}, status_code=403)

    telegram_id = user.get("id")
    if not telegram_id:
        return JSONResponse({"ok": False, "error": "Usuário não identificado."}, status_code=403)

    from src.sheets_supabase import buscar_membro, get_galeria_completa
    
    membro = buscar_membro(int(telegram_id))
    if not membro:
        return JSONResponse({"ok": False, "error": "Membro não cadastrado."}, status_code=404)
        
    loja_id = membro.get("loja_id") or membro.get("ID da loja")
    nome_membro = membro.get("Nome") or membro.get("nome") or "Obreiro"
    
    dados = get_galeria_completa(int(telegram_id), loja_id)
    dados["nome_membro"] = nome_membro
    dados["ok"] = True
    
    return JSONResponse(dados)

