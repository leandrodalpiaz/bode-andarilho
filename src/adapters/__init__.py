"""Adaptadores de entrada/saída de canais externos."""

from .telegram_legacy import LegacyTelegramAdapter
from .cards import to_legacy_card_payload

__all__ = ["LegacyTelegramAdapter", "to_legacy_card_payload"]
