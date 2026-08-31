from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from .config import PwaConfigurationError, PwaSettings


class AuthenticationError(RuntimeError):
    """Token não pôde ser validado pelo Supabase Auth."""


@dataclass(frozen=True)
class AuthUser:
    id: str
    email: str


class Authenticator(Protocol):
    async def authenticate(self, access_token: str) -> AuthUser:
        ...


class SupabaseAuthenticator:
    def __init__(self, settings: PwaSettings) -> None:
        self.settings = settings

    async def authenticate(self, access_token: str) -> AuthUser:
        if not self.settings.supabase_url:
            raise PwaConfigurationError("SUPABASE_URL não configurada")
        api_key = self.settings.supabase_anon_key or self.settings.supabase_service_role_key
        if not api_key:
            raise PwaConfigurationError("chave do Supabase não configurada")

        url = self.settings.supabase_url.rstrip("/") + "/auth/v1/user"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(
                    url,
                    headers={
                        "apikey": api_key,
                        "Authorization": f"Bearer {access_token}",
                    },
                )
        except httpx.HTTPError as exc:
            raise AuthenticationError("não foi possível consultar o Supabase Auth") from exc

        if response.status_code != 200:
            raise AuthenticationError("sessão inválida ou expirada")
        try:
            data: dict[str, Any] = response.json()
            user_id = str(data["id"])
            email = str(data.get("email") or "").strip().casefold()
        except (ValueError, KeyError, TypeError) as exc:
            raise AuthenticationError("resposta de autenticação inválida") from exc
        if not user_id or not email:
            raise AuthenticationError("usuário autenticado sem e-mail válido")
        return AuthUser(id=user_id, email=email)
