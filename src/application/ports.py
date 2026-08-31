from __future__ import annotations

from typing import Any, Protocol

from src.domain.authorization import Actor


class EventRepositoryPort(Protocol):
    """Contrato mínimo para os casos de uso de eventos.

    Telegram, API HTTP e testes podem fornecer implementações diferentes sem
    transportar objetos de framework para dentro do domínio.
    """

    def get_event(self, event_id: int) -> dict[str, Any] | None:
        ...

    def create_event(self, values: dict[str, Any]) -> dict[str, Any]:
        ...

    def update_event(self, event_id: int, values: dict[str, Any]) -> dict[str, Any]:
        ...


class PresenceRepositoryPort(Protocol):
    def get_presence(self, presence_id: int) -> dict[str, Any] | None:
        ...

    def update_presence(self, presence_id: int, values: dict[str, Any]) -> dict[str, Any]:
        ...


def can_manage_event(actor: Actor, store_id: int) -> bool:
    return actor.can_manage_events(int(store_id))
