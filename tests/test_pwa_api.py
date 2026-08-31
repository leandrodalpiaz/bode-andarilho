from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
from starlette.applications import Starlette

from src.domain.authorization import Actor
from src.pwa.auth import AuthUser
from src.pwa.api import PwaAPI
from src.pwa.config import PwaSettings


@dataclass
class FakeAuthenticator:
    async def authenticate(self, access_token: str) -> AuthUser:
        if access_token not in {"secretary", "admin"}:
            raise RuntimeError("sessão inválida")
        return AuthUser(id=access_token, email=f"{access_token}@example.com")


class FakeRepository:
    def __init__(self) -> None:
        self.audits: list[dict] = []
        self.created_events: list[dict] = []
        self.presence: list[dict] = []
        self.publication = {"id": 40, "evento_id": 10, "estado": "prepared", "canal": "instagram"}
        self.event = {
            "id": 10,
            "loja_id": 1,
            "evento_at": "2026-09-10T20:00:00-03:00",
            "titulo": "Sessão aberta",
            "descricao": "Encontro semanal",
            "status": "published",
            "visibilidade": "public",
        }

    def get_actor(self, user: AuthUser):
        if user.id == "admin":
            return Actor("p-admin", user.id, user.email, is_global_admin=True)
        return Actor("p-secretary", user.id, user.email, roles_by_store={1: frozenset({"secretary"})})

    def list_stores(self, actor):
        return [{"id": 1, "nome": "Loja Piloto"}]

    def list_events(self, actor):
        return self.created_events

    def get_store(self, store_id):
        return {"id": store_id, "nome": "Loja Piloto", "template_card_path": "", "layout_config": {}}

    def create_event(self, values):
        row = {"id": 20, **values}
        self.created_events.append(row)
        return row

    def get_event(self, event_id):
        return self.event if event_id == 10 else None

    def get_public_event(self, token_hash):
        return self.event

    def create_presence(self, values):
        row = {"id": 30, **values}
        self.presence.append(row)
        return row

    def get_public_receipt(self, receipt_hash):
        return None

    def insert_audit(self, values):
        self.audits.append(values)
        return values

    def get_publication(self, publication_id):
        return self.publication if publication_id == 40 else None

    def update_publication(self, publication_id, values):
        self.publication.update(values)
        return self.publication


def make_client(repo: FakeRepository) -> httpx.AsyncClient:
    settings = PwaSettings(
        supabase_url="https://example.supabase.co",
        supabase_anon_key="public",
        supabase_service_role_key="server",
        token_pepper="test-pepper",
        public_base_url="https://pwa.example",
        frontend_dist=Path("web/dist"),
    )
    pwa = PwaAPI(settings, repository=repo, authenticator=FakeAuthenticator())
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=Starlette(routes=pwa.routes())), base_url="http://test")


@pytest.mark.asyncio
async def test_api_rejeita_sessao_ausente():
    async with make_client(FakeRepository()) as client:
        response = await client.get("/api/v1/me")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_config_expoe_apenas_parametros_publicos():
    async with make_client(FakeRepository()) as client:
        response = await client.get("/api/v1/config")
    assert response.status_code == 200
    body = response.json()
    assert body["supabase_url"] == "https://example.supabase.co"
    assert body["supabase_publishable_key"] == "public"
    assert "supabase_service_role_key" not in body
    assert "token_pepper" not in body


@pytest.mark.asyncio
async def test_api_rejeita_mutacao_sem_idempotencia():
    async with make_client(FakeRepository()) as client:
        response = await client.post(
            "/api/v1/eventos",
            headers={"Authorization": "Bearer secretary"},
            json={"titulo": "Sessão", "evento_at": "2026-09-10T20:00:00-03:00", "loja_id": 1},
        )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_secretario_cria_evento_somente_na_loja_vinculada():
    repo = FakeRepository()
    async with make_client(repo) as client:
        response = await client.post(
            "/api/v1/eventos",
            headers={"Authorization": "Bearer secretary", "Idempotency-Key": "event-001"},
            json={"titulo": "Sessão", "evento_at": "2026-09-10T20:00:00-03:00", "loja_id": 2},
        )
    assert response.status_code == 403
    assert repo.created_events == []


@pytest.mark.asyncio
async def test_evento_criado_nao_retorna_hashes_de_bearer():
    repo = FakeRepository()
    async with make_client(repo) as client:
        response = await client.post(
            "/api/v1/eventos",
            headers={"Authorization": "Bearer secretary", "Idempotency-Key": "event-002"},
            json={"titulo": "Sessão", "evento_at": "2026-09-10T20:00:00-03:00", "loja_id": 1},
        )
    assert response.status_code == 201
    assert "public_token_hash" not in response.json()
    assert "idempotency_key_hash" not in response.json()
    assert response.json()["public_url"].startswith("https://pwa.example/evento/")


@pytest.mark.asyncio
async def test_endpoint_publico_cria_presenca_pendente_e_nao_expoe_hashes():
    repo = FakeRepository()
    async with make_client(repo) as client:
        response = await client.post(
            "/api/v1/public/eventos/public-token/presencas",
            headers={"Idempotency-Key": "presence-001"},
            json={"nome": "Visitante", "email": "VISITANTE@example.com", "agape": "sem"},
        )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "pending"
    assert body["receipt"]
    assert "recibo_hash" not in body
    assert repo.audits[-1]["origem"] == "public"


@pytest.mark.asyncio
async def test_publicacao_registra_compartilhamento_sem_fingir_publicacao_externa():
    repo = FakeRepository()
    async with make_client(repo) as client:
        response = await client.post(
            "/api/v1/publicacoes/40/estado",
            headers={"Authorization": "Bearer secretary", "Idempotency-Key": "publication-001"},
            json={"estado": "share_initiated"},
        )
        forbidden = await client.post(
            "/api/v1/publicacoes/40/estado",
            headers={"Authorization": "Bearer secretary", "Idempotency-Key": "publication-002"},
            json={"estado": "api_published"},
        )
    assert response.status_code == 200
    assert response.json()["estado"] == "share_initiated"
    assert forbidden.status_code == 403
