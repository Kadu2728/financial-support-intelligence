"""Rate limiting por usuario, em memoria.

Janela deslizante simples: guarda os instantes das ultimas chamadas de cada chave e
conta quantas cairam no ultimo minuto. Sem dependencia externa.

Limitacao declarada: o estado vive no processo. Com duas instancias atras de um
balanceador, cada uma aplica o limite separadamente — o teto efetivo dobra. E
aceitavel para uma instancia (o caso atual); com mais, o lugar certo e Redis, e
esta classe e a unica coisa a trocar.
"""

from __future__ import annotations

import time
from collections import deque
from threading import Lock

from app.core.errors import AppError, ErrorCode


class RateLimitedError(AppError):
    status_code = 429
    code = ErrorCode.RATE_LIMITED
    message = "Muitas perguntas em pouco tempo. Aguarde um instante e tente novamente."


class SlidingWindowLimiter:
    def __init__(self, *, max_per_window: int, window_seconds: float = 60.0) -> None:
        self._max = max_per_window
        self._window = window_seconds
        self._historico: dict[str, deque[float]] = {}
        self._lock = Lock()

    def check(self, chave: str, *, agora: float | None = None) -> None:
        """Registra a chamada ou levanta `RateLimitedError`.

        A chamada recusada NAO e registrada: um usuario bloqueado que insiste nao
        estende o proprio bloqueio.
        """
        agora = time.monotonic() if agora is None else agora
        limite = agora - self._window

        with self._lock:
            fila = self._historico.setdefault(chave, deque())
            while fila and fila[0] <= limite:
                fila.popleft()

            if len(fila) >= self._max:
                espera = int(fila[0] + self._window - agora) + 1
                raise RateLimitedError(details={"retry_after_seconds": espera})

            fila.append(agora)

            # Evita crescimento indefinido do dicionario com chaves ociosas.
            if len(self._historico) > 10_000:
                ociosas = [k for k, f in self._historico.items() if not f or f[-1] <= limite]
                for k in ociosas:
                    del self._historico[k]
