from __future__ import annotations

import pytest

from app.core.ratelimit import RateLimitedError, SlidingWindowLimiter


def test_permite_ate_o_limite_e_bloqueia_o_seguinte() -> None:
    limiter = SlidingWindowLimiter(max_per_window=3, window_seconds=60)
    for i in range(3):
        limiter.check("u1", agora=100.0 + i)
    with pytest.raises(RateLimitedError) as erro:
        limiter.check("u1", agora=103.0)
    assert erro.value.details["retry_after_seconds"] >= 1


def test_janela_desliza() -> None:
    limiter = SlidingWindowLimiter(max_per_window=2, window_seconds=60)
    limiter.check("u1", agora=0.0)
    limiter.check("u1", agora=1.0)
    with pytest.raises(RateLimitedError):
        limiter.check("u1", agora=59.0)
    # A primeira chamada saiu da janela.
    limiter.check("u1", agora=61.0)


def test_chaves_sao_independentes() -> None:
    limiter = SlidingWindowLimiter(max_per_window=1, window_seconds=60)
    limiter.check("u1", agora=0.0)
    limiter.check("u2", agora=0.0)
    with pytest.raises(RateLimitedError):
        limiter.check("u1", agora=0.0)


def test_chamada_recusada_nao_estende_o_bloqueio() -> None:
    limiter = SlidingWindowLimiter(max_per_window=1, window_seconds=10)
    limiter.check("u1", agora=0.0)
    for t in (1.0, 5.0, 9.0):
        with pytest.raises(RateLimitedError):
            limiter.check("u1", agora=t)
    # Se as recusas contassem, ainda estaria bloqueado em 10.5.
    limiter.check("u1", agora=10.5)
