import logging
import secrets
from collections.abc import Sequence
from pathlib import Path

from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import OutOfMemoryError, ReadOnlyError
from redis.exceptions import TimeoutError as RedisTimeoutError

from app.admission import Admission
from app.decision import Decision, DegradedReason
from app.limits import LimitsProvider

SCRIPT_PATH = Path(__file__).parent / "lua" / "sliding_window.lua"
MS_PER_SECOND = 1000
KEY_PREFIX = "rl:"
MEMBER_BYTES = 8

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


class RateLimiter:
    def __init__(
        self,
        redis: Redis,
        admission: Admission,
        limits: LimitsProvider,
        *,
        window_sec: int,
        fail_mode_open: bool,
    ) -> None:
        self._script = redis.register_script(SCRIPT_PATH.read_text())
        self._admission = admission
        self.limits = limits
        self._window_ms = window_sec * MS_PER_SECOND
        self._fail_mode_open = fail_mode_open

    async def check(self, client_id: str) -> Decision:
        limit = self.limits.get(client_id)
        async with self._admission.slot():
            try:
                reply = await self._script(
                    keys=[key_for(client_id)],
                    args=[limit, self._window_ms, secrets.token_hex(MEMBER_BYTES)],
                )
            except REDIS_UNAVAILABLE_ERRORS as error:
                logger.warning("redis is unavailable: %s", classify_redis_error(error))
                return self.unavailable_decision()
        return decision_from_script(limit, reply)

    def unavailable_decision(self) -> Decision:
        return Decision(
            allowed=self._fail_mode_open,
            limit=None,
            remaining=None,
            reset_at=None,
            retry_after=None,
            degraded=DegradedReason.REDIS_UNAVAILABLE,
        )
