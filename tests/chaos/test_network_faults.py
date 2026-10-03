import asyncio
import os
import time
import uuid
from collections.abc import AsyncIterator

import asyncpg
import httpx
import pytest
from prometheus_client.parser import text_string_to_metric_families

from app.migrate import seed_client_limits
from tests.chaos.conftest import InProcessFactory

TOXIPROXY_URL = os.environ.get("TOXIPROXY_URL", "http://localhost:8474")
PROXIED_REDIS_URL = os.environ.get("PROXIED_REDIS_URL", "redis://localhost:26379/15")
PROXIED_DATABASE_URL = os.environ.get(
    "PROXIED_DATABASE_URL",
    "postgresql://ratelimiter:local-dev-only@localhost:25432/ratelimiter_test",
)


class Toxiproxy:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client

    async def add_toxic(self, proxy: str, toxic_type: str, **attributes: int) -> None:
        response = await self.client.post(
            f"/proxies/{proxy}/toxics",
            json={"name": toxic_type, "type": toxic_type, "attributes": attributes},
        )
        response.raise_for_status()

    async def set_enabled(self, proxy: str, enabled: bool) -> None:
        response = await self.client.post(f"/proxies/{proxy}", json={"enabled": enabled})
        response.raise_for_status()


@pytest.fixture
async def toxiproxy() -> AsyncIterator[Toxiproxy]:
    async with httpx.AsyncClient(base_url=TOXIPROXY_URL, timeout=5) as client:
        await client.post("/reset")
        try:
            yield Toxiproxy(client)
        finally:
            await client.post("/reset")


def unique_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def metric(text: str, name: str) -> float:
    for family in text_string_to_metric_families(text):
        for sample in family.samples:
            if sample.name == name:
                return float(sample.value)
    return 0.0


async def test_hung_redis_is_bounded_by_timeouts(
    toxiproxy: Toxiproxy, in_process_app: InProcessFactory
) -> None:
    async with in_process_app(
        redis_url=PROXIED_REDIS_URL,
        fail_mode_open=True,
        redis_timeout_ms=300,
        breaker_cooldown_sec=30,
        breaker_min_calls=5,
    ) as app:
        await app.post("/check", json={"client_id": unique_id("warm")})
        await toxiproxy.add_toxic("redis", "timeout", timeout=0)
        durations, bodies = [], []
        for _ in range(16):
            started = time.monotonic()
            response = await app.post("/check", json={"client_id": unique_id("hang")})
            durations.append(time.monotonic() - started)
            bodies.append(response.json())
        health = (await app.get("/health")).json()

    degraded = [body["degraded"] for body in bodies]
    opened_at = degraded.index("redis_unavailable")
    assert opened_at >= 3
    assert degraded[:opened_at] == ["redis_timeout"] * opened_at
    assert all(body["allowed"] is False for body in bodies[:opened_at])
    assert all(duration < 1.0 for duration in durations[: opened_at + 1])
    assert degraded[opened_at:] == ["redis_unavailable"] * (len(bodies) - opened_at)
    assert all(body["allowed"] is True for body in bodies[opened_at:])
    assert all(duration < 0.1 for duration in durations[opened_at + 1 :])
    assert health["breaker"] == "open"


async def test_slow_redis_overload_is_shed_without_failing_open(
    toxiproxy: Toxiproxy, in_process_app: InProcessFactory
) -> None:
    async with in_process_app(
        redis_url=PROXIED_REDIS_URL,
        fail_mode_open=True,
        redis_max_connections=2,
        redis_queue_timeout_ms=150,
        redis_timeout_ms=1000,
    ) as app:
        await app.post("/check", json={"client_id": unique_id("warm")})
        await toxiproxy.add_toxic("redis", "latency", latency=200)
        responses = await asyncio.gather(
            *(app.post("/check", json={"client_id": unique_id("slow")}) for _ in range(20))
        )
        health = (await app.get("/health")).json()

    bodies = [response.json() for response in responses]
    shed = [body for body in bodies if body["degraded"] == "overloaded"]
    served = [body for body in bodies if body["degraded"] is None]
    assert len(shed) + len(served) == len(bodies)
    assert shed and served
    assert all(body["allowed"] is False for body in shed)
    assert all(body["allowed"] is True for body in served)
    assert health["breaker"] == "closed"


async def test_postgres_outage_keeps_last_limits_snapshot(
    toxiproxy: Toxiproxy, in_process_app: InProcessFactory, database: asyncpg.Connection
) -> None:
    client_id = unique_id("vip")
    await seed_client_limits(database, {client_id: 2})

    async with in_process_app(
        database_url=PROXIED_DATABASE_URL, limits_refresh_sec=0.2, limits_query_timeout_ms=300
    ) as app:
        await toxiproxy.set_enabled("postgres", False)
        await asyncio.sleep(1.0)
        during_outage = [
            (await app.post("/check", json={"client_id": client_id})).json()["allowed"]
            for _ in range(3)
        ]
        errors = metric((await app.get("/metrics")).text, "ratelimit_limits_refresh_errors_total")
        stale_age = (await app.get("/health")).json()["limits_snapshot_age_sec"]
        await toxiproxy.set_enabled("postgres", True)
        await asyncio.sleep(1.0)
        fresh_age = (await app.get("/health")).json()["limits_snapshot_age_sec"]

    assert during_outage == [True, True, False]
    assert errors >= 2
    assert stale_age > 0.8
    assert fresh_age < 0.5
