from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
from starlette.applications import Starlette

from src.domain.authorization import Actor
from src.pwa.auth import AuthUser
from src.pwa.api import PwaAPI
from src.pwa.config import PwaSettings
from src.pwa.observability import PwaMetrics
from src.pwa.repository import RepositoryConflict
from src.pwa.security import hash_secret


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
        self.invites: list[dict] = []
        self.association_codes: list[dict] = []
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
        return {"id": store_id, "nome": "Loja Piloto", "status": "active", "template_card_path": "", "layout_config": {}}

    def create_store(self, values):
        return {"id": 2, **values}

    def archive_store(self, store_id):
        return {"id": store_id, "nome": "Loja Piloto", "status": "archived"}

    def create_invite(self, values):
        row = {"id": "invite-1", **values}
        self.invites.append(row)
        return row

    def consume_invite(self, token_hash, auth_user_id, email, request_id=None):
        return {"perfil_id": "p-secretary", "auth_user_id": auth_user_id, "email": email, "papel": "secretary", "loja_id": 1}

    def bootstrap_admin(self, auth_user_id, email, name, request_id=None):
        return {"perfil_id": "p-admin", "auth_user_id": auth_user_id, "email": email, "nome": name, "is_global_admin": True}

    def create_event(self, values):
        row = {"id": 20, **values}
        self.created_events.append(row)
        return row

    def get_event(self, event_id):
        return self.event if event_id == 10 else None

    def update_event(self, event_id, values):
        if event_id != 10:
            return None
        self.event.update(values)
        return self.event

    def get_public_event(self, token_hash):
        return self.event

    def create_presence(self, values):
        row = {"id": 30, **values}
        self.presence.append(row)
        return row

    def get_public_receipt(self, receipt_hash):
        return {
            "id": 30,
            "evento_id": 10,
            "visitante_nome": "Visitante",
            "status": "pending",
            "created_at": "2026-09-10T20:00:00+00:00",
        } if receipt_hash else None

    def insert_audit(self, values):
        self.audits.append(values)
        return values

    def get_publication(self, publication_id):
        return self.publication if publication_id == 40 else None

    def update_publication(self, publication_id, values):
        self.publication.update(values)
        return self.publication

    def update_store(self, store_id, values):
        return {"id": store_id, "nome": values.get("nome", "Loja Piloto"), **values}

    def get_presence(self, presence_id):
        return next((row for row in self.presence if row.get("id") == presence_id), {
            "id": presence_id,
            "evento_id": 10,
            "visitante_nome": "Visitante",
            "status": "pending",
            "agape": "sem",
        })

    def list_presence(self, event_id):
        return [row for row in self.presence if row.get("evento_id") == event_id]

    def update_presence(self, presence_id, values):
        row = self.get_presence(presence_id)
        row.update(values)
        return row

    def insert_publication(self, values):
        self.publication.update({"id": 40, **values})
        return self.publication

    def upload_artifact(self, bucket, path, content, content_type):
        return {"bucket": bucket, "path": path, "url": f"https://storage.example/{path}"}

    def create_association_code(self, values):
        row = {"id": "code-1", **values}
        self.association_codes.append(row)
        return row

    def consume_external_identity(self, code_hash, provider, external_user_id, request_id=None):
        return {"perfil_id": "p-secretary", "provedor": provider, "external_user_id": external_user_id}


def make_client(
    repo: FakeRepository,
    settings: PwaSettings | None = None,
    metrics: PwaMetrics | None = None,
) -> httpx.AsyncClient:
    settings = settings or PwaSettings(
        supabase_url="https://example.supabase.co",
        supabase_anon_key="public",
        supabase_service_role_key="server",
        token_pepper="test-pepper",
        public_base_url="https://pwa.example",
        frontend_dist=Path("web/dist"),
    )
    pwa = PwaAPI(settings, repository=repo, authenticator=FakeAuthenticator(), metrics=metrics)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=Starlette(routes=pwa.routes())), base_url="http://test")


class ConflictRepository(FakeRepository):
    def create_event(self, values):
        raise RepositoryConflict("chave de idempotência já utilizada")


class MissingInviteStoreRepository(FakeRepository):
    def get_store(self, store_id):
        return None


class ArchivedInviteStoreRepository(FakeRepository):
    def get_store(self, store_id):
        return {"id": store_id, "nome": "Loja Arquivada", "status": "archived"}


class PublicPresenceConflictRepository(FakeRepository):
    def create_presence(self, values):
        raise RepositoryConflict("chave de idempotência já utilizada")


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
async def test_metricas_sao_restritas_ao_administrador_global():
    metrics = PwaMetrics()
    async with make_client(FakeRepository(), metrics=metrics) as client:
        await client.get("/api/v1/config")
        forbidden = await client.get(
            "/api/v1/metrics",
            headers={"Authorization": "Bearer secretary"},
        )
        response = await client.get(
            "/api/v1/metrics",
            headers={"Authorization": "Bearer admin"},
        )
    assert forbidden.status_code == 403
    assert response.status_code == 200
    counters = response.json()["counters"]
    assert any(item["name"] == "auth_success_total" for item in counters)
    assert any(
        item["name"] == "api_requests_total"
        and item["labels"].get("operation") == "config"
        and item["labels"].get("status") == "200"
        for item in counters
    )


@pytest.mark.asyncio
async def test_config_pode_expor_somente_a_chave_publica_do_captcha():
    settings = PwaSettings(
        supabase_url="https://example.supabase.co",
        supabase_anon_key="public",
        supabase_service_role_key="server",
        token_pepper="test-pepper",
        public_base_url="https://pwa.example",
        frontend_dist=Path("web/dist"),
        captcha_required=True,
        captcha_site_key="site-public-key",
    )
    async with make_client(FakeRepository(), settings) as client:
        response = await client.get("/api/v1/config")
    assert response.status_code == 200
    body = response.json()
    assert body["captcha_required"] is True
    assert body["captcha_site_key"] == "site-public-key"
    assert "captcha_secret" not in body


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
async def test_api_converte_conflito_de_idempotencia_em_409():
    async with make_client(ConflictRepository()) as client:
        response = await client.post(
            "/api/v1/eventos",
            headers={"Authorization": "Bearer secretary", "Idempotency-Key": "event-conflict"},
            json={"titulo": "Sessão", "evento_at": "2026-09-10T20:00:00-03:00", "loja_id": 1},
        )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


@pytest.mark.asyncio
async def test_convite_rejeita_loja_inexistente_antes_da_persistencia():
    async with make_client(MissingInviteStoreRepository()) as client:
        response = await client.post(
            "/api/v1/convites",
            headers={"Authorization": "Bearer admin", "Idempotency-Key": "invite-missing"},
            json={"email": "secretario@example.com", "papel": "secretary", "loja_id": 404},
        )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_convite_rejeita_loja_arquivada():
    async with make_client(ArchivedInviteStoreRepository()) as client:
        response = await client.post(
            "/api/v1/convites",
            headers={"Authorization": "Bearer admin", "Idempotency-Key": "invite-archived"},
            json={"email": "secretario@example.com", "papel": "secretary", "loja_id": 7},
        )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "store_archived"


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
    audit = repo.audits[-1]
    assert "idempotency_key" not in audit["metadata"]
    assert audit["metadata"]["idempotency_key_hash"] == hash_secret("event-002", "test-pepper")


@pytest.mark.asyncio
async def test_evento_pode_rotacionar_link_publico_sem_expor_hash():
    repo = FakeRepository()
    async with make_client(repo) as client:
        response = await client.post(
            "/api/v1/eventos/10/link-publico",
            headers={"Authorization": "Bearer secretary", "Idempotency-Key": "link-001"},
            json={},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["public_link_rotated"] is True
    assert body["public_url"].startswith("https://pwa.example/evento/")
    assert "public_token_hash" not in body
    assert repo.audits[-1]["acao"] == "event_public_link_rotated"


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
    assert "id" not in body
    assert "recibo_hash" not in body
    assert repo.audits[-1]["origem"] == "public"


@pytest.mark.asyncio
async def test_endpoint_publico_aplica_rate_limit_por_ip_e_evento():
    settings = PwaSettings(
        supabase_url="https://example.supabase.co",
        supabase_anon_key="public",
        supabase_service_role_key="server",
        token_pepper="test-pepper",
        public_base_url="https://pwa.example",
        frontend_dist=Path("web/dist"),
        public_rate_limit=1,
        public_rate_window_seconds=300,
    )
    async with make_client(FakeRepository(), settings) as client:
        first = await client.post(
            "/api/v1/public/eventos/public-token/presencas",
            headers={"Idempotency-Key": "presence-rate-1"},
            json={"nome": "Visitante 1"},
        )
        second = await client.post(
            "/api/v1/public/eventos/public-token/presencas",
            headers={"Idempotency-Key": "presence-rate-2"},
            json={"nome": "Visitante 2"},
        )
    assert first.status_code == 201
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "rate_limited"


@pytest.mark.asyncio
async def test_api_preserva_request_id_valido_na_resposta():
    request_id = "00000000-0000-4000-8000-000000000001"
    async with make_client(FakeRepository()) as client:
        response = await client.get("/api/v1/config", headers={"X-Request-ID": request_id})
    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == request_id


@pytest.mark.asyncio
async def test_endpoint_publico_consulta_recibo_sem_expor_contato():
    async with make_client(FakeRepository()) as client:
        response = await client.get("/api/v1/public/presencas/receipt-token")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "pending"
    assert body["visitante_nome"] == "Visitante"
    assert "visitante_email" not in body
    assert "recibo_hash" not in body
    assert "id" not in body
    assert "evento_id" not in body


@pytest.mark.asyncio
async def test_evento_publico_expoe_identidade_institucional_segura():
    repo = FakeRepository()
    repo.event["loja"] = {
        "id": 1,
        "nome": "Loja Piloto",
        "numero_loja": "101",
        "cidade": "São Paulo",
        "uf": "SP",
        "endereco": "não deve ser exposto neste endpoint",
    }
    async with make_client(repo) as client:
        response = await client.get("/api/v1/public/eventos/public-token")
    assert response.status_code == 200
    assert response.json()["loja"]["nome"] == "Loja Piloto"
    assert "id" not in response.json()
    assert "loja_id" not in response.json()
    assert "id" not in response.json()["loja"]
    assert "endereco" not in response.json()["loja"]


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


@pytest.mark.asyncio
async def test_edicao_de_loja_normaliza_dados_antes_do_repository():
    repo = FakeRepository()
    async with make_client(repo) as client:
        response = await client.patch(
            "/api/v1/lojas/1",
            headers={"Authorization": "Bearer admin", "Idempotency-Key": "store-001"},
            json={"nome": "Loja Atualizada", "uf": "rj", "layout_config": {"cor": "#fff"}},
        )
    assert response.status_code == 200
    assert response.json()["nome"] == "Loja Atualizada"
    assert response.json()["uf"] == "RJ"
    assert "idempotency_key" not in repo.audits[-1]["metadata"]
    assert repo.audits[-1]["metadata"]["idempotency_key_hash"] == hash_secret("store-001", "test-pepper")


@pytest.mark.asyncio
async def test_edicao_de_loja_rejeita_campos_invalidos():
    repo = FakeRepository()
    async with make_client(repo) as client:
        response = await client.patch(
            "/api/v1/lojas/1",
            headers={"Authorization": "Bearer admin", "Idempotency-Key": "store-002"},
            json={"uf": "R"},
        )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_usuario_autenticado_gera_codigo_telegram_opaco_e_temporario():
    repo = FakeRepository()
    async with make_client(repo) as client:
        response = await client.post(
            "/api/v1/identidades/telegram/codigo",
            headers={"Authorization": "Bearer secretary", "Idempotency-Key": "identity-001"},
        )
    assert response.status_code == 201
    body = response.json()
    assert body["provedor"] == "telegram"
    assert body["codigo"]
    assert repo.association_codes[0]["codigo_hash"] != body["codigo"]


@pytest.mark.asyncio
async def test_endpoint_publico_associa_telegram_apenas_com_id_numerico():
    repo = FakeRepository()
    async with make_client(repo) as client:
        response = await client.post(
            "/api/v1/public/identidades/telegram/associar",
            headers={"Idempotency-Key": "identity-002"},
            json={"codigo": "one-time-code", "telegram_id": "123456789"},
        )
        invalid = await client.post(
            "/api/v1/public/identidades/telegram/associar",
            headers={"Idempotency-Key": "identity-003"},
            json={"codigo": "one-time-code", "telegram_id": "abc"},
        )
    assert response.status_code == 200
    assert response.json()["external_user_id"] == "123456789"
    assert invalid.status_code == 422


@pytest.mark.asyncio
async def test_admin_cria_convite_com_link_opaco_e_auditoria():
    repo = FakeRepository()
    async with make_client(repo) as client:
        response = await client.post(
            "/api/v1/convites",
            headers={"Authorization": "Bearer admin", "Idempotency-Key": "invite-ok"},
            json={"email": "SECRETARIO@example.com", "papel": "secretary", "loja_id": 1},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "secretario@example.com"
    assert body["papel"] == "secretary"
    assert body["loja_id"] == 1
    assert "token_hash" not in body
    assert "token=" in body["invite_url"]
    assert repo.audits[-1]["acao"] == "invite_created"


@pytest.mark.asyncio
async def test_convite_e_bootstrap_exigem_otp_e_preservam_contexto():
    settings = PwaSettings(
        supabase_url="https://example.supabase.co",
        supabase_anon_key="public",
        supabase_service_role_key="server",
        token_pepper="test-pepper",
        public_base_url="https://pwa.example",
        frontend_dist=Path("web/dist"),
        bootstrap_token="bootstrap-secret",
    )
    async with make_client(FakeRepository(), settings) as client:
        consumed = await client.post(
            "/api/v1/convites/consumir",
            headers={"Authorization": "Bearer secretary", "Idempotency-Key": "consume-1"},
            json={"token": "opaque-invite"},
        )
        bootstrapped = await client.post(
            "/api/v1/bootstrap/admin",
            headers={
                "Authorization": "Bearer secretary",
                "X-Bootstrap-Token": "bootstrap-secret",
                "Idempotency-Key": "bootstrap-1",
            },
            json={"nome": "Administrador inicial"},
        )
    assert consumed.status_code == 200
    assert consumed.json()["papel"] == "secretary"
    assert bootstrapped.status_code == 201
    assert bootstrapped.json()["is_global_admin"] is True


@pytest.mark.asyncio
async def test_bootstrap_pode_usar_allowlist_de_email_sem_expor_token():
    settings = PwaSettings(
        supabase_url="https://example.supabase.co",
        supabase_anon_key="public",
        supabase_service_role_key="server",
        token_pepper="test-pepper",
        public_base_url="https://pwa.example",
        frontend_dist=Path("web/dist"),
        bootstrap_token="bootstrap-secret",
        bootstrap_email="SECRETARY@example.com",
    )
    async with make_client(FakeRepository(), settings) as client:
        response = await client.post(
            "/api/v1/bootstrap/admin",
            headers={"Authorization": "Bearer secretary", "Idempotency-Key": "bootstrap-email-1"},
            json={"nome": "Administrador inicial"},
        )

    assert response.status_code == 201
    assert response.json()["is_global_admin"] is True


@pytest.mark.asyncio
async def test_bootstrap_rejeita_email_fora_da_allowlist_sem_token():
    settings = PwaSettings(
        supabase_url="https://example.supabase.co",
        supabase_anon_key="public",
        supabase_service_role_key="server",
        token_pepper="test-pepper",
        public_base_url="https://pwa.example",
        frontend_dist=Path("web/dist"),
        bootstrap_token="bootstrap-secret",
        bootstrap_email="owner@example.com",
    )
    async with make_client(FakeRepository(), settings) as client:
        response = await client.post(
            "/api/v1/bootstrap/admin",
            headers={"Authorization": "Bearer secretary", "Idempotency-Key": "bootstrap-email-2"},
            json={"nome": "Administrador inicial"},
        )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_admin_cria_loja_e_arquiva_loja_existente():
    repo = FakeRepository()
    async with make_client(repo) as client:
        created = await client.post(
            "/api/v1/lojas",
            headers={"Authorization": "Bearer admin", "Idempotency-Key": "store-create"},
            json={"nome": "Loja Nova"},
        )
        archived = await client.delete(
            "/api/v1/lojas/1",
            headers={"Authorization": "Bearer admin", "Idempotency-Key": "store-archive"},
        )
    assert created.status_code == 201
    assert created.json()["slug"] == "loja-nova"
    assert archived.status_code == 200
    assert archived.json()["status"] == "archived"
    assert repo.audits[-1]["acao"] == "store_archived"


@pytest.mark.asyncio
async def test_arquivamento_de_loja_inexistente_retorna_404():
    async with make_client(MissingInviteStoreRepository()) as client:
        response = await client.delete(
            "/api/v1/lojas/404",
            headers={"Authorization": "Bearer admin", "Idempotency-Key": "store-missing"},
        )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_evento_pode_ser_atualizado_e_cancelado_com_auditoria():
    repo = FakeRepository()
    async with make_client(repo) as client:
        updated = await client.patch(
            "/api/v1/eventos/10",
            headers={"Authorization": "Bearer secretary", "Idempotency-Key": "event-update"},
            json={"titulo": "Sessão atualizada"},
        )
        cancelled = await client.delete(
            "/api/v1/eventos/10",
            headers={"Authorization": "Bearer secretary", "Idempotency-Key": "event-cancel"},
        )
    assert updated.status_code == 200
    assert updated.json()["titulo"] == "Sessão atualizada"
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert repo.audits[-1]["acao"] == "event_cancelled"


@pytest.mark.asyncio
async def test_secretario_lista_aprova_presenca_com_idempotencia():
    repo = FakeRepository()
    repo.presence = [
        {"id": 30, "evento_id": 10, "visitante_nome": "Visitante", "status": "pending", "agape": "sem"},
    ]
    async with make_client(repo) as client:
        listed = await client.get(
            "/api/v1/eventos/10/presencas",
            headers={"Authorization": "Bearer secretary"},
        )
        approved = await client.post(
            "/api/v1/presencas/30/aprovar",
            headers={"Authorization": "Bearer secretary", "Idempotency-Key": "presence-review"},
            json={},
        )
    assert listed.status_code == 200
    assert listed.json()["items"][0]["visitante_nome"] == "Visitante"
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert repo.audits[-1]["acao"] == "presence_approved"


@pytest.mark.asyncio
async def test_presenca_publica_nao_duplica_quando_repository_retorna_conflito():
    async with make_client(PublicPresenceConflictRepository()) as client:
        response = await client.post(
            "/api/v1/public/eventos/public-token/presencas",
            headers={"Idempotency-Key": "presence-duplicate"},
            json={"nome": "Visitante"},
        )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_secretario_prepara_card_e_publicacao_sem_expor_artefato_privado(monkeypatch):
    from types import SimpleNamespace

    card_path = Path(__file__).resolve().parents[1] / "assets" / "templates" / "default_event_card.png"
    monkeypatch.setattr(
        "src.render_cards.render_event_card",
        lambda *_args, **_kwargs: SimpleNamespace(path=str(card_path), warnings=[]),
    )
    monkeypatch.setattr(
        "src.pwa.api.to_legacy_card_payload",
        lambda event, store: (event, store),
    )
    repo = FakeRepository()

    async with make_client(repo) as client:
        response = await client.post(
            "/api/v1/eventos/10/card",
            headers={"Authorization": "Bearer secretary", "Idempotency-Key": "card-001"},
            json={"canal": "instagram"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["publication"]["estado"] == "prepared"
    assert body["artifact"]["bucket"] == "pwa-private"
    assert "public_token_hash" not in body
    assert repo.audits[-1]["acao"] == "event_card_prepared"
