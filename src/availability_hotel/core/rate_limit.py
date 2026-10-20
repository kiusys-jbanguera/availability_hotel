"""Rate limit en memoria por proveedor (HU004).

Dos algoritmos con la misma interfaz:
- `sliding_window` (por defecto): log de marcas de tiempo acotado a `requests`
  entradas. Garantiza no superar `requests` en ninguna ventana de `per_seconds`
  (RNF-02). O(1) amortizado por adquisicion, O(requests) memoria.
- `token_bucket` (DC-01 original): O(1) por adquisicion y memoria; admite
  `burst`, pero puede superar `requests` en una ventana deslizante.
"""

import asyncio
import time
from collections import deque
from collections.abc import Callable
from email.utils import parsedate_to_datetime
from datetime import UTC, datetime

Clock = Callable[[], float]


class RateLimiter:
    """Limitador por proveedor; compartido entre consultas del proceso (RF-07)."""

    def __init__(self, clock: Clock = time.monotonic) -> None:
        self._clock = clock
        self._blocked_until = 0.0

    def block_for(self, seconds: float) -> None:
        """Bloquea el proveedor tras un 429 respetando `Retry-After` (RF-06)."""
        self._blocked_until = max(self._blocked_until, self._clock() + seconds)

    def is_blocked(self) -> bool:
        return self._clock() < self._blocked_until

    def _try_acquire(self, now: float) -> float:
        """Devuelve 0 si consumio cupo o los segundos a esperar para reintentar."""
        return 0.0

    async def acquire(self, deadline: float) -> bool:
        """Espera cupo como maximo hasta `deadline` (DC-02); False si no lo obtiene."""
        while True:
            now = self._clock()
            if now < self._blocked_until:
                return False
            wait = self._try_acquire(now)
            if wait <= 0:
                return True
            if now + wait > deadline:
                return False
            await asyncio.sleep(wait)


class SlidingWindowLimiter(RateLimiter):
    def __init__(
        self, requests: int, per_seconds: float, clock: Clock = time.monotonic
    ) -> None:
        super().__init__(clock)
        self._requests = requests
        self._per_seconds = per_seconds
        self._log: deque[float] = deque(maxlen=requests)

    def _try_acquire(self, now: float) -> float:
        while self._log and self._log[0] <= now - self._per_seconds:
            self._log.popleft()
        if len(self._log) < self._requests:
            self._log.append(now)
            return 0.0
        return self._log[0] + self._per_seconds - now


class TokenBucketLimiter(RateLimiter):
    def __init__(
        self,
        requests: int,
        per_seconds: float,
        burst: int | None = None,
        clock: Clock = time.monotonic,
    ) -> None:
        super().__init__(clock)
        self._rate = requests / per_seconds
        self._capacity = float(burst or requests)
        self._tokens = self._capacity
        self._updated = clock()

    def _try_acquire(self, now: float) -> float:
        elapsed = max(0.0, now - self._updated)
        self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
        self._updated = now
        if self._tokens >= 1:
            self._tokens -= 1
            return 0.0
        return (1 - self._tokens) / self._rate


def parse_retry_after(value: str | None, now: datetime | None = None) -> float | None:
    """Interpreta `Retry-After` en segundos o como fecha HTTP."""
    if not value:
        return None
    text = value.strip()
    try:
        return max(0.0, float(text))
    except ValueError:
        pass
    try:
        moment = parsedate_to_datetime(text)
    except TypeError, ValueError:
        return None
    reference = now or datetime.now(UTC)
    return max(0.0, (moment - reference).total_seconds())
