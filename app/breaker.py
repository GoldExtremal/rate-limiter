import math
import time
from collections.abc import Callable
from enum import IntEnum


class BreakerState(IntEnum):
    CLOSED = 0
    OPEN = 1
    HALF_OPEN = 2


class CircuitBreaker:
    def __init__(
        self,
        failure_threshold: int,
        cooldown_sec: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._failure_threshold = failure_threshold
        self._cooldown_sec = cooldown_sec
        self._clock = clock
        self._state = BreakerState.CLOSED
        self._consecutive_failures = 0
        self._opened_at = 0.0
        self._probe_in_flight = False

    @property
    def state(self) -> BreakerState:
        return self._state

    def allow_request(self) -> bool:
        if self._state is BreakerState.CLOSED:
            return True
        if self._state is BreakerState.OPEN:
            if self.remaining_cooldown() > 0:
                return False
            self._state = BreakerState.HALF_OPEN
        if self._probe_in_flight:
            return False
        self._probe_in_flight = True
        return True

    def record_success(self) -> None:
        self._state = BreakerState.CLOSED
        self._consecutive_failures = 0
        self._probe_in_flight = False

    def record_failure(self) -> None:
        if self._state is BreakerState.HALF_OPEN:
            self._open()
            return
        if self._state is BreakerState.CLOSED:
            self._consecutive_failures += 1
            if self._consecutive_failures >= self._failure_threshold:
                self._open()

    def release_probe(self) -> None:
        self._probe_in_flight = False

    def remaining_cooldown(self) -> float:
        if self._state is not BreakerState.OPEN:
            return 0.0
        return max(0.0, self._cooldown_sec - (self._clock() - self._opened_at))

    def retry_after(self) -> int | None:
        if self._state is BreakerState.CLOSED:
            return None
        return max(1, math.ceil(self.remaining_cooldown()))

    def _open(self) -> None:
        self._state = BreakerState.OPEN
        self._opened_at = self._clock()
        self._consecutive_failures = 0
        self._probe_in_flight = False
