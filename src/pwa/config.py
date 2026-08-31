from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


class PwaConfigurationError(RuntimeError):
    """Configuração obrigatória ausente no backend."""


def _env(name: str, default: str = "") -> str:
    value = os.getenv(name, default).strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1].strip()
    return value


@dataclass(frozen=True)
class PwaSettings:
    supabase_url: str
    supabase_anon_key: str
    supabase_service_role_key: str
    token_pepper: str
    public_base_url: str
    frontend_dist: Path
    bootstrap_token: str = ""
    public_rate_limit: int = 8
    public_rate_window_seconds: int = 300
    captcha_required: bool = False
    captcha_site_key: str = ""
    captcha_verify_url: str = "https://hcaptcha.com/siteverify"

    @classmethod
    def from_env(cls) -> "PwaSettings":
        default_dist = Path(__file__).resolve().parents[2] / "web" / "dist"
        return cls(
            supabase_url=_env("SUPABASE_URL"),
            supabase_anon_key=_env("SUPABASE_ANON_KEY") or _env("SUPABASE_PUBLISHABLE_KEY"),
            supabase_service_role_key=_env("SUPABASE_SERVICE_ROLE_KEY"),
            token_pepper=_env("PWA_TOKEN_PEPPER"),
            bootstrap_token=_env("PWA_BOOTSTRAP_TOKEN"),
            public_base_url=_env("PWA_PUBLIC_BASE_URL") or _env("RENDER_EXTERNAL_URL"),
            frontend_dist=Path(_env("PWA_FRONTEND_DIST") or str(default_dist)).resolve(),
            public_rate_limit=max(1, int(_env("PWA_PUBLIC_RATE_LIMIT", "8") or "8")),
            public_rate_window_seconds=max(
                30, int(_env("PWA_PUBLIC_RATE_WINDOW_SECONDS", "300") or "300")
            ),
            captcha_required=_env("PWA_PUBLIC_CAPTCHA_REQUIRED", "false").lower()
            in {"1", "true", "yes", "on"},
            captcha_site_key=_env("PWA_CAPTCHA_SITE_KEY"),
            captcha_verify_url=_env("PWA_CAPTCHA_VERIFY_URL", "https://hcaptcha.com/siteverify"),
        )

    def require_service_configuration(self) -> None:
        missing = [
            name
            for name, value in (
                ("SUPABASE_URL", self.supabase_url),
                ("SUPABASE_SERVICE_ROLE_KEY", self.supabase_service_role_key),
                ("PWA_TOKEN_PEPPER", self.token_pepper),
            )
            if not value
        ]
        if missing:
            raise PwaConfigurationError(
                "Configuração da PWA ausente: " + ", ".join(missing)
            )
