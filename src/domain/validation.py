from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from .states import EVENT_STATUSES, PRESENCE_STATUSES


class DomainValidationError(ValueError):
    """Erro de entrada que pode ser apresentado como HTTP 422."""


_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def normalize_email(value: Any) -> str:
    email = str(value or "").strip().casefold()
    if not email or not _EMAIL_RE.fullmatch(email):
        raise DomainValidationError("e-mail inválido")
    return email


def required_text(value: Any, field_name: str, *, max_length: int = 240) -> str:
    text = str(value or "").strip()
    if not text:
        raise DomainValidationError(f"{field_name} é obrigatório")
    if len(text) > max_length:
        raise DomainValidationError(f"{field_name} excede o limite de {max_length} caracteres")
    return text


def optional_text(value: Any, field_name: str, *, max_length: int = 240) -> str:
    text = str(value or "").strip()
    if len(text) > max_length:
        raise DomainValidationError(f"{field_name} excede o limite de {max_length} caracteres")
    return text


def positive_int(value: Any, field_name: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise DomainValidationError(f"{field_name} deve ser um número inteiro") from exc
    if number <= 0:
        raise DomainValidationError(f"{field_name} deve ser positivo")
    return number


def _slug(value: Any, field_name: str) -> str:
    slug = optional_text(value, field_name, max_length=120).lower()
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug):
        raise DomainValidationError(f"{field_name} inválido")
    return slug


def normalize_store_payload(payload: dict[str, Any], *, partial: bool = False) -> dict[str, Any]:
    """Normaliza campos da loja antes de qualquer adapter ou persistência."""

    result: dict[str, Any] = {}
    if not partial or "nome" in payload:
        result["nome"] = required_text(payload.get("nome"), "nome", max_length=180)
    if "slug" in payload:
        result["slug"] = _slug(payload.get("slug"), "slug")

    for field_name, label, max_length in (
        ("numero_loja", "número da loja", 40),
        ("descricao", "descrição", 4000),
        ("cidade", "cidade", 120),
        ("endereco", "endereço", 400),
        ("rito", "rito", 80),
        ("potencia", "potência", 80),
        ("potencia_complemento", "complemento da potência", 120),
        ("instagram_handle", "Instagram", 120),
        ("logo_path", "caminho da logo", 500),
        ("template_card_path", "caminho do template", 500),
    ):
        if field_name in payload:
            result[field_name] = optional_text(payload.get(field_name), label, max_length=max_length)

    if "uf" in payload:
        uf = optional_text(payload.get("uf"), "UF", max_length=3).upper()
        if uf and len(uf) not in {2, 3}:
            raise DomainValidationError("UF deve ter 2 ou 3 caracteres")
        result["uf"] = uf

    if "layout_config" in payload:
        layout = payload.get("layout_config")
        if not isinstance(layout, dict):
            raise DomainValidationError("layout_config deve ser um objeto")
        result["layout_config"] = layout

    if "status" in payload:
        status = optional_text(payload.get("status"), "status", max_length=20).lower()
        if status not in {"draft", "active", "archived"}:
            raise DomainValidationError("status de loja inválido")
        result["status"] = status

    return result


def normalize_event_payload(payload: dict[str, Any], *, partial: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if not partial or "titulo" in payload:
        result["titulo"] = required_text(payload.get("titulo"), "título", max_length=160)
    if not partial or "evento_at" in payload:
        raw_date = required_text(payload.get("evento_at"), "data do evento", max_length=64)
        try:
            parsed = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
        except ValueError as exc:
            raise DomainValidationError("data do evento deve estar em formato ISO 8601") from exc
        if parsed.tzinfo is None:
            raise DomainValidationError("data do evento deve informar o fuso horário")
        result["evento_at"] = parsed.astimezone(timezone.utc).isoformat()
    if not partial or "loja_id" in payload:
        result["loja_id"] = positive_int(payload.get("loja_id"), "loja_id")
    if "descricao" in payload:
        result["descricao"] = optional_text(payload.get("descricao"), "descrição", max_length=4000)
    for field_name, label, max_length in (
        ("grau", "grau", 100),
        ("tipo_sessao", "tipo de sessão", 200),
        ("rito", "rito", 120),
        ("traje_obrigatorio", "traje obrigatório", 200),
        ("agape", "ágape", 100),
        ("ordem_do_dia", "ordem do dia", 4000),
        ("endereco_sessao", "endereço da sessão", 400),
    ):
        if field_name in payload:
            result[field_name] = optional_text(payload.get(field_name), label, max_length=max_length)
    if "visibilidade" in payload:
        visibility = optional_text(payload.get("visibilidade"), "visibilidade", max_length=20).lower()
        if visibility not in {"public", "private"}:
            raise DomainValidationError("visibilidade deve ser public ou private")
        result["visibilidade"] = visibility
    if "status" in payload:
        status = optional_text(payload.get("status"), "status", max_length=20).lower()
        if status not in EVENT_STATUSES:
            raise DomainValidationError("status de evento inválido")
        result["status"] = status
    return result


def normalize_presence_payload(payload: dict[str, Any]) -> dict[str, Any]:
    name = required_text(payload.get("visitante_nome") or payload.get("nome"), "nome", max_length=160)
    result = {"visitante_nome": name}
    if payload.get("email"):
        result["visitante_email"] = normalize_email(payload["email"])
    if payload.get("telefone"):
        result["visitante_telefone"] = optional_text(payload["telefone"], "telefone", max_length=40)
    result["agape"] = optional_text(payload.get("agape"), "ágape", max_length=40).lower() or "sem"
    if result["agape"] not in {"sem", "com", "gratuito", "pago"}:
        raise DomainValidationError("opção de ágape inválida")
    if payload.get("status"):
        status = optional_text(payload["status"], "status", max_length=20).lower()
        if status not in PRESENCE_STATUSES:
            raise DomainValidationError("status de presença inválido")
        result["status"] = status
    return result
