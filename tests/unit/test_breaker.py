import asyncio

from app.breaker import BreakerState, CircuitBreaker
from tests.unit.fakes import FakeClock


def open_breaker(clock: FakeClock, threshold: int = 3, cooldown: float = 5) -> CircuitBreaker:
    breaker = CircuitBreaker(failure_threshold=threshold, cooldown_sec=cooldown, clock=clock)
    for _ in range(threshold):
        breaker.record_failure()
    return breaker


def test_closed_breaker_allows_requests() -> None:
    breaker = CircuitBreaker(failure_threshold=3, cooldown_sec=5)

    assert breaker.allow_request() is True
    assert breaker.state is BreakerState.CLOSED
    assert breaker.retry_after() is None


def test_opens_after_consecutive_failures() -> None:
    breaker = open_breaker(FakeClock())

    assert breaker.state is BreakerState.OPEN
    assert breaker.allow_request() is False


def test_success_resets_consecutive_failures() -> None:
    breaker = CircuitBreaker(failure_threshold=3, cooldown_sec=5)
    for _ in range(2):
        breaker.record_failure()
    breaker.record_success()
    for _ in range(2):
        breaker.record_failure()

    assert breaker.state is BreakerState.CLOSED


def test_open_breaker_reports_remaining_cooldown() -> None:
    clock = FakeClock()
    breaker = open_breaker(clock, cooldown=5)
    clock.advance(3.2)

    assert breaker.retry_after() == 2
    assert breaker.allow_request() is False


def test_half_open_lets_exactly_one_probe_through() -> None:
    clock = FakeClock()
    breaker = open_breaker(clock)
    clock.advance(5)

    assert breaker.allow_request() is True
    assert breaker.state is BreakerState.HALF_OPEN
    assert breaker.allow_request() is False


async def test_concurrent_tasks_after_cooldown_get_one_probe() -> None:
    clock = FakeClock()
    breaker = open_breaker(clock)
    clock.advance(5)

    async def try_request() -> bool:
        await asyncio.sleep(0)
        return breaker.allow_request()

    results = await asyncio.gather(*(try_request() for _ in range(50)))

    assert results.count(True) == 1


def test_successful_probe_closes_breaker() -> None:
    clock = FakeClock()
    breaker = open_breaker(clock)
    clock.advance(5)
    breaker.allow_request()
    breaker.record_success()

    assert breaker.state is BreakerState.CLOSED
    assert breaker.allow_request() is True


def test_failed_probe_reopens_with_new_cooldown() -> None:
    clock = FakeClock()
    breaker = open_breaker(clock, cooldown=5)
    clock.advance(5)
    breaker.allow_request()
    breaker.record_failure()

    assert breaker.state is BreakerState.OPEN
    assert breaker.retry_after() == 5


def test_released_probe_can_be_taken_again() -> None:
    clock = FakeClock()
    breaker = open_breaker(clock)
    clock.advance(5)
    breaker.allow_request()
    breaker.release_probe()

    assert breaker.allow_request() is True


def ratio_breaker(clock: FakeClock) -> CircuitBreaker:
    return CircuitBreaker(
        failure_threshold=3,
        cooldown_sec=5,
        window_sec=10,
        min_calls=10,
        failure_ratio=0.5,
        clock=clock,
    )


def test_timeouts_do_not_trip_consecutive_rule() -> None:
    breaker = ratio_breaker(FakeClock())
    for _ in range(9):
        breaker.record_failure(definite=False)

    assert breaker.state is BreakerState.CLOSED


def test_timeouts_open_breaker_by_failure_ratio() -> None:
    breaker = ratio_breaker(FakeClock())
    for _ in range(5):
        breaker.record_success()
    for _ in range(5):
        breaker.record_failure(definite=False)

    assert breaker.state is BreakerState.OPEN


def test_sporadic_timeouts_under_load_keep_breaker_closed() -> None:
    clock = FakeClock()
    breaker = ratio_breaker(clock)
    for _ in range(200):
        for _ in range(3):
            breaker.record_success()
        breaker.record_failure(definite=False)
        clock.advance(0.05)

    assert breaker.state is BreakerState.CLOSED


def test_failures_outside_window_are_forgotten() -> None:
    clock = FakeClock()
    breaker = ratio_breaker(clock)
    for _ in range(9):
        breaker.record_failure(definite=False)
    clock.advance(11)
    for _ in range(9):
        breaker.record_success()
    breaker.record_failure(definite=False)

    assert breaker.state is BreakerState.CLOSED


def test_definite_failures_open_breaker_even_at_low_traffic() -> None:
    clock = FakeClock()
    breaker = ratio_breaker(clock)
    for _ in range(3):
        breaker.record_failure(definite=True)
        clock.advance(60)

    assert breaker.state is BreakerState.OPEN
