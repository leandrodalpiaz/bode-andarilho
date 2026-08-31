from __future__ import annotations

import os
import uuid
from typing import Any

import httpx


def _public_base_url() -> str:
    return (os.getenv("PWA_PUBLIC_BASE_URL") or os.getenv("RENDER_EXTERNAL_URL") or "").strip().rstrip("/")


def _api_error(payload: Any) -> str:
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict) and error.get("message"):
            return str(error["message"])
    return "não foi possível concluir a associação"


async def vincular_telegram(update: Any, context: Any) -> None:
    """Consome, no privado, o código emitido pela PWA para vincular o Telegram."""

    message = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    if not message or not user:
        return
    if chat and chat.type != "private":
        await message.reply_text("Por segurança, execute /vincular no chat privado com o bot.")
        return

    code = " ".join(getattr(context, "args", []) or []).strip()
    if not code:
        await message.reply_text("Use /vincular seguido do código de uso único exibido na PWA.")
        return
    base_url = _public_base_url()
    if not base_url:
        await message.reply_text("A associação da PWA ainda não está configurada neste ambiente.")
        return

    try:
        async with httpx.AsyncClient(timeout=8) as client:
            response = await client.post(
                f"{base_url}/api/v1/public/identidades/telegram/associar",
                headers={"Idempotency-Key": str(uuid.uuid4())},
                json={"codigo": code, "telegram_id": str(user.id)},
            )
            payload = response.json()
    except (httpx.HTTPError, ValueError):
        await message.reply_text("Não foi possível alcançar o serviço da PWA. Tente novamente mais tarde.")
        return

    if 200 <= response.status_code < 300:
        await message.reply_text("Telegram associado ao seu perfil da PWA. O código não pode ser reutilizado.")
    else:
        await message.reply_text(f"Associação não concluída: {_api_error(payload)}.")
