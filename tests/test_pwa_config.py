from pathlib import Path

from src.pwa.config import PwaSettings


def test_pwa_reutiliza_chave_historica_do_bot_somente_no_backend(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", "legacy-server-key")
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    monkeypatch.setenv("SUPABASE_ANON_KEY", "public-key")
    monkeypatch.setenv("PWA_TOKEN_PEPPER", "test-pepper")

    settings = PwaSettings.from_env()

    assert settings.supabase_service_role_key == "legacy-server-key"
    assert settings.supabase_anon_key == "public-key"


def test_pwa_nao_promove_chave_historica_a_chave_publica(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", "legacy-server-key")
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_ANON_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_PUBLISHABLE_KEY", raising=False)

    settings = PwaSettings.from_env()

    assert settings.supabase_anon_key == ""
    assert settings.supabase_service_role_key == "legacy-server-key"


def test_bootstrap_email_eh_normalizado_sem_ser_enviado_ao_navegador(monkeypatch):
    monkeypatch.setenv("PWA_BOOTSTRAP_EMAIL", "  ADMINISTRADOR@EXEMPLO.COM ")

    settings = PwaSettings.from_env()

    assert settings.bootstrap_email == "administrador@exemplo.com"
