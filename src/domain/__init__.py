"""Regras de negócio independentes dos canais Telegram e HTTP."""

from .authorization import Actor
from .states import (
    EVENT_STATUSES,
    PRESENCE_STATUSES,
    PUBLICATION_STATES,
    can_transition_event,
    can_transition_publication,
)

__all__ = [
    "Actor",
    "EVENT_STATUSES",
    "PRESENCE_STATUSES",
    "PUBLICATION_STATES",
    "can_transition_event",
    "can_transition_publication",
]
