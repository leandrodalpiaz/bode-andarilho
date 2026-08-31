from __future__ import annotations

import os
from dataclasses import dataclass


def _flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class FeatureFlags:
    pwa_enabled: bool = True
    telegram_enabled: bool = True
    telegram_mutations_to_pwa: bool = False
    telegram_notifications_enabled: bool = True

    @classmethod
    def from_env(cls) -> "FeatureFlags":
        return cls(
            pwa_enabled=_flag("PWA_ENABLED", True),
            telegram_enabled=_flag("TELEGRAM_ENABLED", True),
            telegram_mutations_to_pwa=_flag("TELEGRAM_MUTATIONS_TO_PWA", False),
            telegram_notifications_enabled=_flag("TELEGRAM_NOTIFICATIONS_ENABLED", True),
        )
