import pytest

from src.application.publication import build_event_caption
from src.domain.validation import DomainValidationError


def test_legenda_independente_de_telegram_reune_dados_publicos():
    caption = build_event_caption(
        {
            "titulo": "Sessão aberta",
            "evento_at": "2026-09-10T23:00:00+00:00",
            "grau": "Mestre",
            "rito": "REAA",
            "ordem_do_dia": "Abertura e trabalhos",
            "endereco_sessao": "Rua da Loja, 10",
        },
        {"nome": "Loja Piloto", "numero_loja": "101", "cidade": "São Paulo", "uf": "sp"},
        public_url="https://pwa.example/evento/token",
    )
    assert "Sessão aberta" in caption
    assert "10/09/2026" in caption
    assert "Loja Piloto nº 101" in caption
    assert "Solicite sua presença: https://pwa.example/evento/token" in caption


def test_legenda_rejeita_data_sem_fuso():
    with pytest.raises(DomainValidationError):
        build_event_caption({"evento_at": "2026-09-10T20:00:00"}, {"nome": "Loja"})
