from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from src.domain.validation import DomainValidationError


_WEEKDAYS_PT_BR = (
    "segunda-feira",
    "terça-feira",
    "quarta-feira",
    "quinta-feira",
    "sexta-feira",
    "sábado",
    "domingo",
)


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _clip(value: Any, limit: int) -> str:
    text = _text(value)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _local_zone(name: str) -> timezone | ZoneInfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        return timezone(timedelta(hours=-3))


def _format_event_datetime(value: Any, timezone_name: str) -> str:
    raw = _text(value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise DomainValidationError("data do evento inválida para a legenda") from exc
    if parsed.tzinfo is None:
        raise DomainValidationError("data do evento deve informar o fuso horário")
    local = parsed.astimezone(_local_zone(timezone_name))
    return f"{local:%d/%m/%Y} ({_WEEKDAYS_PT_BR[local.weekday()]}) às {local:%H:%M}"


def build_event_caption(
    event: Mapping[str, Any],
    store: Mapping[str, Any],
    *,
    public_url: str = "",
    timezone_name: str = "America/Sao_Paulo",
) -> str:
    """Monta uma legenda pública sem depender do Telegram ou do renderer."""

    title = _clip(event.get("titulo"), 160) or "Sessão"
    store_name = _clip(store.get("nome"), 180) or "Loja"
    store_number = _text(store.get("numero_loja"))
    if store_number and store_number != "0":
        store_name = f"{store_name} nº {store_number}"

    lines = [
        f"{title}",
        f"📅 {_format_event_datetime(event.get('evento_at'), timezone_name)}",
        f"🏛️ {store_name}",
    ]
    location = " / ".join(
        item for item in (_text(store.get("cidade")), _text(store.get("uf")).upper()) if item
    )
    if location:
        lines.append(f"📍 {location}")

    for label, value in (
        ("Grau", event.get("grau")),
        ("Tipo de sessão", event.get("tipo_sessao")),
        ("Rito", event.get("rito") or store.get("rito")),
        ("Traje", event.get("traje_obrigatorio")),
        ("Ágape", event.get("agape")),
    ):
        text = _clip(value, 180)
        if text:
            lines.append(f"{label}: {text}")

    description = _clip(event.get("ordem_do_dia") or event.get("descricao"), 650)
    if description:
        lines.extend(("", "Ordem do dia / observações:", description))

    address = _clip(event.get("endereco_sessao") or store.get("endereco"), 300)
    if address:
        lines.extend(("", f"Local: {address}"))

    link = _text(public_url)
    if link:
        lines.extend(("", f"Solicite sua presença: {link}"))

    return "\n".join(lines)
