from __future__ import annotations

import os
from dataclasses import dataclass
from typing import FrozenSet


def _flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _positive_int_set(name: str) -> FrozenSet[int]:
    """Lê uma lista de IDs de loja sem transformar configuração inválida em permissão."""

    raw = os.getenv(name, "")
    values: set[int] = set()
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            value = int(item)
        except ValueError:
            continue
        if value > 0:
            values.add(value)
    return frozenset(values)


@dataclass(frozen=True)
class FeatureFlags:
    pwa_enabled: bool = True
    telegram_enabled: bool = True
    telegram_mutations_to_pwa: bool = False
    telegram_mutations_to_pwa_store_ids: FrozenSet[int] = frozenset()
    telegram_notifications_enabled: bool = True

    @classmethod
    def from_env(cls) -> "FeatureFlags":
        return cls(
            pwa_enabled=_flag("PWA_ENABLED", True),
            telegram_enabled=_flag("TELEGRAM_ENABLED", True),
            telegram_mutations_to_pwa=_flag("TELEGRAM_MUTATIONS_TO_PWA", False),
            telegram_mutations_to_pwa_store_ids=_positive_int_set("TELEGRAM_MUTATIONS_TO_PWA_STORES"),
            telegram_notifications_enabled=_flag("TELEGRAM_NOTIFICATIONS_ENABLED", True),
        )
