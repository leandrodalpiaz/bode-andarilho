from src.pwa.security import FixedWindowRateLimiter, hash_secret


def test_token_hash_nao_eh_o_token_original():
    assert hash_secret("token-original", "pepper") != "token-original"
    assert hash_secret("token-original", "pepper") == hash_secret("token-original", "pepper")


def test_rate_limiter_bloqueia_excesso_na_janela():
    limiter = FixedWindowRateLimiter(limit=2, window_seconds=60)
    assert limiter.allow("ip:event", now=100)
    assert limiter.allow("ip:event", now=101)
    assert not limiter.allow("ip:event", now=102)
    assert limiter.allow("ip:event", now=161)
