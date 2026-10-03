import asyncio
import math
import time

import httpx
from redis.asyncio import Redis

from app.limiter import key_for
from tests.conftest import ClientFactory

WINDOW_SEC = 2
WINDOW_MS = WINDOW_SEC * 1000


async def check(client: httpx.AsyncClient, client_id: str) -> dict[str, object]:
    response = await client.post("/check", json={"client_id": client_id})
    assert response.status_code == 200
    body: dict[str, object] = response.json()
    return body


async def allowed_series(client: httpx.AsyncClient, client_id: str, count: int) -> list[object]:
    return [(await check(client, client_id))["allowed"] for _ in range(count)]


async def oldest_score(redis: Redis, client_id: str) -> int:
    entries = await redis.zrange(key_for(client_id), 0, 0, withscores=True)
    return int(entries[0][1])


async def test_default_limit_and_client_isolation(app_client: ClientFactory) -> None:
    async with app_client(rate_limit=3) as client:
        first = await allowed_series(client, "alice", 4)
        other = await allowed_series(client, "bob", 3)

    assert first == [True, True, True, False]
    assert other == [True, True, True]


async def test_remaining_decreases_and_stays_at_zero(app_client: ClientFactory) -> None:
    async with app_client(rate_limit=3) as client:
        remaining = [(await check(client, "carol"))["remaining"] for _ in range(5)]

    assert remaining == [2, 1, 0, 0, 0]


async def test_rejected_check_carries_retry_after(app_client: ClientFactory) -> None:
    async with app_client(rate_limit=1, window_sec=WINDOW_SEC) as client:
        await check(client, "dave")
        response = await client.post("/check", json={"client_id": "dave"})

    assert response.json()["allowed"] is False
    assert 1 <= int(response.headers["Retry-After"]) <= WINDOW_SEC + 1


async def test_reset_at_follows_oldest_entry(app_client: ClientFactory, redis: Redis) -> None:
    async with app_client(rate_limit=5, window_sec=WINDOW_SEC) as client:
        first = await check(client, "erin")
        first_score = await oldest_score(redis, "erin")
        await asyncio.sleep(1.0)
        second = await check(client, "erin")
        await asyncio.sleep(1.2)
        third = await check(client, "erin")
        third_oldest = await oldest_score(redis, "erin")

    expected_first = math.ceil((first_score + WINDOW_MS + 1) / 1000)
    assert first["reset_at"] == expected_first
    assert second["reset_at"] == expected_first
    assert third_oldest > first_score
    assert third["reset_at"] == math.ceil((third_oldest + WINDOW_MS + 1) / 1000)


async def test_window_slides_instead_of_resetting(app_client: ClientFactory) -> None:
    async with app_client(rate_limit=2, window_sec=WINDOW_SEC) as client:
        started = time.monotonic()
        assert (await check(client, "frank"))["allowed"] is True
        await asyncio.sleep(1.0)
        assert (await check(client, "frank"))["allowed"] is True
        assert (await check(client, "frank"))["allowed"] is False
        await asyncio.sleep(2.3 - (time.monotonic() - started))
        after_first_expired = await allowed_series(client, "frank", 2)

    assert after_first_expired == [True, False]


async def test_limit_recovers_after_window(app_client: ClientFactory) -> None:
    async with app_client(rate_limit=2, window_sec=WINDOW_SEC) as client:
        exhausted = await allowed_series(client, "grace", 3)
        await asyncio.sleep(WINDOW_SEC + 0.3)
        recovered = await allowed_series(client, "grace", 3)

    assert exhausted == [True, True, False]
    assert recovered == [True, True, False]


async def test_zero_limit_rejects_without_creating_key(
    app_client: ClientFactory, redis: Redis
) -> None:
    async with app_client(rate_limit=0) as client:
        body = await check(client, "blocked")

    assert body["allowed"] is False
    assert body["remaining"] == 0
    assert await redis.exists(key_for("blocked")) == 0


async def test_ttl_is_set_by_newest_entry(app_client: ClientFactory, redis: Redis) -> None:
    async with app_client(rate_limit=1, window_sec=WINDOW_SEC) as client:
        await check(client, "heidi")
        ttl_after_allowed = await redis.pttl(key_for("heidi"))
        await asyncio.sleep(0.5)
        assert (await check(client, "heidi"))["allowed"] is False
        ttl_after_rejected = await redis.pttl(key_for("heidi"))

    assert 0 < ttl_after_allowed <= WINDOW_MS + 1
    assert ttl_after_rejected <= ttl_after_allowed - 400


async def test_key_of_inactive_client_disappears(app_client: ClientFactory, redis: Redis) -> None:
    async with app_client(rate_limit=3, window_sec=WINDOW_SEC) as client:
        await check(client, "ivan")
        assert await redis.exists(key_for("ivan")) == 1
        await asyncio.sleep(WINDOW_SEC + 0.3)

    assert await redis.exists(key_for("ivan")) == 0


async def test_concurrent_checks_never_exceed_limit(app_client: ClientFactory) -> None:
    async with app_client(
        rate_limit=100, redis_timeout_ms=10_000, redis_queue_timeout_ms=10_000
    ) as client:
        bodies = await asyncio.gather(*(check(client, "judy") for _ in range(300)))

    assert all(body["degraded"] is None for body in bodies)
    assert sum(body["allowed"] is True for body in bodies) == 100
