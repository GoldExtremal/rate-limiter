import asyncio
import time
import uuid

import httpx
from docker.models.containers import Container
from prometheus_client.parser import text_string_to_metric_families
from redis.asyncio import Redis

from app.limiter import key_for
from tests.chaos.conftest import (
    APP_URLS,
    COMPOSE_BREAKER_COOLDOWN_SEC,
    NGINX_URL,
    InProcessFactory,
    wait_for_redis,
)
from tests.conftest import TEST_REDIS_URL


def unique_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def metric(text: str, name: str, **labels: str) -> float:
    for family in text_string_to_metric_families(text):
        for sample in family.samples:
            if sample.name == name and sample.labels == labels:
                return float(sample.value)
    return 0.0


async def test_redis_stop_degrades_and_recovers_without_restart(
    redis_chaos: Container, in_process_app: InProcessFactory
) -> None:
    client_id = unique_id("outage")
    async with (
        in_process_app(fail_mode_open=False) as closed_app,
        httpx.AsyncClient(timeout=10) as http,
    ):
        redis_chaos.stop(timeout=1)

        direct = [
            await http.post(f"{url}/check", json={"client_id": client_id})
            for url in APP_URLS
            for _ in range(6)
        ]
        demo = await http.get(f"{NGINX_URL}/demo", headers={"X-Client-Id": client_id})
        health = [(await http.get(f"{url}/health")).json() for url in APP_URLS]
        errors_before = metric(
            (await http.get(f"{APP_URLS[0]}/metrics")).text,
            "ratelimit_redis_errors_total",
            kind="connection",
        )
        for _ in range(10):
            await http.post(f"{APP_URLS[0]}/check", json={"client_id": client_id})
        errors_after = metric(
            (await http.get(f"{APP_URLS[0]}/metrics")).text,
            "ratelimit_redis_errors_total",
            kind="connection",
        )

        closed_checks = [
            await closed_app.post("/check", json={"client_id": client_id}) for _ in range(6)
        ]
        closed_demo = await closed_app.get("/demo", headers={"X-Client-Id": client_id})

        redis_chaos.start()
        await wait_for_redis()
        await asyncio.sleep(COMPOSE_BREAKER_COOLDOWN_SEC + 0.5)
        recovered = [
            (await http.post(f"{url}/check", json={"client_id": client_id})).json()
            for url in APP_URLS
        ]
        closed_recovered = (await closed_app.post("/check", json={"client_id": client_id})).json()

    assert all(response.status_code == 200 for response in direct)
    assert all(response.json()["allowed"] is True for response in direct)
    assert all(response.json()["degraded"] == "redis_unavailable" for response in direct)
    assert demo.status_code == 200
    assert demo.headers["X-RateLimit-Degraded"] == "redis_unavailable"
    assert "X-RateLimit-Limit" not in demo.headers
    assert [entry["breaker"] for entry in health] == ["open", "open"]
    assert errors_after == errors_before

    assert all(response.status_code == 200 for response in closed_checks)
    assert all(response.json()["allowed"] is False for response in closed_checks)
    assert closed_demo.status_code == 503
    assert int(closed_demo.headers["Retry-After"]) >= 1

    assert [body["degraded"] for body in recovered] == [None, None]
    assert all(isinstance(body["remaining"], int) for body in recovered)
    assert closed_recovered["degraded"] is None
    assert closed_recovered["allowed"] is True


async def test_hung_redis_is_bounded_by_timeouts(
    redis_chaos: Container, in_process_app: InProcessFactory
) -> None:
    async with in_process_app(
        fail_mode_open=True, redis_timeout_ms=300, breaker_cooldown_sec=30, breaker_min_calls=5
    ) as app:
        redis_chaos.pause()
        durations, bodies = [], []
        for _ in range(8):
            started = time.monotonic()
            response = await app.post("/check", json={"client_id": unique_id("hang")})
            durations.append(time.monotonic() - started)
            bodies.append(response.json())
        health = (await app.get("/health")).json()

    assert [body["degraded"] for body in bodies[:4]] == ["redis_timeout"] * 4
    assert all(body["allowed"] is False for body in bodies[:4])
    assert all(body["degraded"] == "redis_unavailable" for body in bodies[4:])
    assert all(body["allowed"] is True for body in bodies[4:])
    assert all(duration < 1.0 for duration in durations[:5])
    assert all(duration < 0.1 for duration in durations[5:])
    assert health["breaker"] == "open"


async def test_hung_redis_overload_is_shed_not_failed_open(
    redis_chaos: Container, in_process_app: InProcessFactory
) -> None:
    async with in_process_app(
        fail_mode_open=True,
        redis_timeout_ms=1000,
        redis_max_connections=2,
        redis_queue_timeout_ms=100,
        breaker_failure_threshold=100,
    ) as app:
        redis_chaos.pause()
        responses = await asyncio.gather(
            *(app.post("/check", json={"client_id": unique_id("shed")}) for _ in range(10))
        )

    bodies = [response.json() for response in responses]
    shed = [body for body in bodies if body["degraded"] == "overloaded"]
    assert all(response.status_code == 200 for response in responses)
    assert len(shed) == 8
    assert all(body["allowed"] is False for body in bodies)
    assert sum(body["degraded"] == "redis_timeout" for body in bodies) == 2


async def test_out_of_memory_rejects_script_before_execution(
    redis_chaos: Container, in_process_app: InProcessFactory
) -> None:
    client_id = unique_id("oom")
    redis = Redis.from_url(TEST_REDIS_URL)
    try:
        await redis.zadd(key_for(client_id), {"expired-entry": 1})
        async with in_process_app(fail_mode_open=True) as app:
            await redis.config_set("maxmemory", "1")
            response = await app.post("/check", json={"client_id": client_id})
            metrics_text = (await app.get("/metrics")).text
            await redis.config_set("maxmemory", "256mb")
        remaining_entries = await redis.zrange(key_for(client_id), 0, -1)
    finally:
        await redis.delete(key_for(client_id))
        await redis.aclose()

    assert response.status_code == 200
    assert response.json()["degraded"] == "redis_unavailable"
    assert metric(metrics_text, "ratelimit_redis_errors_total", kind="oom") == 1
    assert metric(metrics_text, "ratelimit_script_errors_total") == 0
    assert remaining_entries == [b"expired-entry"]
