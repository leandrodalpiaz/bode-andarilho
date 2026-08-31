from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.domain.authorization import Actor

from .auth import AuthUser
from .config import PwaConfigurationError, PwaSettings


SCHEMA = "pwa_v2"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class RepositoryError(RuntimeError):
    """Falha de persistência ou integração com o Supabase."""


class RepositoryConflict(RepositoryError):
    """Violação de idempotência/constraint que deve virar HTTP 409."""


def _response_data(response: Any) -> list[dict[str, Any]]:
    error = getattr(response, "error", None)
    if error:
        raise RepositoryError(str(error))
    data = getattr(response, "data", None)
    if data is None:
        return []
    if isinstance(data, list):
        return data
    return [data]


class SupabaseRepository:
    """Repository v2; nenhuma operação deste objeto acessa tabelas legadas."""

    def __init__(self, settings: PwaSettings) -> None:
        settings.require_service_configuration()
        try:
            from supabase import create_client
        except ImportError as exc:  # pragma: no cover - coberto no ambiente CI
            raise PwaConfigurationError("dependência supabase não instalada") from exc
        self._client = create_client(settings.supabase_url, settings.supabase_service_role_key)
        self._schema = self._client.schema(SCHEMA)
        self._settings = settings

    def _table(self, table: str) -> Any:
        return self._schema.table(table)

    def _one(self, query: Any) -> dict[str, Any] | None:
        rows = _response_data(query.execute())
        return rows[0] if rows else None

    def _many(self, query: Any) -> list[dict[str, Any]]:
        return _response_data(query.execute())

    def _insert_one(self, table: str, values: dict[str, Any]) -> dict[str, Any]:
        try:
            row = self._one(self._table(table).insert(values).select("*"))
        except Exception as exc:
            if "duplicate" in str(exc).lower() or "unique" in str(exc).lower():
                raise RepositoryConflict(str(exc)) from exc
            raise RepositoryError(str(exc)) from exc
        if not row:
            raise RepositoryError(f"insert não retornou {table}")
        return row

    def get_actor(self, user: AuthUser) -> Actor | None:
        profile = self._one(
            self._table("perfis").select("*").eq("auth_user_id", user.id).limit(1)
        )
        if not profile or profile.get("status") != "active":
            return None
        links = self._many(
            self._table("vinculos_loja")
            .select("perfil_id,loja_id,papel,status")
            .eq("perfil_id", profile["id"])
            .eq("status", "active")
        )
        roles: dict[int, set[str]] = {}
        global_admin = False
        for link in links:
            if link.get("loja_id") is None and link.get("papel") == "admin":
                global_admin = True
                continue
            if link.get("loja_id") is not None:
                roles.setdefault(int(link["loja_id"]), set()).add(str(link.get("papel")))
        return Actor(
            profile_id=str(profile["id"]),
            auth_user_id=user.id,
            email=user.email,
            is_global_admin=global_admin,
            roles_by_store={store_id: frozenset(values) for store_id, values in roles.items()},
        )

    def list_stores(self, actor: Actor) -> list[dict[str, Any]]:
        query = self._table("lojas").select("*").order("nome")
        if actor.is_global_admin:
            return self._many(query)
        store_ids = list(actor.roles_by_store)
        if not store_ids:
            return []
        return self._many(query.in_("id", store_ids))

    def get_store(self, store_id: int) -> dict[str, Any] | None:
        return self._one(self._table("lojas").select("*").eq("id", int(store_id)).limit(1))

    def create_store(self, values: dict[str, Any]) -> dict[str, Any]:
        return self._insert_one("lojas", values)

    def update_store(self, store_id: int, values: dict[str, Any]) -> dict[str, Any]:
        try:
            row = self._one(
                self._table("lojas")
                .update({**values, "updated_at": _utc_now()})
                .eq("id", int(store_id))
                .select("*")
            )
        except Exception as exc:
            raise RepositoryError(str(exc)) from exc
        if not row:
            raise RepositoryError("loja não encontrada")
        return row

    def archive_store(self, store_id: int) -> dict[str, Any]:
        return self.update_store(store_id, {"status": "archived"})

    def create_invite(self, values: dict[str, Any]) -> dict[str, Any]:
        return self._insert_one("convites_conta", values)

    def consume_invite(self, token_hash: str, auth_user_id: str, email: str, request_id: str | None = None) -> dict[str, Any]:
        try:
            response = self._schema.rpc(
                "consume_invite",
                {
                    "invite_token_hash": token_hash,
                    "target_auth_user_id": auth_user_id,
                    "authenticated_email": email,
                    "request_uuid": request_id,
                },
            ).execute()
            data = _response_data(response)
        except Exception as exc:
            message = str(exc)
            if "Convite" in message or "convite" in message:
                raise RepositoryConflict(message) from exc
            raise RepositoryError(message) from exc
        return data[0] if data else {}

    def bootstrap_admin(self, auth_user_id: str, email: str, name: str, request_id: str | None = None) -> dict[str, Any]:
        try:
            response = self._schema.rpc(
                "bootstrap_admin",
                {
                    "target_auth_user_id": auth_user_id,
                    "authenticated_email": email,
                    "display_name": name,
                    "request_uuid": request_id,
                },
            ).execute()
            data = _response_data(response)
        except Exception as exc:
            message = str(exc)
            if "administrador" in message.lower() or "admin" in message.lower():
                raise RepositoryConflict(message) from exc
            raise RepositoryError(message) from exc
        return data[0] if data else {}

    def list_events(self, actor: Actor) -> list[dict[str, Any]]:
        query = self._table("eventos").select("*").order("evento_at")
        if actor.is_global_admin:
            return self._many(query)
        store_ids = list(actor.roles_by_store)
        if not store_ids:
            return []
        return self._many(query.in_("loja_id", store_ids))

    def get_event(self, event_id: int) -> dict[str, Any] | None:
        return self._one(self._table("eventos").select("*").eq("id", int(event_id)).limit(1))

    def create_event(self, values: dict[str, Any]) -> dict[str, Any]:
        return self._insert_one("eventos", values)

    def update_event(self, event_id: int, values: dict[str, Any]) -> dict[str, Any]:
        try:
            row = self._one(
                self._table("eventos")
                .update({**values, "updated_at": _utc_now()})
                .eq("id", int(event_id))
                .select("*")
            )
        except Exception as exc:
            raise RepositoryError(str(exc)) from exc
        if not row:
            raise RepositoryError("evento não encontrado")
        return row

    def cancel_event(self, event_id: int) -> dict[str, Any]:
        return self.update_event(event_id, {"status": "cancelled"})

    def list_presence(self, event_id: int) -> list[dict[str, Any]]:
        return self._many(
            self._table("solicitacoes_presenca")
            .select("*")
            .eq("evento_id", int(event_id))
            .order("created_at")
        )

    def get_presence(self, presence_id: int) -> dict[str, Any] | None:
        return self._one(
            self._table("solicitacoes_presenca")
            .select("*")
            .eq("id", int(presence_id))
            .limit(1)
        )

    def create_presence(self, values: dict[str, Any]) -> dict[str, Any]:
        return self._insert_one("solicitacoes_presenca", values)

    def update_presence(self, presence_id: int, values: dict[str, Any]) -> dict[str, Any]:
        try:
            row = self._one(
                self._table("solicitacoes_presenca")
                .update({**values, "updated_at": _utc_now()})
                .eq("id", int(presence_id))
                .select("*")
            )
        except Exception as exc:
            raise RepositoryError(str(exc)) from exc
        if not row:
            raise RepositoryError("solicitação não encontrada")
        return row

    def get_public_event(self, token_hash: str) -> dict[str, Any] | None:
        return self._one(
            self._table("eventos")
            .select("*")
            .eq("public_token_hash", token_hash)
            .eq("status", "published")
            .eq("visibilidade", "public")
            .limit(1)
        )

    def get_public_receipt(self, receipt_hash: str) -> dict[str, Any] | None:
        return self._one(
            self._table("solicitacoes_presenca")
            .select("id,evento_id,visitante_nome,status,created_at")
            .eq("recibo_hash", receipt_hash)
            .limit(1)
        )

    def get_publication(self, publication_id: int) -> dict[str, Any] | None:
        return self._one(
            self._table("publicacoes_canal")
            .select("*")
            .eq("id", int(publication_id))
            .limit(1)
        )

    def update_publication(self, publication_id: int, values: dict[str, Any]) -> dict[str, Any]:
        try:
            row = self._one(
                self._table("publicacoes_canal")
                .update(values)
                .eq("id", int(publication_id))
                .select("*")
            )
        except Exception as exc:
            raise RepositoryError(str(exc)) from exc
        if not row:
            raise RepositoryError("publicação não encontrada")
        return row

    def insert_publication(self, values: dict[str, Any]) -> dict[str, Any]:
        return self._insert_one("publicacoes_canal", values)

    def insert_audit(self, values: dict[str, Any]) -> dict[str, Any]:
        return self._insert_one("auditoria", values)

    def upload_artifact(
        self, bucket: str, path: str, content: bytes, content_type: str = "image/png"
    ) -> dict[str, str]:
        try:
            self._client.storage.from_(bucket).upload(
                path,
                content,
                file_options={"content-type": content_type, "upsert": "true"},
            )
            signed = self._client.storage.from_(bucket).create_signed_url(path, 3600)
        except Exception as exc:
            raise RepositoryError(str(exc)) from exc
        signed_url = ""
        if isinstance(signed, dict):
            signed_url = str(signed.get("signedURL") or signed.get("signedUrl") or "")
        return {"path": path, "url": signed_url}
