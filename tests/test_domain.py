import pytest

from src.domain.authorization import Actor
from src.domain.states import can_transition_event, can_transition_publication, is_public_event
from src.domain.validation import DomainValidationError, normalize_event_payload, normalize_presence_payload


def test_secretario_so_pode_operar_loja_vinculada():
    actor = Actor(
        profile_id="profile-1",
        auth_user_id="auth-1",
        email="sec@example.com",
        roles_by_store={7: frozenset({"secretary"})},
    )
    assert actor.can_manage_events(7)
    assert not actor.can_manage_events(8)
    assert not actor.can_manage_store(7)


def test_admin_global_pode_operar_qualquer_loja():
    actor = Actor(
        profile_id="profile-1",
        auth_user_id="auth-1",
        email="admin@example.com",
        is_global_admin=True,
    )
    assert actor.can_manage_events(7)
    assert actor.can_manage_store(7)
    assert actor.can_invite(None)


def test_estado_publicado_nao_volta_para_rascunho():
    assert can_transition_event("draft", "published")
    assert not can_transition_event("published", "draft")
    assert is_public_event("published", "public")
    assert not is_public_event("draft", "public")


def test_publicacao_distingue_compartilhamento_de_publicacao_comprovada():
    assert can_transition_publication("prepared", "share_initiated")
    assert can_transition_publication("share_initiated", "confirmed_by_user")
    assert not can_transition_publication("share_initiated", "api_published")


def test_evento_exige_data_iso_e_loja():
    payload = normalize_event_payload(
        {"titulo": "Sessão aberta", "evento_at": "2026-09-10T20:00:00-03:00", "loja_id": 1}
    )
    assert payload["loja_id"] == 1
    assert payload["evento_at"].startswith("2026-09-10T23:00:00")
    with pytest.raises(DomainValidationError):
        normalize_event_payload({"titulo": "Sem data", "loja_id": 1})


def test_presenca_publica_nao_aceita_nome_vazio():
    result = normalize_presence_payload({"nome": "Visitante", "email": "VISITANTE@EXAMPLE.COM"})
    assert result["visitante_nome"] == "Visitante"
    assert result["visitante_email"] == "visitante@example.com"
    with pytest.raises(DomainValidationError):
        normalize_presence_payload({"nome": ""})
