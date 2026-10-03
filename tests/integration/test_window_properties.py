import secrets
from collections import defaultdict
from dataclasses import dataclass, field

from hypothesis import given, settings
from hypothesis import strategies as st
from redis import Redis

from app.limiter import SCRIPT_PATH
from tests.conftest import TEST_REDIS_URL

REDIS_TIME_LINES = (
    "local time = redis.call('TIME')\n"
    "local now = tonumber(time[1]) * 1000 + math.floor(tonumber(time[2]) / 1000)\n"
)
START_MS = 1_700_000_000_000
CLIENTS = 3


def script_with_injected_time() -> str:
    source = SCRIPT_PATH.read_text()
    assert REDIS_TIME_LINES in source
    return source.replace(REDIS_TIME_LINES, "local now = tonumber(ARGV[4])\n")


@dataclass
class ReferenceWindow:
    limit: int
    window: int
    entries: dict[int, list[tuple[int, str]]] = field(default_factory=dict)
    last_counted: bool = False

    def check(self, client: int, now: int, member: str) -> list[int]:
        self.last_counted = False
        if self.limit <= 0:
            return [0, 0, now + self.window, self.window]
        active = [entry for entry in self.entries.get(client, []) if entry[0] >= now - self.window]
        duplicate = any(entry[1] == member for entry in active)
        allowed = duplicate or len(active) < self.limit
        if allowed and not duplicate:
            active.append((now, member))
            self.last_counted = True
        self.entries[client] = active
        free_at = min(score for score, _ in active) + self.window + 1
        return [int(allowed), max(0, self.limit - len(active)), free_at, free_at - now]

    def expected_ttl(self, client: int, now: int) -> int:
        return max(score for score, _ in self.entries[client]) + self.window - now + 1


def max_allowed_in_any_window(times: list[int], window: int) -> int:
    return max((sum(1 for t in times if end - window <= t <= end) for end in times), default=0)


BOUNDARY_STEPS = ["zero", "one", "half", "window-1", "window", "window+1"]

steps = st.one_of(st.sampled_from(BOUNDARY_STEPS), st.integers(min_value=0, max_value=700))
requests = st.lists(
    st.tuples(steps, st.integers(0, CLIENTS - 1), st.booleans()), min_size=1, max_size=60
)


def step_ms(step: str | int, window: int) -> int:
    if isinstance(step, int):
        return step
    return {
        "zero": 0,
        "one": 1,
        "half": window // 2,
        "window-1": window - 1,
        "window": window,
        "window+1": window + 1,
    }[step]


@settings(max_examples=150, deadline=None)
@given(requests=requests, limit=st.integers(0, 4), window=st.sampled_from([1000, 2000]))
def test_script_matches_reference_window(
    requests: list[tuple[str | int, int, bool]], limit: int, window: int
) -> None:
    client = Redis.from_url(TEST_REDIS_URL)
    keys = [f"rl:property-{index}" for index in range(CLIENTS)]
    client.delete(*keys)
    script = client.register_script(script_with_injected_time())
    model = ReferenceWindow(limit, window)
    allowed_at: dict[int, list[int]] = defaultdict(list)
    last_member: dict[int, str] = {}
    now = START_MS
    try:
        for step, client_index, is_retry in requests:
            now += step_ms(step, window)
            member = last_member.get(client_index) if is_retry else None
            member = member or secrets.token_hex(8)
            last_member[client_index] = member
            reply = script(keys=[keys[client_index]], args=[limit, window, member, now])
            decision = [int(value) for value in reply]
            assert decision == model.check(client_index, now, member)
            if model.last_counted:
                allowed_at[client_index].append(now)
            if limit <= 0:
                assert client.exists(keys[client_index]) == 0
            else:
                expected_ttl = model.expected_ttl(client_index, now)
                assert expected_ttl - 100 < client.pttl(keys[client_index]) <= expected_ttl
    finally:
        client.delete(*keys)
        client.close()

    for times in allowed_at.values():
        assert max_allowed_in_any_window(times, window) <= limit
