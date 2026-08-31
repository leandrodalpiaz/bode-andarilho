from __future__ import annotations

from typing import Final


EVENT_STATUSES: Final = frozenset({"draft", "published", "cancelled", "closed"})
PRESENCE_STATUSES: Final = frozenset({"pending", "approved", "rejected", "cancelled"})
PUBLICATION_STATES: Final = frozenset(
    {"prepared", "share_initiated", "confirmed_by_user", "api_published", "failed"}
)

_PUBLICATION_TRANSITIONS = {
    "prepared": frozenset({"prepared", "share_initiated", "failed"}),
    "share_initiated": frozenset({"share_initiated", "confirmed_by_user", "failed"}),
    "confirmed_by_user": frozenset({"confirmed_by_user", "api_published", "failed"}),
    "api_published": frozenset({"api_published"}),
    "failed": frozenset({"failed", "prepared"}),
}


_EVENT_TRANSITIONS = {
    "draft": frozenset({"draft", "published", "cancelled"}),
    "published": frozenset({"published", "cancelled", "closed"}),
    "cancelled": frozenset({"cancelled"}),
    "closed": frozenset({"closed"}),
}


def can_transition_event(current: str, target: str) -> bool:
    """Retorna se uma alteração de estado do evento é operacionalmente válida."""

    return target in _EVENT_TRANSITIONS.get(str(current).strip().lower(), frozenset())


def can_transition_publication(current: str, target: str) -> bool:
    return target in _PUBLICATION_TRANSITIONS.get(str(current).strip().lower(), frozenset())


def is_public_event(status: str, visibility: str) -> bool:
    return str(status).lower() == "published" and str(visibility).lower() == "public"
