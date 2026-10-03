import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import IntEnum


class BreakerState(IntEnum):
    CLOSED = 0
    OPEN = 1
    HALF_OPEN = 2


@dataclass(slots=True)
class SecondBucket:
    second: int = -1
    calls: int = 0
    failures: int = 0


class CircuitBreaker:
    def __init__(
        self,
        failure_threshold: int,
        cooldown_sec: float,
        *,
        window_sec: int = 10,
        min_calls: int = 10,
        failure_ratio: float = 0.5,
        min_failure_seconds: int = 3,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._failure_threshold = failure_threshold
        self._cooldown_sec = cooldown_sec
        self._window_sec = window_sec
        self._min_calls = min_calls
        self._failure_ratio = failure_ratio
        self._min_failure_seconds = min_failure_seconds
        self._clock = clock
        self._buckets = [SecondBucket() for _ in range(window_sec)]
        self._state = BreakerState.CLOSED
        self._consecutive_definite_failures = 0
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
        if self._state is BreakerState.CLOSED:
            self._current_bucket().calls += 1
        else:
            self._reset_window()
        self._state = BreakerState.CLOSED
        self._consecutive_definite_failures = 0
        self._probe_in_flight = False

    def record_failure(self, *, definite: bool = True) -> None:
        if self._state is BreakerState.HALF_OPEN:
            self._open()
            return
        if self._state is not BreakerState.CLOSED:
            return
        bucket = self._current_bucket()
        bucket.calls += 1
        bucket.failures += 1
        if definite:
            self._consecutive_definite_failures += 1
        if self._too_many_consecutive_failures() or self._failure_ratio_exceeded():
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

    def _too_many_consecutive_failures(self) -> bool:
        return self._consecutive_definite_failures >= self._failure_threshold

    def _failure_ratio_exceeded(self) -> bool:
        oldest_second = int(self._clock()) - self._window_sec + 1
        recent = [bucket for bucket in self._buckets if bucket.second >= oldest_second]
        calls = sum(bucket.calls for bucket in recent)
        failures = sum(bucket.failures for bucket in recent)
        failing_seconds = sum(1 for bucket in recent if bucket.failures)
        return (
            calls >= self._min_calls
            and failures >= calls * self._failure_ratio
            and failing_seconds >= self._min_failure_seconds
        )

    def _current_bucket(self) -> SecondBucket:
        second = int(self._clock())
        bucket = self._buckets[second % self._window_sec]
        if bucket.second != second:
            bucket.second, bucket.calls, bucket.failures = second, 0, 0
        return bucket

    def _reset_window(self) -> None:
        for bucket in self._buckets:
            bucket.second, bucket.calls, bucket.failures = -1, 0, 0

    def _open(self) -> None:
        self._state = BreakerState.OPEN
        self._opened_at = self._clock()
        self._consecutive_definite_failures = 0
        self._probe_in_flight = False
        self._reset_window()
