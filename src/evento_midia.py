from __future__ import annotations

import logging
import mimetypes
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import requests
from telegram import InputMediaPhoto
from telegram.ext import ContextTypes

from src.render_cards import render_event_card
from src.sheets_supabase import (
    atualizar_evento,
    buscar_loja_por_id,
    buscar_loja_por_nome_numero,
    upload_storage_publico,
)

logger = logging.getLogger(__name__)

BUCKET_EVENT_CARDS = os.getenv("SUPABASE_EVENT_CARDS_BUCKET", "event-cards")
CAPTION_PUBLICACAO_VISUAL = "Confirme sua presença pelos botões abaixo."


@dataclass
class MidiaEvento:
    modo: str
    path: Optional[str] = None
    url: str = ""
    file_id: str = ""
    erro: str = ""


def _norm(value: Any) -> str:
    return "" if value is None else str(value).strip()


def obter_loja_evento(evento: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    loja_id = _norm(evento.get("ID da loja") or evento.get("loja_id"))
    if loja_id:
        loja = buscar_loja_por_id(loja_id)
        if loja:
            return loja
    return buscar_loja_por_nome_numero(evento.get("Nome da loja"), evento.get("Número da loja"))


def _baixar_url_para_temp(url: str, prefix: str = "bode_event_card_") -> Optional[str]:
    if not url:
        return None
    if not url.startswith(("http://", "https://")) and os.path.exists(url):
        return url
    try:
        resp = requests.get(url, timeout=25)
        resp.raise_for_status()
        ext = ".jpg"
        ctype = resp.headers.get("content-type", "")
        if "png" in ctype:
            ext = ".png"
        elif "webp" in ctype:
            ext = ".webp"
        path = os.path.join(tempfile.gettempdir(), f"{prefix}{abs(hash(url))}{ext}")
        with open(path, "wb") as f:
            f.write(resp.content)
        return path
    except Exception as e:
        logger.warning("Falha ao baixar card especial %s: %s", url, e)
        return None


def preparar_midia_evento(evento: Dict[str, Any]) -> MidiaEvento:
    modo = _norm(evento.get("Modo visual") or evento.get("modo_visual"))
    card_especial = _norm(evento.get("Card especial URL") or evento.get("card_especial_url"))
    if modo == "card_especial" and card_especial:
        path = _baixar_url_para_temp(card_especial, "bode_event_special_")
        if path:
            return MidiaEvento(modo="card_especial", path=path, url=card_especial)
        return MidiaEvento(modo="texto_fallback", erro="Card especial indisponível.")

    loja = obter_loja_evento(evento) or {}
    try:
        rendered = render_event_card(evento, loja)
        modo_render = "template_loja" if loja else "template_padrao"
        return MidiaEvento(modo=modo_render, path=rendered.path)
    except Exception as e:
        logger.warning("Falha ao renderizar card do evento %s: %s", evento.get("ID Evento"), e)
        return MidiaEvento(modo="texto_fallback", erro=str(e))



def salvar_render_no_storage(evento: Dict[str, Any], path: str) -> str:
    id_evento = _norm(evento.get("ID Evento") or evento.get("id_evento"))
    if not id_evento or not path or not os.path.exists(path):
        return ""
    ext = Path(path).suffix.lower() or ".png"
    content_type = mimetypes.types_map.get(ext, "image/png")
    with open(path, "rb") as f:
        url = upload_storage_publico(BUCKET_EVENT_CARDS, f"eventos/{id_evento}/render{ext}", f.read(), content_type)
    return url or ""


async def publicar_evento_no_grupo(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    evento: Dict[str, Any],
    texto_fallback: str,
    reply_markup,
):
    midia = preparar_midia_evento(evento)
    if midia.path:
        try:
            with open(midia.path, "rb") as photo:
                msg = await context.bot.send_photo(
                    chat_id=chat_id,
                    photo=photo,
                    caption=CAPTION_PUBLICACAO_VISUAL,
                    reply_markup=reply_markup,
                )
            photos = getattr(msg, "photo", None) or []
            file_id = photos[-1].file_id if photos else ""
            sync = {
                "ID Evento": evento.get("ID Evento"),
                "Modo visual": midia.modo,
                "Telegram tipo mensagem grupo": "photo",
            }
            if midia.modo in ("template_loja", "card_especial"):
                url = salvar_render_no_storage(evento, midia.path)
                if url:
                    sync["Card renderizado URL"] = url
                    evento["Card renderizado URL"] = url
                    if midia.modo == "card_especial":
                        sync["Card especial URL"] = url
                        evento["Card especial URL"] = url
            if file_id:
                sync["Card file_id Telegram"] = file_id
            atualizar_evento(0, sync)
            return msg, "photo"
        except Exception as e:
            logger.warning("Falha ao enviar card visual; usando texto fallback: %s", e)

    msg = await context.bot.send_message(
        chat_id=chat_id,
        text=texto_fallback,
        parse_mode="Markdown",
        reply_markup=reply_markup,
    )
    atualizar_evento(0, {
        "ID Evento": evento.get("ID Evento"),
        "Modo visual": "texto_fallback",
        "Telegram tipo mensagem grupo": "text",
    })
    return msg, "text"


async def enviar_previa_evento(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    evento: Dict[str, Any],
    reply_markup,
    texto_fallback: str,
):
    midia = preparar_midia_evento(evento)
    if midia.path:
        try:
            with open(midia.path, "rb") as photo:
                return await context.bot.send_photo(
                    chat_id=chat_id,
                    photo=photo,
                    caption=CAPTION_PUBLICACAO_VISUAL,
                    reply_markup=reply_markup,
                )
        except Exception as e:
            logger.warning("Falha ao enviar prévia visual; usando texto: %s", e)
    return await context.bot.send_message(
        chat_id=chat_id,
        text=texto_fallback,
        parse_mode="Markdown",
        reply_markup=reply_markup,
    )


async def editar_ou_republicar_evento_visual(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    message_id: int,
    evento: Dict[str, Any],
    texto_fallback: str,
    reply_markup,
) -> bool:
    midia = preparar_midia_evento(evento)
    if midia.path:
        try:
            with open(midia.path, "rb") as photo:
                await context.bot.edit_message_media(
                    chat_id=chat_id,
                    message_id=message_id,
                    media=InputMediaPhoto(photo, caption=CAPTION_PUBLICACAO_VISUAL),
                    reply_markup=reply_markup,
                )
            atualizar_evento(0, {
                "ID Evento": evento.get("ID Evento"),
                "Modo visual": midia.modo,
                "Telegram tipo mensagem grupo": "photo",
            })
            return True
        except Exception as e:
            logger.warning("Falha ao editar card visual do evento %s: %s", evento.get("ID Evento"), e)

    try:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=texto_fallback,
            parse_mode="Markdown",
            reply_markup=reply_markup,
        )
        atualizar_evento(0, {
            "ID Evento": evento.get("ID Evento"),
            "Modo visual": "texto_fallback",
            "Telegram tipo mensagem grupo": "text",
        })
        return True
    except Exception as e:
        logger.warning("Falha ao editar fallback textual do evento %s: %s", evento.get("ID Evento"), e)
        return False
