import pytest

from src.adapters.telegram_legacy import LegacyTelegramAdapter
from src.domain.validation import DomainValidationError


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
