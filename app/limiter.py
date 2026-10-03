import logging
import secrets
import time
from collections.abc import Sequence
from functools import partial
from pathlib import Path

from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import OutOfMemoryError, ReadOnlyError, ResponseError
from redis.exceptions import TimeoutError as RedisTimeoutError

from app.admission import Admission, AdmissionTimeout
from app.breaker import BreakerState, CircuitBreaker
from app.decision import Decision, DegradedReason
from app.limits import LimitsProvider
from app.metrics import Metrics

SCRIPT_PATH = Path(__file__).parent / "lua" / "sliding_window.lua"
MS_PER_SECOND = 1000
KEY_PREFIX = "rl:"
MEMBER_BYTES = 8
GENERATED_MEMBER_PREFIX = "g:"
REQUEST_MEMBER_PREFIX = "r:"

REDIS_UNAVAILABLE_ERRORS = (
    RedisConnectionError,
    RedisTimeoutError,
    TimeoutError,
    OutOfMemoryError,
    ReadOnlyError,
)

logger = logging.getLogger(__name__)


def key_for(client_id: str) -> str:
    return f"{KEY_PREFIX}{client_id}"


def member_for(request_id: str | None) -> str:
    if request_id is None:
        return GENERATED_MEMBER_PREFIX + secrets.token_hex(MEMBER_BYTES)
    return REQUEST_MEMBER_PREFIX + request_id


def ceil_seconds(milliseconds: int) -> int:
    return -(-milliseconds // MS_PER_SECOND)


def classify_redis_error(error: BaseException) -> str:
    if isinstance(error, RedisConnectionError):
        return "connection"
    if isinstance(error, OutOfMemoryError):
        return "oom"
    if isinstance(error, ReadOnlyError):
        return "readonly"
    return "timeout"


def decision_from_script(limit: int, reply: Sequence[int]) -> Decision:
    allowed, remaining, free_at_ms, retry_after_ms = (int(value) for value in reply)
    is_allowed = allowed == 1
    return Decision(
        allowed=is_allowed,
        limit=limit,
        remaining=remaining,
        reset_at=ceil_seconds(free_at_ms),
        retry_after=None if is_allowed else max(1, ceil_seconds(retry_after_ms)),
    )


def snapshot_age_or_never(limits: LimitsProvider) -> float:
    age = limits.snapshot_age_sec()
    return -1.0 if age is None else age


def overloaded_decision() -> Decision:
    return Decision(
        allowed=False,
        limit=None,
        remaining=None,
        reset_at=None,
        retry_after=1,
        degraded=DegradedReason.OVERLOADED,
    )


def timeout_decision() -> Decision:
    return Decision(
        allowed=False,
        limit=None,
        remaining=None,
        reset_at=None,
        retry_after=1,
        degraded=DegradedReason.REDIS_TIMEOUT,
    )


class RateLimiter:
    def __init__(
        self,
        redis: Redis,
        admission: Admission,
        limits: LimitsProvider,
        breaker: CircuitBreaker,
        metrics: Metrics,
        *,
        window_sec: int,
        fail_mode_open: bool,
    ) -> None:
        self._script = redis.register_script(SCRIPT_PATH.read_text())
        self._admission = admission
        self.limits = limits
        self.breaker = breaker
        self.metrics = metrics
        metrics.breaker_state.set_function(lambda: float(breaker.state))
        metrics.inflight_checks.set_function(lambda: float(admission.in_use))
        metrics.limits_loaded.set_function(lambda: 1.0 if limits.loaded else 0.0)
        metrics.limits_snapshot_age.set_function(partial(snapshot_age_or_never, limits))
        self._window_ms = window_sec * MS_PER_SECOND
        self._fail_mode_open = fail_mode_open

    async def check(self, client_id: str, request_id: str | None = None) -> Decision:
        started = time.perf_counter()
        limit = self.limits.get(client_id)
        try:
            async with self._admission.slot():
                decision = await self._check_in_redis(client_id, limit, member_for(request_id))
        except AdmissionTimeout:
            decision = overloaded_decision()
        self.metrics.record(decision, time.perf_counter() - started)
        return decision

    async def _check_in_redis(self, client_id: str, limit: int, member: str) -> Decision:
        if not self.breaker.allow_request():
            return self.unavailable_decision()
        is_probe = self.breaker.state is BreakerState.HALF_OPEN
        try:
            with self.metrics.redis_duration.time():
                reply = await self._script(
                    keys=[key_for(client_id)],
                    args=[limit, self._window_ms, member],
                )
        except REDIS_UNAVAILABLE_ERRORS as error:
            kind = classify_redis_error(error)
            self.breaker.record_failure(definite=kind != "timeout")
            self.metrics.redis_errors.labels(kind).inc()
            logger.warning("redis is unavailable", extra={"kind": kind})
            if kind == "timeout" and self.breaker.state is not BreakerState.OPEN:
                return timeout_decision()
            return self.unavailable_decision()
        except ResponseError:
            self.metrics.script_errors.inc()
            logger.exception("redis rejected the rate limit script")
            if is_probe:
                self.breaker.release_probe()
            raise
        except BaseException:
            if is_probe:
                self.breaker.release_probe()
            raise
        self.breaker.record_success()
        return decision_from_script(limit, reply)

    def unavailable_decision(self) -> Decision:
        return Decision(
            allowed=self._fail_mode_open,
            limit=None,
            remaining=None,
            reset_at=None,
            retry_after=None if self._fail_mode_open else self.breaker.retry_after(),
            degraded=DegradedReason.REDIS_UNAVAILABLE,
        )
