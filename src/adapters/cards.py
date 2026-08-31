from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any
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


def _local_zone(name: str) -> timezone | ZoneInfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        return timezone(timedelta(hours=-3))


def _event_datetime(value: Any, timezone_name: str) -> tuple[str, str, str]:
    raw = str(value or "").strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise DomainValidationError("data do evento inválida para o card") from exc
    if parsed.tzinfo is None:
        raise DomainValidationError("data do evento deve informar o fuso horário")
    local = parsed.astimezone(_local_zone(timezone_name))
    return local.strftime("%d/%m/%Y"), local.strftime("%H:%M"), _WEEKDAYS_PT_BR[local.weekday()]


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _formatted_store_name(store: dict[str, Any]) -> str:
    name = _text(store.get("nome") or store.get("Nome da Loja")) or "Loja"
    number = _text(store.get("numero_loja") or store.get("Número"))
    if number and number != "0":
        return f"{name} nº {number}"
    return name


def to_legacy_card_payload(
    event: dict[str, Any],
    store: dict[str, Any],
    *,
    timezone_name: str = "America/Sao_Paulo",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Adapta somente o formato do renderer; não consulta tabelas legadas."""

    date, hour, weekday = _event_datetime(event.get("evento_at"), timezone_name)
    layout = store.get("layout_config")
    if not isinstance(layout, dict):
        layout = {}
    legacy_event = {
        "ID Evento": event.get("id"),
        "ID da loja": store.get("id"),
        "Nome da loja": store.get("nome"),
        "Nome formatado da loja": _formatted_store_name(store),
        "Número da loja": store.get("numero_loja"),
        "Data do evento": date,
        "Dia da semana": weekday,
        "Hora": hour,
        "Grau": event.get("grau") or "",
        "Tipo de sessão": event.get("tipo_sessao") or event.get("titulo") or "Sessão",
        "Rito": event.get("rito") or store.get("rito") or "",
        "Potência": store.get("potencia") or "",
        "Potência complemento": store.get("potencia_complemento") or "",
        "Traje obrigatório": event.get("traje_obrigatorio") or "",
        "Ágape": event.get("agape") or "",
        "Observações": event.get("ordem_do_dia") or event.get("descricao") or "",
        "Oriente": store.get("cidade") or "",
        "Endereço da sessão": event.get("endereco_sessao") or store.get("endereco") or "",
    }
    legacy_store = {
        "ID": store.get("id"),
        "Nome da Loja": store.get("nome"),
        "Número": store.get("numero_loja"),
        "Template sessão URL": store.get("template_card_path") or "",
        "Cor texto padrão": layout.get("cor_texto_padrao", ""),
        "Layout config JSON": json.dumps(layout, ensure_ascii=False),
    }
    return legacy_event, legacy_store
