import asyncio
from collections.abc import Sequence
from typing import Any, cast

from redis.asyncio import Redis

from app.admission import Admission
from app.breaker import CircuitBreaker
from app.limiter import RateLimiter
from app.limits import LimitsProvider
from app.metrics import Metrics


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeScript:
    def __init__(self) -> None:
        self.reply: Sequence[int] = (1, 9, 1_700_000_060_001, 60_001)
        self.error: BaseException | None = None
        self.release: asyncio.Event | None = None
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, keys: list[str], args: list[Any]) -> Sequence[int]:
        self.calls.append({"keys": keys, "args": args})
        if self.release is not None:
            await self.release.wait()
        if self.error is not None:
            raise self.error
        return self.reply


class FakeRedis:
    def __init__(self, script: FakeScript) -> None:
        self.script = script

    def register_script(self, source: str) -> FakeScript:
        return self.script


def build_limiter(
    script: FakeScript,
    *,
    fail_mode_open: bool = True,
    breaker: CircuitBreaker | None = None,
    admission: Admission | None = None,
    limits: dict[str, int] | None = None,
) -> RateLimiter:
    return RateLimiter(
        cast(Redis, FakeRedis(script)),
        admission or Admission(slots=4, timeout_sec=1),
        LimitsProvider(10, limits),
        breaker or CircuitBreaker(failure_threshold=5, cooldown_sec=5),
        Metrics(),
        window_sec=60,
        fail_mode_open=fail_mode_open,
    )
