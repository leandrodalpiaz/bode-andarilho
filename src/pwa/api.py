from __future__ import annotations

import asyncio
import hmac
import inspect
import json
import logging
import mimetypes
import os
import re
import shutil
import tempfile
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

import httpx
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from src.application.services import (
    ApplicationAuthorizationError,
    ApplicationConflictError,
    CommandContext,
    EventCommandService,
    PresenceCommandService,
    validate_publication_transition,
)
from src.application.publication import build_event_caption
from src.adapters.cards import to_legacy_card_payload
from src.domain.authorization import Actor
from src.domain.validation import (
    DomainValidationError,
    normalize_email,
    optional_text,
    normalize_store_payload,
    positive_int,
    required_text,
)

from .auth import AuthenticationError, AuthUser, Authenticator, SupabaseAuthenticator
from .config import PwaConfigurationError, PwaSettings
from .repository import RepositoryConflict, RepositoryError, SupabaseRepository
from .security import (
    FixedWindowRateLimiter,
    SecurityInputError,
    bearer_token,
    generate_opaque_token,
    hash_secret,
    idempotency_key,
    request_client_ip,
)
from .observability import PwaMetrics


logger = logging.getLogger(__name__)


class ApiError(Exception):
    def __init__(self, status_code: int, message: str, *, code: str = "request_error") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.code = code


def _slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    ascii_value = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_value).strip("-")
    return slug[:120]


class PwaAPI:
    """Handlers v1 compartilhados pela PWA e por futuros adaptadores de canal."""

    def __init__(
        self,
        settings: PwaSettings | None = None,
        *,
        repository: Any | None = None,
        authenticator: Authenticator | None = None,
        metrics: PwaMetrics | None = None,
    ) -> None:
        self.settings = settings or PwaSettings.from_env()
        self._repository = repository
        self._authenticator = authenticator
        self._metrics = metrics or PwaMetrics()
        self._public_limiter = FixedWindowRateLimiter(
            self.settings.public_rate_limit, self.settings.public_rate_window_seconds
        )

    @property
    def repository(self) -> Any:
        if self._repository is None:
            self._repository = SupabaseRepository(self.settings)
        return self._repository

    @property
    def authenticator(self) -> Authenticator:
        if self._authenticator is None:
            self._authenticator = SupabaseAuthenticator(self.settings)
        return self._authenticator

    def routes(self) -> list[Route]:
        return [
            Route("/api/v1/config", self._wrap(self.config), methods=["GET"]),
            Route("/api/v1/metrics", self._wrap(self.metrics), methods=["GET"]),
            Route("/api/v1/me", self._wrap(self.me), methods=["GET"]),
            Route("/api/v1/bootstrap/admin", self._wrap(self.bootstrap_admin), methods=["POST"]),
            Route("/api/v1/convites", self._wrap(self.create_invite), methods=["POST"]),
            Route("/api/v1/convites/consumir", self._wrap(self.consume_invite), methods=["POST"]),
            Route("/api/v1/identidades/{provider}/codigo", self._wrap(self.create_association_code), methods=["POST"]),
            Route("/api/v1/lojas", self._wrap(self.list_stores), methods=["GET"]),
            Route("/api/v1/lojas", self._wrap(self.create_store), methods=["POST"]),
            Route("/api/v1/lojas/{store_id:int}", self._wrap(self.get_store), methods=["GET"]),
            Route("/api/v1/lojas/{store_id:int}", self._wrap(self.update_store), methods=["PATCH"]),
            Route("/api/v1/lojas/{store_id:int}", self._wrap(self.archive_store), methods=["DELETE"]),
            Route("/api/v1/eventos", self._wrap(self.list_events), methods=["GET"]),
            Route("/api/v1/eventos", self._wrap(self.create_event), methods=["POST"]),
            Route("/api/v1/eventos/{event_id:int}", self._wrap(self.get_event), methods=["GET"]),
            Route("/api/v1/eventos/{event_id:int}", self._wrap(self.update_event), methods=["PATCH"]),
            Route("/api/v1/eventos/{event_id:int}/link-publico", self._wrap(self.rotate_public_link), methods=["POST"]),
            Route("/api/v1/eventos/{event_id:int}", self._wrap(self.cancel_event), methods=["DELETE"]),
            Route("/api/v1/eventos/{event_id:int}/card", self._wrap(self.generate_card), methods=["POST"]),
            Route("/api/v1/publicacoes/{publication_id:int}/estado", self._wrap(self.update_publication_state), methods=["POST"]),
            Route("/api/v1/eventos/{event_id:int}/presencas", self._wrap(self.list_presence), methods=["GET"]),
            Route("/api/v1/presencas/{presence_id:int}/aprovar", self._wrap(self.approve_presence), methods=["POST"]),
            Route("/api/v1/presencas/{presence_id:int}/recusar", self._wrap(self.reject_presence), methods=["POST"]),
            Route("/api/v1/public/eventos/{token}", self._wrap(self.public_event), methods=["GET"]),
            Route("/api/v1/public/eventos/{token}/presencas", self._wrap(self.create_public_presence), methods=["POST"]),
            Route("/api/v1/public/presencas/{receipt}", self._wrap(self.public_receipt), methods=["GET"]),
            Route("/api/v1/public/identidades/{provider}/associar", self._wrap(self.consume_external_identity), methods=["POST"]),
        ]

    def _wrap(self, handler: Callable[[Request], Awaitable[Response]]) -> Callable[[Request], Awaitable[Response]]:
        async def endpoint(request: Request) -> Response:
            request_id = self._request_id(request)
            request.state.request_id = request_id
            try:
                response = await handler(request)
            except ApiError as exc:
                response = self._error(exc.status_code, exc.message, exc.code)
            except AuthenticationError as exc:
                response = self._error(401, str(exc), "unauthorized")
            except SecurityInputError as exc:
                response = self._error(400, str(exc), "invalid_header")
            except DomainValidationError as exc:
                response = self._error(422, str(exc), "validation_error")
            except ApplicationAuthorizationError as exc:
                response = self._error(403, str(exc), "forbidden")
            except ApplicationConflictError as exc:
                response = self._error(409, str(exc), "conflict")
            except RepositoryConflict as exc:
                response = self._error(409, str(exc), "conflict")
            except PwaConfigurationError as exc:
                logger.error("Configuração da PWA ausente: %s", exc)
                response = self._error(503, "PWA não configurada neste ambiente", "not_configured")
            except RepositoryError:
                logger.exception("Falha de persistência request_id=%s", request_id)
                response = self._error(503, "serviço de dados indisponível", "repository_unavailable")
            except Exception:
                logger.exception("Erro não tratado na API PWA request_id=%s", request_id)
                response = self._error(500, "erro interno", "internal_error")
            response.headers["X-Request-ID"] = request_id
            response.headers.setdefault("Cache-Control", "no-store")
            operation = getattr(handler, "__name__", "unknown")
            self._metrics.increment(
                "api_requests_total",
                operation=operation,
                status=response.status_code,
            )
            if response.status_code >= 500:
                self._metrics.increment("api_failures_total", operation=operation)
            return response

        endpoint.__name__ = getattr(handler, "__name__", "pwa_endpoint")
        return endpoint

    @staticmethod
    def _request_id(request: Request) -> str:
        raw = request.headers.get("X-Request-ID", "").strip()
        try:
            return str(uuid.UUID(raw)) if raw else str(uuid.uuid4())
        except ValueError:
            return str(uuid.uuid4())

    @staticmethod
    def _error(status_code: int, message: str, code: str) -> JSONResponse:
        return JSONResponse({"error": {"code": code, "message": message}}, status_code=status_code)

    @staticmethod
    def _invite_validity_days(value: Any) -> int:
        try:
            days = int(value or 7)
        except (TypeError, ValueError) as exc:
            raise DomainValidationError("validade_dias deve ser um número inteiro") from exc
        return min(30, max(1, days))

    @staticmethod
    async def _json(request: Request) -> dict[str, Any]:
        try:
            payload = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ApiError(400, "corpo JSON inválido", code="invalid_json") from exc
        if not isinstance(payload, dict):
            raise ApiError(400, "o corpo deve ser um objeto JSON", code="invalid_json")
        return payload

    async def _run(self, method_name: str, *args: Any) -> Any:
        method = getattr(self.repository, method_name)
        result = await asyncio.to_thread(method, *args)
        if inspect.isawaitable(result):
            return await result
        return result

    async def _auth_user(self, request: Request) -> AuthUser:
        try:
            token = bearer_token(request)
        except SecurityInputError as exc:
            self._metrics.increment("auth_failures_total")
            raise ApiError(401, str(exc), code="unauthorized") from exc
        try:
            user = await self.authenticator.authenticate(token)
        except AuthenticationError:
            self._metrics.increment("auth_failures_total")
            raise
        except PwaConfigurationError:
            raise
        except Exception as exc:
            self._metrics.increment("auth_failures_total")
            raise AuthenticationError("falha ao validar a sessão") from exc
        self._metrics.increment("auth_success_total")
        return user

    async def _actor(self, request: Request) -> tuple[AuthUser, Actor]:
        user = await self._auth_user(request)
        actor = await self._run("get_actor", user)
        if not actor:
            raise ApiError(403, "conta autenticada ainda não possui convite ativo", code="invite_required")
        return user, actor

    @staticmethod
    def _require_role(actor: Actor, store_id: int, *, events: bool = False, store: bool = False) -> None:
        if events:
            allowed = actor.can_manage_events(store_id)
        elif store:
            allowed = actor.can_manage_store(store_id)
        else:
            allowed = actor.can_read_store(store_id)
        if not allowed:
            raise ApiError(403, "sem vínculo autorizado para esta loja", code="forbidden")

    async def _audit(
        self,
        request: Request,
        actor: Actor | None,
        action: str,
        entity_type: str,
        entity_id: Any,
        origin: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        values = {
            "ator_perfil_id": actor.profile_id if actor else None,
            "acao": action,
            "entidade_tipo": entity_type,
            "entidade_id": str(entity_id) if entity_id is not None else None,
            "origem": origin,
            "request_id": getattr(request.state, "request_id", None),
            "metadata": metadata or {},
        }
        try:
            await self._run("insert_audit", values)
        except Exception:
            # A falha fica explícita nos logs e será alerta operacional; não se
            # finge que a mutação foi auditada.
            logger.exception("Auditoria indisponível request_id=%s", values["request_id"])

    def _idempotency_metadata(self, key: str) -> dict[str, str]:
        """Retorna somente a representação não reversível da chave do comando."""

        return {"idempotency_key_hash": hash_secret(key, self.settings.token_pepper)}

    async def me(self, request: Request) -> Response:
        user, actor = await self._actor(request)
        profile = {
            "id": actor.profile_id,
            "auth_user_id": actor.auth_user_id,
            "email": user.email,
        }
        stores = await self._run("list_stores", actor)
        return JSONResponse(
            {
                "profile": profile,
                "is_global_admin": actor.is_global_admin,
                "store_roles": {
                    str(store_id): sorted(roles)
                    for store_id, roles in actor.roles_by_store.items()
                },
                "stores": stores,
            }
        )

    async def config(self, request: Request) -> Response:
        """Entrega somente configuração pública necessária para o navegador."""

        return JSONResponse(
            {
                "supabase_url": self.settings.supabase_url,
                "supabase_publishable_key": self.settings.supabase_anon_key,
                "public_base_url": self.settings.public_base_url,
                "captcha_required": self.settings.captcha_required,
                "captcha_site_key": self.settings.captcha_site_key,
            }
        )

    async def metrics(self, request: Request) -> Response:
        """Expõe contadores sem dados de negócio somente ao administrador global."""

        _, actor = await self._actor(request)
        if not actor.is_global_admin:
            raise ApiError(
                403,
                "somente administrador global pode consultar métricas",
                code="forbidden",
            )
        return JSONResponse(self._metrics.snapshot())

    async def create_invite(self, request: Request) -> Response:
        _, actor = await self._actor(request)
        key = idempotency_key(request)
        payload = await self._json(request)
        email = normalize_email(payload.get("email") or payload.get("email_autorizado"))
        papel = optional_text(payload.get("papel"), "papel", max_length=20).lower() or "member"
        if papel not in {"member", "secretary", "admin"}:
            raise DomainValidationError("papel de convite inválido")
        store_id: int | None = None
        if payload.get("loja_id") is not None:
            store_id = positive_int(payload["loja_id"], "loja_id")
        if papel != "admin" and store_id is None:
            raise DomainValidationError("loja_id é obrigatório para este papel")
        if store_id is not None:
            store = await self._run("get_store", store_id)
            if not store:
                raise ApiError(404, "loja não encontrada", code="not_found")
            if str(store.get("status") or "active") == "archived":
                raise ApiError(409, "não é possível convidar usuários para uma loja arquivada", code="store_archived")
        if not actor.can_invite(store_id):
            raise ApiError(403, "somente administrador autorizado pode criar convites", code="forbidden")
        token = generate_opaque_token()
        valid_until = datetime.now(timezone.utc) + timedelta(
            days=self._invite_validity_days(payload.get("validade_dias"))
        )
        row = await self._run(
            "create_invite",
            {
                "token_hash": hash_secret(token, self.settings.token_pepper),
                "email_autorizado": email,
                "papel": papel,
                "loja_id": store_id,
                "valid_until": valid_until.isoformat(),
                "created_by_profile_id": actor.profile_id,
            },
        )
        await self._audit(
            request,
            actor,
            "invite_created",
            "convites_conta",
            row.get("id"),
            "pwa",
            {"papel": papel, "loja_id": store_id, **self._idempotency_metadata(key)},
        )
        self._metrics.increment("invites_created_total")
        base = self.settings.public_base_url.rstrip("/")
        invite_url = f"{base}/convite?token={token}" if base else f"/convite?token={token}"
        return JSONResponse({"id": row.get("id"), "email": email, "papel": papel, "loja_id": store_id, "valid_until": valid_until.isoformat(), "invite_url": invite_url})

    async def consume_invite(self, request: Request) -> Response:
        # O usuário já precisa ter uma sessão OTP válida; a criação do perfil e
        # do vínculo é feita pela função transacional do schema privado.
        idempotency_key(request)
        payload = await self._json(request)
        token = required_text(payload.get("token"), "token", max_length=512)
        user = await self._auth_user(request)
        result = await self._run(
            "consume_invite",
            hash_secret(token, self.settings.token_pepper),
            user.id,
            user.email,
            getattr(request.state, "request_id", None),
        )
        self._metrics.increment("invites_consumed_total")
        return JSONResponse(result)

    async def create_association_code(self, request: Request) -> Response:
        _, actor = await self._actor(request)
        key = idempotency_key(request)
        provider = required_text(request.path_params.get("provider"), "provedor", max_length=30).lower()
        if provider != "telegram":
            raise DomainValidationError("provedor de associação inválido")
        token = generate_opaque_token()
        valid_until = datetime.now(timezone.utc) + timedelta(minutes=15)
        row = await self._run(
            "create_association_code",
            {
                "perfil_id": actor.profile_id,
                "provedor": provider,
                "codigo_hash": hash_secret(token, self.settings.token_pepper),
                "idempotency_key_hash": hash_secret(key, self.settings.token_pepper),
                "valid_until": valid_until.isoformat(),
            },
        )
        await self._audit(
            request,
            actor,
            "external_identity_code_created",
            "codigos_associacao",
            row.get("id"),
            "pwa",
            {"provedor": provider, "valid_until": valid_until.isoformat()},
        )
        self._metrics.increment("association_codes_created_total", provider=provider)
        return JSONResponse(
            {"provedor": provider, "codigo": token, "valid_until": valid_until.isoformat()},
            status_code=201,
        )

    async def bootstrap_admin(self, request: Request) -> Response:
        configured = self.settings.bootstrap_token
        presented = request.headers.get("X-Bootstrap-Token", "")
        if not configured or not presented or not hmac.compare_digest(presented, configured):
            raise ApiError(403, "token de bootstrap inválido", code="forbidden")
        idempotency_key(request)
        payload = await self._json(request)
        user = await self._auth_user(request)
        name = optional_text(payload.get("nome"), "nome", max_length=160)
        result = await self._run(
            "bootstrap_admin",
            user.id,
            user.email,
            name,
            getattr(request.state, "request_id", None),
        )
        self._metrics.increment("admins_bootstrapped_total")
        return JSONResponse(result, status_code=201)

    async def list_stores(self, request: Request) -> Response:
        _, actor = await self._actor(request)
        return JSONResponse({"items": await self._run("list_stores", actor)})

    async def get_store(self, request: Request) -> Response:
        _, actor = await self._actor(request)
        store_id = positive_int(request.path_params["store_id"], "loja_id")
        self._require_role(actor, store_id)
        store = await self._run("get_store", store_id)
        if not store:
            raise ApiError(404, "loja não encontrada", code="not_found")
        return JSONResponse(store)

    async def create_store(self, request: Request) -> Response:
        _, actor = await self._actor(request)
        if not actor.is_global_admin:
            raise ApiError(403, "somente administrador global pode criar lojas", code="forbidden")
        key = idempotency_key(request)
        payload = await self._json(request)
        name = required_text(payload.get("nome"), "nome", max_length=180)
        values = normalize_store_payload({**payload, "nome": name}, partial=False)
        if not values.get("slug"):
            values["slug"] = _slugify(name)
        values["created_by"] = actor.profile_id
        row = await self._run("create_store", values)
        await self._audit(
            request,
            actor,
            "store_created",
            "lojas",
            row.get("id"),
            "pwa",
            self._idempotency_metadata(key),
        )
        self._metrics.increment("stores_created_total")
        return JSONResponse(row, status_code=201)

    async def update_store(self, request: Request) -> Response:
        _, actor = await self._actor(request)
        key = idempotency_key(request)
        store_id = positive_int(request.path_params["store_id"], "loja_id")
        self._require_role(actor, store_id, store=True)
        if not await self._run("get_store", store_id):
            raise ApiError(404, "loja não encontrada", code="not_found")
        payload = await self._json(request)
        values = normalize_store_payload(payload, partial=True)
        if not values:
            raise DomainValidationError("nenhum campo para atualizar")
        row = await self._run("update_store", store_id, values)
        await self._audit(
            request,
            actor,
            "store_updated",
            "lojas",
            store_id,
            "pwa",
            self._idempotency_metadata(key),
        )
        self._metrics.increment("stores_updated_total")
        return JSONResponse(row)

    async def archive_store(self, request: Request) -> Response:
        _, actor = await self._actor(request)
        key = idempotency_key(request)
        store_id = positive_int(request.path_params["store_id"], "loja_id")
        self._require_role(actor, store_id, store=True)
        if not await self._run("get_store", store_id):
            raise ApiError(404, "loja não encontrada", code="not_found")
        row = await self._run("archive_store", store_id)
        await self._audit(
            request,
            actor,
            "store_archived",
            "lojas",
            store_id,
            "pwa",
            self._idempotency_metadata(key),
        )
        self._metrics.increment("stores_archived_total")
        return JSONResponse(row)

    async def list_events(self, request: Request) -> Response:
        _, actor = await self._actor(request)
        rows = await self._run("list_events", actor)
        return JSONResponse({"items": [self._redact_event(row) for row in rows]})

    async def get_event(self, request: Request) -> Response:
        _, actor = await self._actor(request)
        event_id = positive_int(request.path_params["event_id"], "evento_id")
        event = await self._run("get_event", event_id)
        if not event:
            raise ApiError(404, "evento não encontrado", code="not_found")
        self._require_role(actor, int(event["loja_id"]))
        return JSONResponse(self._redact_event(event))

    async def create_event(self, request: Request) -> Response:
        _, actor = await self._actor(request)
        key = idempotency_key(request)
        payload = await self._json(request)
        context = CommandContext(actor=actor, request_id=getattr(request.state, "request_id", None), origin="pwa")
        public_token = generate_opaque_token()
        data = EventCommandService.create(
            payload,
            context,
            public_token_hash=hash_secret(public_token, self.settings.token_pepper),
            idempotency_key_hash=hash_secret(key, self.settings.token_pepper),
        )
        store_id = int(data["loja_id"])
        row = await self._run("create_event", data)
        await self._audit(
            request,
            actor,
            "event_created",
            "eventos",
            row.get("id"),
            "pwa",
            {"loja_id": store_id, **self._idempotency_metadata(key)},
        )
        self._metrics.increment("events_created_total")
        response = self._redact_event(dict(row))
        response["public_url"] = self._public_event_url(public_token)
        return JSONResponse(response, status_code=201)

    async def update_event(self, request: Request) -> Response:
        _, actor = await self._actor(request)
        key = idempotency_key(request)
        event_id = positive_int(request.path_params["event_id"], "evento_id")
        current = await self._run("get_event", event_id)
        if not current:
            raise ApiError(404, "evento não encontrado", code="not_found")
        store_id = int(current["loja_id"])
        self._require_role(actor, store_id, events=True)
        payload = await self._json(request)
        context = CommandContext(actor=actor, request_id=getattr(request.state, "request_id", None), origin="pwa")
        values = EventCommandService.update(current, payload, context)
        row = await self._run("update_event", event_id, values)
        await self._audit(
            request,
            actor,
            "event_updated",
            "eventos",
            event_id,
            "pwa",
            self._idempotency_metadata(key),
        )
        self._metrics.increment("events_updated_total")
        return JSONResponse(self._redact_event(row))

    async def rotate_public_link(self, request: Request) -> Response:
        _, actor = await self._actor(request)
        key = idempotency_key(request)
        event_id = positive_int(request.path_params["event_id"], "evento_id")
        current = await self._run("get_event", event_id)
        if not current:
            raise ApiError(404, "evento não encontrado", code="not_found")
        context = CommandContext(actor=actor, request_id=getattr(request.state, "request_id", None), origin="pwa")
        public_token = generate_opaque_token()
        values = EventCommandService.rotate_public_token(
            current,
            context,
            public_token_hash=hash_secret(public_token, self.settings.token_pepper),
        )
        row = await self._run("update_event", event_id, values)
        await self._audit(
            request,
            actor,
            "event_public_link_rotated",
            "eventos",
            event_id,
            "pwa",
            self._idempotency_metadata(key),
        )
        self._metrics.increment("public_links_rotated_total")
        response = self._redact_event(dict(row))
        response["public_url"] = self._public_event_url(public_token)
        response["public_link_rotated"] = True
        return JSONResponse(response)

    async def cancel_event(self, request: Request) -> Response:
        _, actor = await self._actor(request)
        key = idempotency_key(request)
        event_id = positive_int(request.path_params["event_id"], "evento_id")
        current = await self._run("get_event", event_id)
        if not current:
            raise ApiError(404, "evento não encontrado", code="not_found")
        self._require_role(actor, int(current["loja_id"]), events=True)
        context = CommandContext(actor=actor, request_id=getattr(request.state, "request_id", None), origin="pwa")
        values = EventCommandService.cancel(current, context)
        row = await self._run("update_event", event_id, values)
        await self._audit(
            request,
            actor,
            "event_cancelled",
            "eventos",
            event_id,
            "pwa",
            self._idempotency_metadata(key),
        )
        self._metrics.increment("events_cancelled_total")
        return JSONResponse(self._redact_event(row))

    async def generate_card(self, request: Request) -> Response:
        _, actor = await self._actor(request)
        key = idempotency_key(request)
        event_id = positive_int(request.path_params["event_id"], "evento_id")
        event = await self._run("get_event", event_id)
        if not event:
            raise ApiError(404, "evento não encontrado", code="not_found")
        store_id = int(event["loja_id"])
        self._require_role(actor, store_id, events=True)
        store = await self._run("get_store", store_id)
        if not store:
            raise ApiError(404, "loja do evento não encontrada", code="not_found")
        payload = await self._json(request)
        channel = optional_text(payload.get("canal"), "canal", max_length=20).lower() or "instagram"
        if channel not in {"instagram", "whatsapp", "telegram"}:
            raise DomainValidationError("canal de publicação inválido")

        from src.render_cards import render_event_card

        output_dir = Path(tempfile.mkdtemp(prefix="bode-pwa-card-"))
        try:
            legacy_event, legacy_store = to_legacy_card_payload(event, store)
            rendered = await asyncio.to_thread(
                render_event_card, legacy_event, legacy_store, str(output_dir)
            )
            path = Path(rendered.path)
            content = await asyncio.to_thread(path.read_bytes)
            content_type = mimetypes.guess_type(path.name)[0] or "image/png"
            artifact_path = f"eventos/{event_id}/cards/{uuid.uuid4().hex}{path.suffix.lower()}"
            uploaded = await self._run("upload_artifact", "pwa-private", artifact_path, content, content_type)
            publication = await self._run(
                "insert_publication",
                {
                    "evento_id": event_id,
                    "artefato_path": artifact_path,
                    "canal": channel,
                    "estado": "prepared",
                    "idempotency_key_hash": hash_secret(key, self.settings.token_pepper),
                    "criado_por_id": actor.profile_id,
                },
            )
            await self._audit(
                request,
                actor,
                "event_card_prepared",
                "publicacoes_canal",
                publication.get("id"),
                "pwa",
                {"evento_id": event_id, "canal": channel, **self._idempotency_metadata(key)},
            )
            self._metrics.increment("cards_prepared_total", channel=channel)
            return JSONResponse(
                {
                    "publication": self._redact_publication(publication),
                    "artifact": uploaded,
                    "caption": build_event_caption(event, store),
                    "warnings": rendered.warnings,
                }
            )
        finally:
            shutil.rmtree(output_dir, ignore_errors=True)

    async def update_publication_state(self, request: Request) -> Response:
        _, actor = await self._actor(request)
        key = idempotency_key(request)
        publication_id = positive_int(request.path_params["publication_id"], "publicação_id")
        publication = await self._run("get_publication", publication_id)
        if not publication:
            raise ApiError(404, "publicação não encontrada", code="not_found")
        event = await self._run("get_event", int(publication["evento_id"]))
        if not event:
            raise ApiError(404, "evento não encontrado", code="not_found")
        self._require_role(actor, int(event["loja_id"]), events=True)
        payload = await self._json(request)
        target = optional_text(payload.get("estado"), "estado", max_length=30).lower()
        current = str(publication.get("estado") or "prepared")
        validate_publication_transition(current, target)
        values = {"estado": target}
        if "erro" in payload:
            values["erro"] = optional_text(payload.get("erro"), "erro", max_length=1000)
        row = await self._run("update_publication", publication_id, values)
        await self._audit(
            request,
            actor,
            f"publication_{target}",
            "publicacoes_canal",
            publication_id,
            "pwa",
            self._idempotency_metadata(key),
        )
        self._metrics.increment("publication_states_total", state=target)
        return JSONResponse(self._redact_publication(row))

    async def list_presence(self, request: Request) -> Response:
        _, actor = await self._actor(request)
        event_id = positive_int(request.path_params["event_id"], "evento_id")
        event = await self._run("get_event", event_id)
        if not event:
            raise ApiError(404, "evento não encontrado", code="not_found")
        self._require_role(actor, int(event["loja_id"]), events=True)
        rows = await self._run("list_presence", event_id)
        return JSONResponse({"items": [self._redact_presence(row) for row in rows]})

    async def _review_presence(self, request: Request, target_status: str) -> Response:
        _, actor = await self._actor(request)
        key = idempotency_key(request)
        presence_id = positive_int(request.path_params["presence_id"], "presença_id")
        presence = await self._run("get_presence", presence_id)
        if not presence:
            raise ApiError(404, "solicitação não encontrada", code="not_found")
        event = await self._run("get_event", int(presence["evento_id"]))
        if not event:
            raise ApiError(404, "evento não encontrado", code="not_found")
        self._require_role(actor, int(event["loja_id"]), events=True)
        context = CommandContext(actor=actor, request_id=getattr(request.state, "request_id", None), origin="pwa")
        values = PresenceCommandService.review(presence, event, context, target_status)
        values["revisado_at"] = datetime.now(timezone.utc).isoformat()
        row = await self._run("update_presence", presence_id, values)
        await self._audit(
            request,
            actor,
            f"presence_{target_status}",
            "solicitacoes_presenca",
            presence_id,
            "pwa",
            self._idempotency_metadata(key),
        )
        self._metrics.increment("presence_reviews_total", state=target_status)
        return JSONResponse(self._redact_presence(row))

    async def approve_presence(self, request: Request) -> Response:
        return await self._review_presence(request, "approved")

    async def reject_presence(self, request: Request) -> Response:
        return await self._review_presence(request, "rejected")

    def _public_event_url(self, token: str) -> str:
        base = self.settings.public_base_url.rstrip("/")
        return f"{base}/evento/{token}" if base else f"/evento/{token}"

    @staticmethod
    def _public_event_payload(event: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "evento_at": event.get("evento_at"),
            "titulo": event.get("titulo"),
            "descricao": event.get("descricao"),
            "grau": event.get("grau"),
            "tipo_sessao": event.get("tipo_sessao"),
            "rito": event.get("rito"),
            "traje_obrigatorio": event.get("traje_obrigatorio"),
            "agape": event.get("agape"),
            "ordem_do_dia": event.get("ordem_do_dia"),
            "endereco_sessao": event.get("endereco_sessao"),
            "status": event.get("status"),
            "visibilidade": event.get("visibilidade"),
        }
        store = event.get("loja")
        if isinstance(store, dict):
            payload["loja"] = {
                key: store.get(key)
                for key in ("nome", "numero_loja", "cidade", "uf", "rito", "instagram_handle")
                if store.get(key) is not None
            }
        return payload

    @staticmethod
    def _redact_event(event: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in event.items() if key not in {"public_token_hash", "idempotency_key_hash"}}

    @staticmethod
    def _redact_presence(presence: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in presence.items() if key not in {"recibo_hash", "idempotency_key_hash"}}

    @staticmethod
    def _redact_publication(publication: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in publication.items() if key != "idempotency_key_hash"}

    async def public_event(self, request: Request) -> Response:
        token = required_text(request.path_params.get("token"), "token", max_length=512)
        event = await self._run("get_public_event", hash_secret(token, self.settings.token_pepper))
        if not event:
            raise ApiError(404, "evento público não encontrado", code="not_found")
        return JSONResponse(self._public_event_payload(event))

    async def _verify_captcha(self, payload: dict[str, Any], request: Request) -> None:
        if not self.settings.captcha_required:
            return
        captcha_token = required_text(payload.get("captcha_token"), "captcha_token", max_length=2048)
        secret = os.getenv("PWA_CAPTCHA_SECRET", "").strip()
        if not secret:
            raise ApiError(503, "CAPTCHA obrigatório ainda não configurado", code="not_configured")
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                response = await client.post(
                    self.settings.captcha_verify_url,
                    data={"secret": secret, "response": captcha_token, "remoteip": request_client_ip(request)},
                )
            result = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ApiError(503, "verificação CAPTCHA indisponível", code="captcha_unavailable") from exc
        if response.status_code != 200 or not result.get("success"):
            raise ApiError(422, "CAPTCHA inválido", code="captcha_invalid")

    async def create_public_presence(self, request: Request) -> Response:
        token = required_text(request.path_params.get("token"), "token", max_length=512)
        payload = await self._json(request)
        if payload.get("website") or payload.get("homepage"):
            raise ApiError(422, "solicitação rejeitada", code="spam_rejected")
        await self._verify_captcha(payload, request)
        event = await self._run("get_public_event", hash_secret(token, self.settings.token_pepper))
        if not event:
            raise ApiError(404, "evento público não encontrado", code="not_found")
        event_id = int(event["id"])
        key = idempotency_key(request)
        limiter_key = f"{request_client_ip(request)}:{event_id}"
        if not self._public_limiter.allow(limiter_key):
            raise ApiError(429, "muitas tentativas; tente novamente mais tarde", code="rate_limited")
        receipt = generate_opaque_token()
        normalized = PresenceCommandService.public_request(
            payload,
            event_id=event_id,
            receipt_hash=hash_secret(receipt, self.settings.token_pepper),
            idempotency_key_hash=hash_secret(key, self.settings.token_pepper),
        )
        row = await self._run(
            "create_presence",
            normalized,
        )
        await self._audit(request, None, "public_presence_requested", "solicitacoes_presenca", row.get("id"), "public", {"evento_id": event_id})
        self._metrics.increment("public_presence_requests_total")
        return JSONResponse({"status": row.get("status", "pending"), "receipt": receipt}, status_code=201)

    async def public_receipt(self, request: Request) -> Response:
        receipt = required_text(request.path_params.get("receipt"), "recibo", max_length=512)
        row = await self._run("get_public_receipt", hash_secret(receipt, self.settings.token_pepper))
        if not row:
            raise ApiError(404, "recibo não encontrado", code="not_found")
        return JSONResponse(
            {
                key: row.get(key)
                for key in ("visitante_nome", "status", "created_at")
                if row.get(key) is not None
            }
        )

    async def consume_external_identity(self, request: Request) -> Response:
        provider = required_text(request.path_params.get("provider"), "provedor", max_length=30).lower()
        if provider != "telegram":
            raise DomainValidationError("provedor de associação inválido")
        payload = await self._json(request)
        if payload.get("website") or payload.get("homepage"):
            raise ApiError(422, "solicitação rejeitada", code="spam_rejected")
        token = required_text(payload.get("codigo") or payload.get("code"), "código", max_length=512)
        external_user_id = required_text(
            payload.get("telegram_id") or payload.get("external_user_id"),
            "telegram_id",
            max_length=30,
        )
        if not re.fullmatch(r"\d{1,30}", external_user_id):
            raise DomainValidationError("telegram_id inválido")
        key = idempotency_key(request)
        limiter_key = f"identity:{request_client_ip(request)}:{provider}"
        if not self._public_limiter.allow(limiter_key):
            raise ApiError(429, "muitas tentativas; tente novamente mais tarde", code="rate_limited")
        result = await self._run(
            "consume_external_identity",
            hash_secret(token, self.settings.token_pepper),
            provider,
            external_user_id,
            getattr(request.state, "request_id", None),
        )
        return JSONResponse(result)


def build_pwa_routes(
    settings: PwaSettings | None = None,
    *,
    repository: Any | None = None,
    authenticator: Authenticator | None = None,
) -> list[Route]:
    return PwaAPI(settings, repository=repository, authenticator=authenticator).routes()
