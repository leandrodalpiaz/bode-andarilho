from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from src.domain.validation import DomainValidationError


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


@dataclass(frozen=True)
class LegacyTelegramAdapter:
    """Traduz o formato legado apenas na borda do canal Telegram.

    A identidade Telegram não vira autorização automaticamente e os registros
    legados não são relacionados aos IDs v2 por nome ou número de loja.
    """

    timezone_name: str = "America/Sao_Paulo"

    def external_identity(self, telegram_id: int) -> dict[str, str]:
        try:
            normalized = int(telegram_id)
        except (TypeError, ValueError) as exc:
            raise DomainValidationError("telegram_id inválido") from exc
        if normalized <= 0:
            raise DomainValidationError("telegram_id inválido")
        return {"provedor": "telegram", "external_user_id": str(normalized)}

    def event_payload(self, legacy: Mapping[str, Any]) -> dict[str, Any]:
        raw_date = _text(legacy.get("Data do evento") or legacy.get("data_evento"))
        raw_time = _text(legacy.get("Hora") or legacy.get("hora"))
        if not raw_date or not raw_time:
            raise DomainValidationError("evento legado sem data ou horário")
        parsed_date = None
        for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
            try:
                parsed_date = datetime.strptime(raw_date[:10], fmt).date()
                break
            except ValueError:
                continue
        if parsed_date is None:
            raise DomainValidationError("data do evento legado inválida")
        parsed_time = None
        for fmt in ("%H:%M", "%H:%M:%S"):
            try:
                parsed_time = datetime.strptime(raw_time[:8], fmt).time()
                break
            except ValueError:
                continue
        if parsed_time is None:
            raise DomainValidationError("horário do evento legado inválido")
        try:
            local_zone = ZoneInfo(self.timezone_name)
        except ZoneInfoNotFoundError:
            # O runtime de produção instala tzdata; este fallback mantém o
            # piloto local determinístico para o fuso histórico do projeto.
            local_zone = timezone(timedelta(hours=-3))
        local = datetime.combine(parsed_date, parsed_time, tzinfo=local_zone)
        return {
            "titulo": _text(legacy.get("Título") or legacy.get("Nome da loja") or "Sessão"),
            "descricao": _text(legacy.get("Observações") or legacy.get("Ordem do dia")),
            "evento_at": local.isoformat(),
            "loja_id": int(legacy.get("ID da loja") or legacy.get("loja_id")),
        }

    def presence_payload(self, legacy: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "nome": _text(legacy.get("Nome") or legacy.get("nome")),
            "agape": _text(legacy.get("Ágape") or legacy.get("agape") or "sem").lower(),
        }
