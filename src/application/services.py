from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.domain.authorization import Actor
from src.domain.states import PUBLICATION_STATES, can_transition_event, can_transition_publication
from src.domain.validation import (
    DomainValidationError,
    normalize_event_payload,
    normalize_presence_payload,
    optional_text,
)


class ApplicationAuthorizationError(PermissionError):
    """O ator não possui vínculo suficiente para o caso de uso."""


class ApplicationConflictError(ValueError):
    """O comando não pode ser aplicado no estado atual."""


@dataclass(frozen=True)
class CommandContext:
    actor: Actor
    request_id: str | None
    origin: str


class EventCommandService:
    """Regras de criação/alteração de evento compartilháveis entre canais."""

    @staticmethod
    def create(
        payload: dict[str, Any],
        context: CommandContext,
        *,
        public_token_hash: str,
        idempotency_key_hash: str,
    ) -> dict[str, Any]:
        values = normalize_event_payload(payload)
        store_id = int(values["loja_id"])
        if not context.actor.can_manage_events(store_id):
            raise ApplicationAuthorizationError("sem vínculo autorizado para esta loja")
        status = str(payload.get("status") or "draft").lower()
        visibility = str(payload.get("visibilidade") or "private").lower()
        if status not in {"draft", "published", "cancelled", "closed"}:
            raise DomainValidationError("status de evento inválido")
        if visibility not in {"public", "private"}:
            raise DomainValidationError("visibilidade deve ser public ou private")
        return {
            **values,
            "status": status,
            "visibilidade": visibility,
            "criado_por_id": context.actor.profile_id,
            "secretario_id": context.actor.profile_id,
            "secretario_snapshot_nome": optional_text(payload.get("secretario_snapshot_nome"), "nome do secretário", max_length=160),
            "public_token_hash": public_token_hash,
            "idempotency_key_hash": idempotency_key_hash,
        }

    @staticmethod
    def cancel(current: dict[str, Any], context: CommandContext) -> dict[str, str]:
        store_id = int(current["loja_id"])
        if not context.actor.can_manage_events(store_id):
            raise ApplicationAuthorizationError("sem vínculo autorizado para esta loja")
        if not can_transition_event(str(current.get("status") or "draft"), "cancelled"):
            raise ApplicationConflictError("evento não pode ser cancelado neste estado")
        return {"status": "cancelled"}

    @staticmethod
    def update(current: dict[str, Any], payload: dict[str, Any], context: CommandContext) -> dict[str, Any]:
        store_id = int(current["loja_id"])
        if not context.actor.can_manage_events(store_id):
            raise ApplicationAuthorizationError("sem vínculo autorizado para esta loja")
        values = normalize_event_payload(payload, partial=True)
        if "loja_id" in values and int(values["loja_id"]) != store_id:
            raise ApplicationAuthorizationError("evento não pode ser movido de loja por esta operação")
        target_status = values.get("status")
        if target_status and not can_transition_event(str(current.get("status") or "draft"), target_status):
            raise ApplicationConflictError("transição de estado do evento não permitida")
        if not values:
            raise DomainValidationError("nenhum campo para atualizar")
        return values


class PresenceCommandService:
    @staticmethod
    def public_request(
        payload: dict[str, Any],
        *,
        event_id: int,
        receipt_hash: str,
        idempotency_key_hash: str,
    ) -> dict[str, Any]:
        normalized = normalize_presence_payload(payload)
        return {
            "evento_id": int(event_id),
            "visitante_nome": normalized["visitante_nome"],
            "visitante_email": normalized.get("visitante_email"),
            "visitante_telefone": normalized.get("visitante_telefone"),
            "agape": normalized["agape"],
            "status": "pending",
            "origem": "public",
            "idempotency_key_hash": idempotency_key_hash,
            "recibo_hash": receipt_hash,
        }

    @staticmethod
    def review(
        presence: dict[str, Any],
        event: dict[str, Any],
        context: CommandContext,
        target_status: str,
    ) -> dict[str, Any]:
        if target_status not in {"approved", "rejected"}:
            raise DomainValidationError("status de revisão inválido")
        if not context.actor.can_manage_events(int(event["loja_id"])):
            raise ApplicationAuthorizationError("sem vínculo autorizado para esta loja")
        current = str(presence.get("status") or "pending")
        if current not in {"pending", "approved", "rejected"}:
            raise ApplicationConflictError("solicitação não pode ser revisada neste estado")
        if current != "pending":
            raise ApplicationConflictError("solicitação já foi revisada")
        return {
            "status": target_status,
            "revisado_por_id": context.actor.profile_id,
        }


def validate_publication_transition(current: str, target: str) -> None:
    if target not in PUBLICATION_STATES:
        raise DomainValidationError("estado de publicação inválido")
    if target == "api_published":
        raise ApplicationAuthorizationError("publicação via API exige adaptador externo com evidência")
    if not can_transition_publication(current, target):
        raise ApplicationConflictError("transição de publicação não permitida")
