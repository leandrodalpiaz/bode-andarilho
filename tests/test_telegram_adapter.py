import pytest

from src.adapters.telegram_legacy import LegacyTelegramAdapter
from src.domain.validation import DomainValidationError


class _FakeMessage:
    def __init__(self):
        self.replies = []

    async def reply_text(self, text, **kwargs):
        self.replies.append((text, kwargs))


class _FakeClient:
    calls = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def post(self, url, *, headers, json):
        self.calls.append((url, headers, json))
        return type("Response", (), {"status_code": 200, "json": lambda self: {"perfil_id": "p1"}})()


def test_adapter_telegram_isola_identidade_externa():
    assert LegacyTelegramAdapter().external_identity(12345) == {
        "provedor": "telegram",
        "external_user_id": "12345",
    }
    with pytest.raises(DomainValidationError):
        LegacyTelegramAdapter().external_identity(0)


def test_adapter_converte_evento_sem_relacionar_registro_legado():
    payload = LegacyTelegramAdapter().event_payload(
        {
            "Data do evento": "10/09/2026",
            "Hora": "20:00",
            "Nome da loja": "Loja Piloto",
            "ID da loja": "1",
        }
    )
    assert payload["loja_id"] == 1
    assert payload["evento_at"].startswith("2026-09-10T20:00:00")
    assert "telegram_id" not in payload


def test_adapter_pwa_existe_sem_transportar_segredo_do_backend():
    from src.adapters.telegram_pwa import _api_error

    assert _api_error({"error": {"message": "código expirado"}}) == "código expirado"


@pytest.mark.asyncio
async def test_comando_vincular_usa_somente_chat_privado(monkeypatch):
    from src.adapters import telegram_pwa

    message = _FakeMessage()
    update = type(
        "Update",
        (),
        {
            "effective_message": message,
            "effective_user": type("User", (), {"id": 12345})(),
            "effective_chat": type("Chat", (), {"type": "private"})(),
        },
    )()
    context = type("Context", (), {"args": ["one-time-code"]})()
    _FakeClient.calls = []
    monkeypatch.setenv("PWA_PUBLIC_BASE_URL", "https://pwa.example")
    monkeypatch.setattr(telegram_pwa.httpx, "AsyncClient", _FakeClient)

    await telegram_pwa.vincular_telegram(update, context)

    assert "associado" in message.replies[0][0]
    assert _FakeClient.calls[0][0] == "https://pwa.example/api/v1/public/identidades/telegram/associar"
    assert _FakeClient.calls[0][2] == {"codigo": "one-time-code", "telegram_id": "12345"}


@pytest.mark.asyncio
async def test_flag_de_corte_redireciona_mutacao_para_pwa_e_falha_fechado(monkeypatch):
    from src.adapters import telegram_pwa

    message = _FakeMessage()
    update = type(
        "Update",
        (),
        {
            "effective_message": message,
            "effective_user": type("User", (), {"id": 12345})(),
            "effective_chat": type("Chat", (), {"type": "private"})(),
        },
    )()
    monkeypatch.setenv("TELEGRAM_MUTATIONS_TO_PWA", "true")
    monkeypatch.setenv("PWA_PUBLIC_BASE_URL", "https://pwa.example")

    assert await telegram_pwa.redirect_mutation_to_pwa(update, "cadastro de sessão")
    assert "direcionado para a PWA" in message.replies[0][0]
    assert "https://pwa.example" in message.replies[0][0] or message.replies[0][1].get("reply_markup") is not None


@pytest.mark.asyncio
async def test_flag_de_corte_sem_url_nao_retorna_ao_fluxo_legado(monkeypatch):
    from src.adapters import telegram_pwa

    message = _FakeMessage()
    update = type(
        "Update",
        (),
        {
            "effective_message": message,
            "effective_user": type("User", (), {"id": 12345})(),
            "effective_chat": type("Chat", (), {"type": "private"})(),
        },
    )()
    monkeypatch.setenv("TELEGRAM_MUTATIONS_TO_PWA", "true")
    monkeypatch.delenv("PWA_PUBLIC_BASE_URL", raising=False)
    monkeypatch.delenv("RENDER_EXTERNAL_URL", raising=False)

    assert await telegram_pwa.redirect_mutation_to_pwa(update, "cadastro de loja")
    assert "endereço público" in message.replies[0][0]
