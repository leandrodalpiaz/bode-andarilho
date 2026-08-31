import pytest

from src.application.services import (
    ApplicationAuthorizationError,
    ApplicationConflictError,
    CommandContext,
    EventCommandService,
    PresenceCommandService,
)
from src.domain.authorization import Actor


def context_for(store_id: int = 1) -> CommandContext:
    return CommandContext(
        actor=Actor("profile", "auth", "sec@example.com", roles_by_store={store_id: frozenset({"secretary"})}),
        request_id="request-1",
        origin="test",
    )


def test_servico_de_evento_nao_conhece_framework_de_canal():
    data = EventCommandService.create(
        {"titulo": "Sessão", "evento_at": "2026-09-10T20:00:00-03:00", "loja_id": 1},
        context_for(),
        public_token_hash="public-hash",
        idempotency_key_hash="idempotency-hash",
    )
    assert data["criado_por_id"] == "profile"
    assert data["status"] == "draft"
    assert data["evento_at"].startswith("2026-09-10T23:00:00")


def test_servico_de_evento_bloqueia_loja_sem_vinculo():
    with pytest.raises(ApplicationAuthorizationError):
        EventCommandService.create(
            {"titulo": "Sessão", "evento_at": "2026-09-10T20:00:00-03:00", "loja_id": 9},
            context_for(),
            public_token_hash="public-hash",
            idempotency_key_hash="idempotency-hash",
        )


def test_servico_preserva_transicao_de_estado():
    with pytest.raises(ApplicationConflictError):
        EventCommandService.update(
            {"loja_id": 1, "status": "published"},
            {"status": "draft"},
            context_for(),
        )


def test_servico_de_presenca_produz_pendente_e_snapshot():
    data = PresenceCommandService.public_request(
        {"nome": "Visitante", "email": "v@example.com", "agape": "sem"},
        event_id=10,
        receipt_hash="receipt-hash",
        idempotency_key_hash="idempotency-hash",
    )
    assert data["status"] == "pending"
    assert data["evento_id"] == 10
    assert data["visitante_nome"] == "Visitante"
