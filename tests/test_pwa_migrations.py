from pathlib import Path


MIGRATIONS_DIR = Path(__file__).parents[1] / "supabase" / "migrations"


def test_bootstrap_admin_serializa_a_primeira_configuracao():
    migration = MIGRATIONS_DIR / "20260901200000_harden_bootstrap_admin_lock.sql"
    sql = " ".join(migration.read_text(encoding="utf-8").split()).lower()

    assert "pg_advisory_xact_lock" in sql
    assert "hashtextextended('pwa_v2.bootstrap_admin', 0)" in sql
    assert "where loja_id is null and papel = 'admin'" in sql
    assert "where loja_id is null and papel = 'admin' and status = 'active'" not in sql
