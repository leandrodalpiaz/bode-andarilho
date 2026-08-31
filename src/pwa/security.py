from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import time
from collections import defaultdict
from threading import Lock
from typing import Optional

from starlette.requests import Request


class SecurityInputError(ValueError):
    """Cabeçalho ou token fora do contrato da API."""


_IDEMPOTENCY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")


def generate_opaque_token() -> str:
    return secrets.token_urlsafe(32)


def hash_secret(value: str, pepper: str) -> str:
    if not value or not pepper:
        raise SecurityInputError("segredo de hash não configurado")
    return hmac.new(
        pepper.encode("utf-8"), value.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def bearer_token(request: Request) -> str:
    raw = request.headers.get("Authorization", "").strip()
    scheme, separator, token = raw.partition(" ")
    if not separator or scheme.casefold() != "bearer" or not token.strip():
        raise SecurityInputError("Bearer token ausente ou inválido")
    return token.strip()


def idempotency_key(request: Request) -> str:
    value = request.headers.get("Idempotency-Key", "").strip()
    if not _IDEMPOTENCY_RE.fullmatch(value):
        raise SecurityInputError(
            "Idempotency-Key obrigatório; use entre 8 e 128 caracteres seguros"
        )
    return value


def request_client_ip(request: Request) -> str:
    # X-Forwarded-For só deve ser confiado após o proxy oficial ser explicitamente
    # configurado. O MVP usa o peer observado pelo servidor.
    return request.client.host if request.client else "unknown"


class FixedWindowRateLimiter:
    """Rate limit conservador por processo para o endpoint público.

    A implementação é suficiente para o piloto de uma instância; antes de
    escalar horizontalmente, o contador deve ser movido para Redis/Upstash.
    """

    def __init__(self, limit: int, window_seconds: int) -> None:
        self.limit = max(1, int(limit))
        self.window_seconds = max(1, int(window_seconds))
        self._hits: dict[str, list[float]] = defaultdict(list)
        self._lock = Lock()

    def allow(self, key: str, *, now: Optional[float] = None) -> bool:
        current = time.time() if now is None else float(now)
        cutoff = current - self.window_seconds
        with self._lock:
            hits = [stamp for stamp in self._hits[key] if stamp > cutoff]
            if len(hits) >= self.limit:
                self._hits[key] = hits
                return False
            hits.append(current)
            self._hits[key] = hits
            return True
