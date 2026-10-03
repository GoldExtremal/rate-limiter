import asyncio

import pytest
from redis.exceptions import BusyLoadingError, OutOfMemoryError, ReadOnlyError, ResponseError
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from app.admission import Admission
from app.breaker import BreakerState, CircuitBreaker
from app.decision import DegradedReason
from tests.unit.fakes import FakeClock, FakeScript, build_limiter

UNAVAILABLE_ERRORS = [
    RedisConnectionError("refused"),
    BusyLoadingError("loading"),
    OutOfMemoryError("OOM command not allowed"),
    ReadOnlyError("READONLY"),
]
TIMEOUT_ERRORS = [RedisTimeoutError("timeout"), TimeoutError()]


async def test_script_reply_becomes_decision() -> None:
    script = FakeScript()
    script.reply = (0, 0, 1_700_000_010_001, 2_500)

    decision = await build_limiter(script).check("client")

    assert decision.allowed is False
    assert (decision.limit, decision.remaining) == (10, 0)
    assert decision.reset_at == 1_700_000_011
    assert decision.retry_after == 3
    assert decision.degraded is None


async def test_individual_limit_is_passed_to_script() -> None:
    script = FakeScript()

    await build_limiter(script, limits={"vip": 7}).check("vip")

    assert script.calls[0]["keys"] == ["rl:vip"]
    assert script.calls[0]["args"][:2] == [7, 60_000]


async def test_request_id_becomes_member_and_generated_ids_are_namespaced() -> None:
    script = FakeScript()
    limiter = build_limiter(script)

    await limiter.check("client", "retry-1")
    await limiter.check("client")

    assert script.calls[0]["args"][2] == "r:retry-1"
    assert script.calls[1]["args"][2].startswith("g:")


@pytest.mark.parametrize("error", UNAVAILABLE_ERRORS, ids=lambda e: type(e).__name__)
async def test_fail_open_allows_on_unavailability(error: Exception) -> None:
    script = FakeScript()
    script.error = error

    decision = await build_limiter(script, fail_mode_open=True).check("client")

    assert decision.allowed is True
    assert decision.degraded is DegradedReason.REDIS_UNAVAILABLE
    assert (decision.remaining, decision.reset_at, decision.limit) == (None, None, None)


@pytest.mark.parametrize("error", UNAVAILABLE_ERRORS, ids=lambda e: type(e).__name__)
async def test_fail_closed_rejects_only_as_degraded(error: Exception) -> None:
    script = FakeScript()
    script.error = error

    decision = await build_limiter(script, fail_mode_open=False).check("client")

    assert decision.allowed is False
    assert decision.degraded is DegradedReason.REDIS_UNAVAILABLE
    assert decision.retry_after is None


@pytest.mark.parametrize("fail_mode_open", [True, False])
@pytest.mark.parametrize("error", TIMEOUT_ERRORS, ids=lambda e: type(e).__name__)
async def test_single_timeout_is_rejected_not_failed_open(
    error: Exception, fail_mode_open: bool
) -> None:
    script = FakeScript()
    script.error = error

    decision = await build_limiter(script, fail_mode_open=fail_mode_open).check("client")

    assert decision.allowed is False
    assert decision.degraded is DegradedReason.REDIS_TIMEOUT
    assert decision.retry_after == 1


async def test_timeouts_open_breaker_by_ratio_and_then_fail_open() -> None:
    script = FakeScript()
    script.error = RedisTimeoutError("timeout")
    breaker = CircuitBreaker(failure_threshold=100, cooldown_sec=5, min_calls=3)
    limiter = build_limiter(script, breaker=breaker, fail_mode_open=True)

    decisions = [await limiter.check("client") for _ in range(5)]

    assert [d.degraded for d in decisions[:2]] == [DegradedReason.REDIS_TIMEOUT] * 2
    assert all(d.degraded is DegradedReason.REDIS_UNAVAILABLE for d in decisions[2:])
    assert all(d.allowed for d in decisions[2:])


async def test_script_error_propagates_and_does_not_touch_breaker() -> None:
    script = FakeScript()
    script.error = ResponseError("WRONGTYPE Operation against a key")
    breaker = CircuitBreaker(failure_threshold=2, cooldown_sec=5)
    limiter = build_limiter(script, breaker=breaker)

    for _ in range(5):
        with pytest.raises(ResponseError):
            await limiter.check("client")

    assert breaker.state is BreakerState.CLOSED


async def test_open_breaker_stops_calling_redis() -> None:
    script = FakeScript()
    script.error = RedisConnectionError("refused")
    breaker = CircuitBreaker(failure_threshold=3, cooldown_sec=5)
    limiter = build_limiter(script, breaker=breaker, fail_mode_open=False)

    decisions = [await limiter.check("client") for _ in range(10)]

    assert len(script.calls) == 3
    assert breaker.state is BreakerState.OPEN
    assert decisions[-1].retry_after == 5


async def test_breaker_recovers_through_probe() -> None:
    clock = FakeClock()
    script = FakeScript()
    script.error = RedisConnectionError("refused")
    breaker = CircuitBreaker(failure_threshold=1, cooldown_sec=5, clock=clock)
    limiter = build_limiter(script, breaker=breaker)
    await limiter.check("client")
    clock.advance(5)
    script.error = None

    decision = await limiter.check("client")

    assert decision.degraded is None
    assert breaker.state is BreakerState.CLOSED


async def test_cancelled_probe_is_released() -> None:
    clock = FakeClock()
    script = FakeScript()
    script.error = RedisConnectionError("refused")
    breaker = CircuitBreaker(failure_threshold=1, cooldown_sec=5, clock=clock)
    limiter = build_limiter(script, breaker=breaker)
    await limiter.check("client")
    clock.advance(5)
    script.error = None
    script.release = asyncio.Event()

    probe = asyncio.create_task(limiter.check("client"))
    await asyncio.sleep(0.01)
    probe.cancel()
    with pytest.raises(asyncio.CancelledError):
        await probe

    assert breaker.state is BreakerState.HALF_OPEN
    assert breaker.allow_request() is True


@pytest.mark.parametrize("fail_mode_open", [True, False])
async def test_overload_never_fails_open(fail_mode_open: bool) -> None:
    script = FakeScript()
    script.release = asyncio.Event()
    breaker = CircuitBreaker(failure_threshold=1, cooldown_sec=5)
    limiter = build_limiter(
        script,
        fail_mode_open=fail_mode_open,
        breaker=breaker,
        admission=Admission(slots=1, timeout_sec=0.05),
    )

    holder = asyncio.create_task(limiter.check("client"))
    await asyncio.sleep(0.01)
    decision = await limiter.check("client")
    script.release.set()
    await holder

    assert decision.allowed is False
    assert decision.degraded is DegradedReason.OVERLOADED
    assert decision.retry_after == 1
    assert breaker.state is BreakerState.CLOSED
